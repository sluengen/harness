#!/usr/bin/env python3
"""Mutation harness — the rules that keep a mutation table honest, made structural (#360).

A tick proves a new guard by mutating the guarded code and watching the guard
die. The mutation **table** is genuinely bespoke: each entry is a specific edit
to a specific line, and it stays outside this repo. Everything around it is not,
and was rewritten from scratch every tick — backup and restore, the landing
assert, the containment assert, the green-baseline precondition, the runner, the
kill/survive determination, the report. That shared part is exactly where the
bugs were, and they were bugs that lied *in the operator's favour*:

* **#207** — an aggregate ``N passed`` assertion reported a kill that never
  happened. One assert could fail two ways, so its message lied in one of them.
* **#336** — four of twenty mutations were **no-ops that evaluated to the
  original value**. ``OVERRIDES = {} or {...}`` returns the non-empty right
  operand; breaking a memo's *read* key while leaving its *write* key intact
  degrades to no caching rather than to a wrong cache; deleting one entry from a
  four-entry table never exercises an "is it empty" floor; a comment edit changes
  nothing at all. Each printed SURVIVED and each cost a re-derivation.

The no-op direction is self-limiting — SURVIVED forces an investigation. The
other direction is not: a mutation that breaks *collection* reddens hundreds of
unrelated tests and gets recorded as a kill it never earned. #336 had one entry
that looked exactly like that (a 0.25s "kill" against a 0.70s baseline) and only
a manual re-run established it was genuine.

One rule, both directions
-------------------------

An entry **declares the tests it must kill**, and the harness compares the
observed failure set to that prediction by **equality**:

* ``observed == kills`` → ``killed``. The only pass.
* ``observed`` empty → ``survived``. The no-op, and the genuinely weak guard.
* ``observed`` anything else → ``mispredicted``. The collection-breaker's set is
  a strict superset, so it fails the same comparison the no-op's empty set fails.

Set equality is deliberately the *whole* rule. Containment ("the predicted test
is among the failures") cannot see over-kill. Containment plus a blast-radius
ceiling (``len(observed) <= N``) would need a threshold, and a threshold is an
unguarded degree of freedom — #336's false kill would have sat under any
plausible one. There is deliberately **no** flag that rewrites ``kills`` from
``observed``: that converts every mispredicted entry into a silent pass, which is
the failure this module exists to remove.

What it refuses, and when
-------------------------

Every refusal happens **before any file is written**, in this order, so a wrong
tree is never mutated and a wrong table never costs a suite run:

1. **Table** — ``id`` unique, ``kills`` non-empty, ``new != old`` (the one no-op
   catchable without running anything), sentinel declared.
2. **Containment** — the sentinel file carries the sentinel text, and every
   target resolves to a real file *inside* the tree with no symlink component.
   The realistic accident is a tick's table run against the primary checkout.
3. **Landing** — ``old`` occurs **exactly once** in the target, counted on the
   pristine text. Zero and two are distinct messages, never one assert that can
   fail two ways (#207). Checked for the whole table before the first write, so
   entry 3's typo cannot leave entries 1 and 2 mutated.
4. **Baseline** — the selection runs clean first. A pre-existing red can never be
   read as a kill, and a selection collecting nothing is refused rather than
   returning a table of identical survivors.
5. **Prediction** — every declared node id appears in the baseline's *passed*
   set. A mistyped node id is a table defect, not a survivor.

Restoration reads **only** from byte-for-byte backups taken before the first
write, held in memory and copied under the work dir; the path is printed so a
hard kill is recoverable by hand. The harness spawns no ``git`` at all — no
``git checkout``, no ``git stash``. ``git checkout -- .`` is the revert that cost
#163 forty minutes of finished work, and ``tests/unit/test_mutate.py`` pins that
the only binary this module can spawn is its own interpreter.

Every entry runs against the pristine tree (mutate → run → restore), so a table
may carry two entries on one file without entry 2 matching against entry 1's
residue.

Observing outcomes
------------------

Node ids come from pytest verbatim, via the one-file plugin
:mod:`_mutate_outcomes`. Reconstructing a node id from ``--junitxml``'s
``classname`` is lossy for classes and parametrization, and reconstructing rather
than observing is precisely the step that lied in #207. Parsing ``N passed`` *is*
#207.

Usage
-----

::

    python scripts/mutate.py check --table <path> [--tree <path>]
    python scripts/mutate.py run   --table <path> [--tree <path>] [--work-dir <path>]
                                   [--only <id>]... [--timeout <seconds>]

``check`` runs everything that needs no suite run and writes nothing, ever — the
cheap loop for getting a table to land before spending a baseline. ``run`` does
``check``, then the baseline, then the entries.

Exit codes follow the verbs' convention that 2 means *refused, nothing
happened*: ``0`` every entry killed, ``1`` at least one entry did not (mutations
ran, everything was restored), ``2`` refused before any write, ``3`` the runner
itself could not complete.

The table, in TOML — ``'''literal'''`` strings need no escaping, and ``old``/
``new`` are exact source substrings full of quotes and backslashes::

    select = ["-m", "unit or guard"]
    sentinel_file = "changelog.d/360.md"
    sentinel_text = "a shared mutation harness"

    [[mutation]]
    id = "memo-read-key"
    file = "harness/cli/review.py"
    old = '''    key = (sha, model)'''
    new = '''    key = (sha,)'''
    kills = ["tests/unit/test_review_memo.py::test_memo_keys_on_model"]
    note = "the memo's read key must include the model"

This is a **build-time instrument**, not a gate stage: it proves a new guard
while the guard is being written. ``scripts/verify.sh`` does not run it, and
``tests/unit/test_mutate_end_to_end.py`` pins that.

Stdlib only, in the shape of :mod:`cadence`. Departure from the design, recorded:
the optional ``--json <path>`` report dump was dropped — nothing consumes it, and
the rendered report is the contract a tick reads.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType

__all__ = [
    "Baseline",
    "EntryResult",
    "Mutation",
    "MutationTable",
    "PytestRunner",
    "RefusalError",
    "Report",
    "RunOutcome",
    "RunnerUnavailableError",
    "check_plan",
    "exit_code",
    "load_table",
    "main",
    "render",
    "run_plan",
]

#: ``scripts/*.py`` -> ``parent.parent`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Where the child interpreter finds :mod:`_mutate_outcomes`.
PLUGIN_DIR = Path(__file__).resolve().parent

#: The environment variable the plugin writes its observations to.
OUTCOME_ENV = "MUTATE_OUTCOME_PATH"

#: Default per-run ceiling. A mutation can induce an infinite loop; that is an
#: ``errored`` entry, not a hung harness.
DEFAULT_TIMEOUT_S = 900.0

#: The closed outcome vocabulary. ``killed`` is the only pass.
Outcome = str


class RefusalError(Exception):
    """Refused before any file was written.

    ``reason`` is one of ``table``, ``containment``, ``landing``, ``baseline`` or
    ``prediction`` — a stable tag, so a caller (and a test) can assert *which*
    rule refused rather than matching prose.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class RunnerUnavailableError(Exception):
    """The baseline run itself could not complete — infrastructure, not a red tree.

    Distinct from ``RefusalError(reason="baseline")``: a red baseline is a fact about
    the tree the operator must fix, whereas an unrunnable pytest says nothing
    about the tree at all.
    """


@dataclass(frozen=True)
class Mutation:
    """One table entry: an exact edit, and the tests it must kill."""

    id: str
    file: str
    old: str
    new: str
    kills: frozenset[str]
    note: str = ""


@dataclass(frozen=True)
class MutationTable:
    """The whole of what a tick supplies."""

    select: tuple[str, ...]
    sentinel_file: str
    sentinel_text: str
    mutations: tuple[Mutation, ...]


@dataclass(frozen=True)
class RunOutcome:
    """One suite run, as observed — never as derived from a summary line."""

    ok: bool
    passed: frozenset[str]
    failed: frozenset[str]
    errored: frozenset[str]
    collected: int
    duration_s: float
    detail: str = ""

    @property
    def observed(self) -> frozenset[str]:
        """Everything that did not pass. The set an entry's prediction meets."""
        return self.failed | self.errored


@dataclass(frozen=True)
class Baseline:
    """The clean run every entry is measured against."""

    passed: frozenset[str]
    collected: int
    duration_s: float


@dataclass(frozen=True)
class EntryResult:
    """One entry's verdict, carrying both directions of the mismatch."""

    mutation: Mutation
    outcome: Outcome
    observed: frozenset[str]
    missing: frozenset[str]
    unexpected: frozenset[str]
    collected: int
    duration_s: float
    detail: str = ""


@dataclass(frozen=True)
class Report:
    """Everything the run observed, rendered by :func:`render`."""

    baseline: Baseline
    results: tuple[EntryResult, ...]
    work_dir: Path
    select: tuple[str, ...]


#: ``(tree, select) -> RunOutcome``. Injected so the decision logic, the
#: backup/restore logic and every refusal are provable without spawning a suite.
Runner = Callable[[Path, list[str]], RunOutcome]


# ---------------------------------------------------------------------------
# The table.
# ---------------------------------------------------------------------------


def load_table(path: Path) -> MutationTable:
    """Parse and validate a table. Raises :class:`RefusalError` with ``reason='table'``."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RefusalError("table", f"no mutation table at {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RefusalError("table", f"{path} is not valid TOML: {exc}") from exc

    for key in ("sentinel_file", "sentinel_text"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise RefusalError(
                "table",
                f"{path}: `{key}` is required and must be a non-empty string — "
                "containment is what stops a table running against the wrong checkout",
            )

    select = raw.get("select", ["-m", "unit or guard"])
    if not isinstance(select, list) or not all(isinstance(item, str) for item in select):
        raise RefusalError("table", f"{path}: `select` must be a list of strings")

    entries = raw.get("mutation", [])
    if not isinstance(entries, list) or not entries:
        raise RefusalError("table", f"{path}: no `[[mutation]]` entries — nothing to prove")

    mutations: list[Mutation] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        mutation = _parse_entry(path, index, entry)
        if mutation.id in seen:
            raise RefusalError("table", f"{path}: duplicate mutation id {mutation.id!r}")
        seen.add(mutation.id)
        mutations.append(mutation)

    return MutationTable(
        select=tuple(select),
        sentinel_file=raw["sentinel_file"],
        sentinel_text=raw["sentinel_text"],
        mutations=tuple(mutations),
    )


def _parse_entry(path: Path, index: int, entry: object) -> Mutation:
    if not isinstance(entry, dict):
        raise RefusalError("table", f"{path}: `[[mutation]]` #{index + 1} is not a table")
    where = f"{path}: mutation #{index + 1}"
    for key in ("id", "file", "old", "new"):
        value = entry.get(key)
        if not isinstance(value, str) or not value:
            raise RefusalError("table", f"{where}: `{key}` is required and must be non-empty")
    ident = str(entry["id"])
    if entry["old"] == entry["new"]:
        raise RefusalError(
            "table",
            f"{where} ({ident}): `old` and `new` are identical — a textually "
            "unchanged entry cannot mutate anything",
        )
    kills = entry.get("kills")
    if not isinstance(kills, list) or not kills or not all(isinstance(k, str) for k in kills):
        raise RefusalError(
            "table",
            f"{where} ({ident}): `kills` must name at least one pytest node id — "
            "an entry that predicts nothing cannot fail, so it proves nothing",
        )
    note = entry.get("note", "")
    if not isinstance(note, str):
        raise RefusalError("table", f"{where} ({ident}): `note` must be a string")
    return Mutation(
        id=ident,
        file=str(entry["file"]),
        old=str(entry["old"]),
        new=str(entry["new"]),
        kills=frozenset(kills),
        note=note,
    )


# ---------------------------------------------------------------------------
# The pre-write invariants.
# ---------------------------------------------------------------------------


def _resolve_target(tree: Path, mutation: Mutation) -> Path:
    """The target's real path, refused unless it is a real file inside ``tree``.

    ``resolve()`` on both sides, so a ``..`` segment and a symlink pointing out
    of the tree are the same refusal — a symlink inside the tree can still name
    the primary checkout.
    """
    root = tree.resolve()
    candidate = (tree / mutation.file).resolve()
    if not str(candidate).startswith(str(root) + os.sep):
        raise RefusalError(
            "containment",
            f"{mutation.id}: {mutation.file} resolves to {candidate}, outside the "
            f"tree {root} — refusing to write outside the tree under test",
        )
    if not candidate.is_file():
        raise RefusalError("containment", f"{mutation.id}: {mutation.file} is not a file in {root}")
    if (tree / mutation.file).is_symlink() or candidate != (tree / mutation.file):
        raise RefusalError(
            "containment",
            f"{mutation.id}: {mutation.file} reaches its target through a symlink "
            f"({candidate}) — refusing, because the link may leave the tree",
        )
    return candidate


def _check_containment(table: MutationTable, tree: Path) -> None:
    sentinel = tree / table.sentinel_file
    if not sentinel.is_file():
        raise RefusalError(
            "containment",
            f"sentinel file {table.sentinel_file} does not exist in {tree} — "
            "this is not the tree the table was written for",
        )
    if table.sentinel_text not in sentinel.read_text(encoding="utf-8", errors="replace"):
        raise RefusalError(
            "containment",
            f"sentinel text {table.sentinel_text!r} is absent from "
            f"{table.sentinel_file} in {tree} — this is not the tree the table "
            "was written for",
        )


def _check_landing(table: MutationTable, tree: Path) -> dict[str, Path]:
    """Every entry's ``old`` occurs exactly once, on the pristine text.

    Returns the resolved target per entry id. Zero and two occurrences raise
    separate messages: one assertion that can fail two ways is #207.
    """
    targets: dict[str, Path] = {}
    for mutation in table.mutations:
        target = _resolve_target(tree, mutation)
        text = target.read_bytes().decode("utf-8")
        count = text.count(mutation.old)
        if count != 1:
            raise RefusalError(
                "landing",
                f"{mutation.id}: `old` has {count} occurrences in {mutation.file} "
                f"(exactly 1 required) — {mutation.old!r}",
            )
        targets[mutation.id] = target
    return targets


def check_plan(table: MutationTable, tree: Path, *, only: Sequence[str] = ()) -> dict[str, Path]:
    """Every invariant that needs no suite run. Writes nothing, ever."""
    _check_only(table, only)
    _check_containment(table, tree)
    return _check_landing(table, tree)


def _check_only(table: MutationTable, only: Sequence[str]) -> None:
    known = {mutation.id for mutation in table.mutations}
    unknown = sorted(set(only) - known)
    if unknown:
        raise RefusalError(
            "table",
            f"--only names no such entry: {', '.join(unknown)} "
            f"(the table has: {', '.join(sorted(known))})",
        )


def _check_baseline(table: MutationTable, baseline_run: RunOutcome) -> Baseline:
    if not baseline_run.ok:
        raise RunnerUnavailableError(
            f"the baseline run did not complete: {baseline_run.detail or 'no detail'}"
        )
    if baseline_run.collected == 0:
        raise RefusalError(
            "baseline",
            "the selection collected 0 tests — every entry would survive "
            "identically and the table would look wrong instead of the selector",
        )
    red = sorted(baseline_run.observed)
    if red:
        raise RefusalError(
            "baseline",
            "the baseline is not green, so a pre-existing red could be read as a "
            "kill. Already failing:\n  " + "\n  ".join(red),
        )
    return Baseline(
        passed=baseline_run.passed,
        collected=baseline_run.collected,
        duration_s=baseline_run.duration_s,
    )


def _check_predictions(table: MutationTable, baseline: Baseline) -> None:
    for mutation in table.mutations:
        absent = sorted(mutation.kills - baseline.passed)
        if absent:
            raise RefusalError(
                "prediction",
                f"{mutation.id}: predicted node id(s) absent from the baseline's "
                f"passed set — a mistyped prediction is a table defect, not a "
                f"survivor:\n  " + "\n  ".join(absent),
            )


# ---------------------------------------------------------------------------
# Backups and the run.
# ---------------------------------------------------------------------------


@dataclass
class _Backups:
    """Pre-run bytes for every target, and the only source a restore reads from."""

    work_dir: Path
    saved: dict[Path, bytes] = field(default_factory=dict)

    def take(self, targets: Iterable[Path], tree: Path) -> None:
        for target in sorted(set(targets)):
            blob = target.read_bytes()
            self.saved[target] = blob
            copy = self.work_dir / "backup" / target.relative_to(tree.resolve())
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_bytes(blob)

    def restore(self) -> None:
        """Write every saved blob back and prove byte-identity.

        Runs from a ``finally``, so it must not raise on the ordinary path and
        must be safe to run twice.
        """
        for target, blob in self.saved.items():
            if target.read_bytes() != blob:
                target.write_bytes(blob)
            if target.read_bytes() != blob:  # pragma: no cover - filesystem failure
                raise RuntimeError(
                    f"failed to restore {target} from its backup; the pre-run bytes "
                    f"are in {self.work_dir / 'backup'}"
                )


def _apply(target: Path, mutation: Mutation) -> None:
    """Bytes in, bytes out — never ``read_text``/``write_text``.

    Universal-newline translation would make a CRLF target's restore
    non-identical while a text comparison called it unchanged.
    """
    text = target.read_bytes().decode("utf-8")
    target.write_bytes(text.replace(mutation.old, mutation.new, 1).encode("utf-8"))


def _classify(
    mutation: Mutation, outcome: RunOutcome, baseline: Baseline
) -> EntryResult:
    """The one rule: ``observed == kills``."""
    observed = outcome.observed
    missing = mutation.kills - observed
    unexpected = observed - mutation.kills
    detail = outcome.detail
    if not outcome.ok:
        verdict = "errored"
    elif observed == mutation.kills:
        verdict = "killed"
    elif not observed:
        verdict = "survived"
    else:
        verdict = "mispredicted"
        if outcome.collected < baseline.collected:
            detail = (
                f"collection broken: collected {outcome.collected} < "
                f"{baseline.collected} baseline"
                + (f"; {detail}" if detail else "")
            )
    return EntryResult(
        mutation=mutation,
        outcome=verdict,
        observed=observed,
        missing=missing,
        unexpected=unexpected,
        collected=outcome.collected,
        duration_s=outcome.duration_s,
        detail=detail,
    )


def run_plan(
    table: MutationTable,
    tree: Path,
    *,
    runner: Runner,
    work_dir: Path | None = None,
    only: Sequence[str] = (),
) -> Report:
    """Validate, baseline, then run every selected entry against a pristine tree."""
    targets = check_plan(table, tree, only=only)
    select = list(table.select)

    baseline = _check_baseline(table, runner(tree, select))
    _check_predictions(table, baseline)

    work_dir = work_dir or Path(tempfile.mkdtemp(prefix="mutate-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    backups = _Backups(work_dir=work_dir)
    backups.take(targets.values(), tree)

    selected = [m for m in table.mutations if not only or m.id in set(only)]
    results: list[EntryResult] = []
    try:
        for mutation in selected:
            try:
                _apply(targets[mutation.id], mutation)
                outcome = runner(tree, select)
            finally:
                backups.restore()
            results.append(_classify(mutation, outcome, baseline))
    finally:
        backups.restore()

    return Report(
        baseline=baseline,
        results=tuple(results),
        work_dir=work_dir,
        select=tuple(select),
    )


def exit_code(report: Report) -> int:
    """0 only when every entry killed exactly what it predicted."""
    return 0 if all(result.outcome == "killed" for result in report.results) else 1


# ---------------------------------------------------------------------------
# The report.
# ---------------------------------------------------------------------------


def render(report: Report) -> str:
    """One stable, greppable line per entry, plus a summary.

    Node ids, counts and durations only — never pytest's tracebacks or captured
    output, so a failing assertion cannot spill environment values into a report
    a tick pastes into a ticket.
    """
    baseline = report.baseline
    lines = [
        f"work dir: {report.work_dir}",
        f"baseline: {len(baseline.passed)} passed, {baseline.collected} collected, "
        f"{baseline.duration_s:.1f}s  [{' '.join(report.select)}]",
    ]
    for result in report.results:
        lines.append(
            f"{result.mutation.id:<24} {result.outcome.upper():<13} "
            f"{len(result.mutation.kills)} predicted, {len(result.observed)} observed, "
            f"collected {result.collected}, {result.duration_s:.1f}s"
        )
        if result.mutation.note:
            lines.append(f"{'':<24}   note: {result.mutation.note}")
        if result.detail:
            lines.append(f"{'':<24}   {result.detail}")
        for nodeid in sorted(result.missing):
            lines.append(f"{'':<24}   predicted but survived: {nodeid}")
        for nodeid in sorted(result.unexpected):
            lines.append(f"{'':<24}   killed but not predicted: {nodeid}")

    tally: dict[str, int] = {}
    for result in report.results:
        tally[result.outcome] = tally.get(result.outcome, 0) + 1
    summary = ", ".join(f"{count} {name}" for name, count in sorted(tally.items()))
    lines.append(f"{len(report.results)} entries: {summary}")
    if exit_code(report) == 0:
        lines.append("RESULT: honest — every entry killed exactly what it predicted")
    else:
        bad = sum(1 for r in report.results if r.outcome != "killed")
        lines.append(f"RESULT: {bad} entr{'y' if bad == 1 else 'ies'} did not kill as predicted")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The pytest runner.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PytestRunner:
    """Runs the selection in ``tree`` and reads node ids from the plugin.

    The plugin writes the observation file; nothing here parses pytest's stdout.
    """

    timeout_s: float = DEFAULT_TIMEOUT_S

    def __call__(self, tree: Path, select: list[str]) -> RunOutcome:
        with tempfile.TemporaryDirectory(prefix="mutate-run-") as scratch:
            outcome_path = Path(scratch) / "outcomes.json"
            env = dict(os.environ)
            env[OUTCOME_ENV] = str(outcome_path)
            env["PYTHONPATH"] = os.pathsep.join(
                [str(PLUGIN_DIR), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
            )
            # A fresh bytecode cache per run, outside the tree. Python validates
            # a ``.pyc`` on the source's (mtime, size), and a mutation is very
            # often **the same size** as what it replaced — ``a + b`` -> ``a - b``
            # — so an in-tree ``__pycache__`` written in the same clock second
            # silently serves the *unmutated* module and the entry reports
            # SURVIVED having never run. Setting the prefix makes Python look
            # only here, so every run compiles from the source on disk, and it
            # keeps the harness from leaving droppings in the tree it mutates.
            env["PYTHONPYCACHEPREFIX"] = str(Path(scratch) / "pycache")
            started = time.monotonic()
            try:
                subprocess.run(  # noqa: S603 - list form, shell=False, argv[0] is this interpreter
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        *select,
                        "-q",
                        "--tb=no",
                        "-p",
                        "no:cacheprovider",
                        "-p",
                        "_mutate_outcomes",
                    ],
                    cwd=tree,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return RunOutcome(
                    ok=False,
                    passed=frozenset(),
                    failed=frozenset(),
                    errored=frozenset(),
                    collected=0,
                    duration_s=time.monotonic() - started,
                    detail=f"timed out after {self.timeout_s:.0f}s",
                )
            duration = time.monotonic() - started
            if not outcome_path.is_file():
                return RunOutcome(
                    ok=False,
                    passed=frozenset(),
                    failed=frozenset(),
                    errored=frozenset(),
                    collected=0,
                    duration_s=duration,
                    detail="the outcome plugin wrote nothing — pytest did not start",
                )
            observed = json.loads(outcome_path.read_text(encoding="utf-8"))

        return RunOutcome(
            ok=True,
            passed=frozenset(observed["passed"]),
            failed=frozenset(observed["failed"]),
            errored=frozenset(observed["errored"]),
            collected=int(observed["collected"]),
            duration_s=duration,
        )


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _install_sigterm_handler() -> None:
    """Turn ``SIGTERM`` into ``SystemExit`` so the restore ``finally`` still runs."""

    def _raise(signum: int, frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _raise)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("check", "run"))
    parser.add_argument("--table", type=Path, required=True, help="the tick's mutation table")
    parser.add_argument(
        "--tree", type=Path, default=REPO_ROOT, help="tree to mutate (defaults to this checkout)"
    )
    parser.add_argument("--work-dir", type=Path, default=None, help="where backups are kept")
    parser.add_argument(
        "--only", action="append", default=[], metavar="ID", help="run only these entries"
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args(argv)

    try:
        table = load_table(args.table)
        if args.mode == "check":
            check_plan(table, args.tree, only=args.only)
            print(f"table ok: {len(table.mutations)} entries land in {args.tree}")
            return 0
        _install_sigterm_handler()
        report = run_plan(
            table,
            args.tree,
            runner=PytestRunner(timeout_s=args.timeout),
            work_dir=args.work_dir,
            only=args.only,
        )
    except RefusalError as refusal:
        print(f"refused ({refusal.reason}): {refusal}", file=sys.stderr)
        return 2
    except RunnerUnavailableError as unavailable:
        print(f"runner unavailable: {unavailable}", file=sys.stderr)
        return 3

    print(render(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
