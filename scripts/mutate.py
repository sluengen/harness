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

A mutation that breaks *collection* reddens hundreds of unrelated tests and gets
recorded as a kill it never earned. #336 had one entry that looked exactly like
that (a 0.25s "kill" against a 0.70s baseline) and only a manual re-run
established it was genuine.

#360 called the no-op direction self-limiting, on the grounds that SURVIVED
forces an investigation. That was a habit rather than a mechanism, and #209 is
what it cost: mutating a gate stage from ``-m "not docker"`` to
``tests/unit -m "not docker"`` is a real textual change that lands exactly once
and passes every refusal above, but both spellings collected the identical 4,826
tests. It reported SURVIVED. Worse, the same tick's adversarial review used a
no-op mutation as its evidence for a real BLOCKING finding — the finding was
right and its proof was invalid, independently. So #365 made the direction
mechanical too (see *Proving a survivor was live*).

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
6. **Observable** — each declared probe, deduplicated by argv, runs **twice on
   the pristine tree**. Two differing runs refuse: a nondeterministic probe
   would differ against every mutation and certify them all live. A nonzero exit
   refuses: a probe already broken breaks identically on both trees, digests
   identically, and would report every entry ``inert``. A probe that cannot run
   at all raises :class:`RunnerUnavailableError`, the same infrastructure /
   red-tree split the baseline makes. Last, so a mistyped node id — the cheaper
   defect — is never paid for at observable prices.

Proving a survivor was live
---------------------------

An entry may declare ``observe``: argv **appended to this interpreter**, run
with ``cwd`` inside the tree. It is not a program name and not a shell string,
and that is the keystone rather than a detail — the harness prepends
:data:`sys.executable`, so the one binary this module may spawn stays pinned by
the AST guard in ``tests/unit/test_mutate.py`` and an observable gets exactly the
trust the tree's own suite already carries. It runs on the mutated tree **only
for a would-be survivor**, inside the same ``try`` that guarantees the restore:

* digests differ → ``survived``, rendered ``SURVIVED (LIVE)``. A real gap.
* digests match → ``inert``. The mutation changed nothing: a table defect, and
  its own exit code, because such a report cannot be read as evidence at all.
* no ``observe`` → ``survived``, rendered ``SURVIVED (UNPROVEN)``, with the
  remedy named. Nobody has shown the mutation was live, so it is not evidence
  that the guard is weak.

An entry that *killed* something is manifestly live and is never asked for a
second witness — letting a narrow probe downgrade a real kill would have the
observable deciding a case the failure set already settled. A mutated
observation that could not complete is ``errored``, never ``inert``: reading a
missing measurement as a measurement of nothing is the same lie in a new place.

No captured output reaches the report, the refusals or the work dir — digests,
counts and durations only, per :func:`render`'s existing rule. A report gets
pasted into a ticket, and the nondeterminism refusal is exactly where a probe's
output is largest and least predictable; the refusal names the argv instead.

One consequence is stated rather than guarded: an observable is arbitrary Python
running as the invoking user, so one that *writes* into the tree can leave it
dirty, since the restore guarantee covers only the declared targets. Sandboxing
it would be a second, weaker copy of the trust decision the suite already is.

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
or an observable itself could not complete, ``4`` at least one entry was
``inert``. ``4`` dominates ``1``: "your table proved nothing" is a louder answer
than "a guard is weak", and they call for different work.

The table, in TOML — ``'''literal'''`` strings need no escaping, and ``old``/
``new`` are exact source substrings full of quotes and backslashes::

    select = ["-m", "unit or guard"]
    sentinel_file = "scripts/cadence.py"
    sentinel_text = "Release-cadence bounds"

    [[mutation]]
    id = "tracked-set-ignores-pathspec"
    file = "tests/_gitutil.py"
    old = '''["git", "ls-files", "-z", "--", str(path)]'''
    new = '''["git", "ls-files", "-z"]'''
    kills = ["tests/unit/test_gitutil.py::test_removed_path_returns_empty"]
    note = "a tracked-set query that ignores its pathspec answers about the repo"
    # Optional. Argv appended to this interpreter, not a command line. Declare it
    # on any entry whose failure mode is "the edit changed nothing" — otherwise a
    # survivor is reported UNPROVEN and cannot be cited against the guard.
    observe = ["-c", "import tests._gitutil as g; print(g.tracked_files_under('.'))"]

This is a **build-time instrument**, not a gate stage: it proves a new guard
while the guard is being written. ``scripts/verify.sh`` does not run it, and
``tests/unit/test_mutate_end_to_end.py`` pins that.

Stdlib only, in the shape of :mod:`cadence`. Three departures from the run's
design, recorded so they are legible in the diff rather than in someone's
reasoning:

* The optional ``--json <path>`` report dump was **dropped**, on the stated
  ground that nothing consumed it and the rendered report is the contract a tick
  reads. #363 restored it, because that ground expired: an automated reader runs
  this module as a subprocess and classifies each entry with no human in the
  loop. It reads :func:`json_report`, never :func:`render` — deriving a verdict
  from a human summary is the defect #207 *is*, and this module's own rule
  against parsing ``N passed`` says so.
* ``Baseline`` carries only ``passed``, ``collected`` and ``duration_s``, not the
  design's ``failed``/``errored``. A baseline that is not green refuses, so its
  red set cannot reach any later stage — carrying it would be dead data that
  reads as though something consults it.
* The child's environment gained ``PYTHONPYCACHEPREFIX``, which the design did
  not specify. It was **added in response to a real failure**, not a
  precaution: see :func:`PytestRunner.__call__` for what a same-size mutation
  does without it.
"""

# size: over the ceiling on documentation, not on logic — the code is well under
# it, and the balance is the recorded rationale that IS this ticket's deliverable
# (#360). A harness whose rules are structural rather than remembered has to
# state, at each rule, the defect that rule exists to stop; deleting that to fit
# the ceiling deletes the feature. #365 kept that balance: the liveness fork adds
# one refusal, one outcome and one seam, and most of its lines are the four
# defects it names. The extraction candidates are the two concrete sides of the
# injected seams, `PytestRunner` and `PythonObserver` — they stay, together,
# because a tick reads one file to learn the instrument and because the pair now
# shares the `PYTHONPYCACHEPREFIX` decision, which is the thing most likely to be
# re-derived wrongly if the two ever sit in different files.

from __future__ import annotations

import argparse
import hashlib
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
from typing import TextIO

__all__ = [
    "Baseline",
    "EntryResult",
    "Mutation",
    "MutationTable",
    "OUTCOMES",
    "Observation",
    "Observer",
    "PythonObserver",
    "PytestRunner",
    "RefusalError",
    "Report",
    "RunOutcome",
    "RunnerUnavailableError",
    "check_plan",
    "exit_code",
    "json_report",
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

#: The members of that vocabulary, in the order :func:`render` reads best.
#: Load-bearing rather than a second list to keep in sync: :class:`EntryResult`
#: refuses an outcome outside it, so a classifier that invents a sixth verdict
#: raises on the first test that reaches the branch. That mattered when
#: ``mypy``'s scope excluded ``scripts/`` and a ``Literal`` alias would have been
#: an unenforced list; since #435 the gate type-checks this file, and the
#: runtime refusal is kept because it is the stronger of the two. It is also
#: what lets a doc guard *derive* what ``CONTRIBUTING.md`` must document, instead
#: of hand-listing it and going stale the way #365 left it (#366).
OUTCOMES: tuple[Outcome, ...] = ("killed", "survived", "mispredicted", "errored", "inert")


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
    """One table entry: an exact edit, the tests it must kill, and how to witness it."""

    id: str
    file: str
    old: str
    new: str
    kills: frozenset[str]
    note: str = ""
    #: argv **appended to this interpreter** — the behavioural observable (#365).
    #: Empty means not declared, which is what every #360-era entry is.
    observe: tuple[str, ...] = ()


@dataclass(frozen=True)
class Observation:
    """One run of an observable, reduced to something safe to compare and report.

    ``stdout``/``stderr`` are captured because the digest is taken over them, and
    are **never rendered** — a report gets pasted into a ticket, and a probe's
    output can carry absolute paths, environment values and secrets. The refusal
    messages print the argv instead, so the operator re-runs it in their own
    terminal, where the output belongs.
    """

    ok: bool
    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""
    duration_s: float = 0.0
    detail: str = ""

    @property
    def digest(self) -> str:
        """sha256 over the length-prefixed parts, so no concatenation collides.

        Bytes, not text, for the reason :func:`_apply` works in bytes: newline
        translation must never decide a verdict. Length-prefixed, so a probe
        printing ``"a"`` to stdout and ``"b"`` to stderr cannot digest the same
        as one printing ``"ab"`` to stdout.
        """
        digest = hashlib.sha256()
        for part in (str(self.returncode).encode("utf-8"), self.stdout, self.stderr):
            digest.update(f"{len(part)}:".encode())
            digest.update(part)
        return digest.hexdigest()


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
    #: Populated only when the observable actually ran on both trees (#365).
    pristine_digest: str = ""
    mutated_digest: str = ""

    def __post_init__(self) -> None:
        """The vocabulary is closed, and this is what closes it (#366).

        Constructed in exactly one place (:func:`_classify`), so the check costs
        nothing and cannot be routed around. Without it, ``OUTCOMES`` would be a
        second copy of the classifier's literals, free to drift from them — and a
        doc guard deriving from a stale copy reports currency it cannot see.
        """
        if self.outcome not in OUTCOMES:
            raise ValueError(
                f"{self.outcome!r} is not one of {OUTCOMES} — add it there, and to "
                "CONTRIBUTING.md's mutation section, which is derived from it"
            )


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

#: ``(tree, observe) -> Observation``. The same seam, one level down: the
#: liveness fork is provable without spawning anything either.
Observer = Callable[[Path, tuple[str, ...]], Observation]


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
    _refuse_parallel_selection(path, select)

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


def _refuse_parallel_selection(path: Path, select: list[str]) -> None:
    """Refuse an xdist selection, because the plugin cannot observe across workers.

    :mod:`_mutate_outcomes` accumulates node ids in module-level sets and writes
    them at ``pytest_sessionfinish``. Under ``-n`` each worker gets its own
    interpreter and its own copy of those sets, so the file that survives holds
    a fraction of the run — or none of it. Every entry would then report
    ``survived`` while the suite was in fact killing tests, which is precisely
    the lie this module exists to remove, arriving from the runner instead of
    from the table.

    Worth refusing rather than documenting: since #358 the gate's own pytest
    stage runs ``-n auto``, so copying that flag into a table's ``select`` is
    now the obvious thing to try. A refusal names the reason; a silent wrong
    answer costs a re-derivation.
    """
    flags = {"-n", "--numprocesses", "--dist"}
    for item in select:
        head = item.split("=", 1)[0]
        parallel = head in flags or (item.startswith("-n") and len(item) > 2)
        if parallel:
            raise RefusalError(
                "table",
                f"{path}: `select` passes {item!r}, but this harness cannot observe "
                "outcomes across xdist workers — each worker would record into its "
                "own copy of the plugin's sets and every entry would read as "
                "`survived`. Narrow the selection instead (a path, or -m).",
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
        observe=_parse_observe(where, ident, entry.get("observe")),
    )


def _parse_observe(where: str, ident: str, observe: object) -> tuple[str, ...]:
    """``observe`` is argv appended to this interpreter — never a command line.

    A program name would put a second binary within this module's reach, and the
    one binary it may spawn is pinned structurally by
    ``tests/unit/test_mutate.py::test_the_module_spawns_only_python_never_git``.
    So the harness prepends :data:`sys.executable` and the table supplies the
    rest: the observable gets exactly the trust the tree's own suite already has,
    and no more. A shell string is refused rather than split, because splitting
    it here would be the first step toward reaching that second binary.
    """
    if observe is None:
        return ()
    if (
        not isinstance(observe, list)
        or not observe
        or not all(isinstance(arg, str) and arg for arg in observe)
    ):
        raise RefusalError(
            "table",
            f"{where} ({ident}): `observe` must be a non-empty list of non-empty "
            "strings — it is argv appended to this interpreter (`sys.executable`), "
            'not a shell command line. Write ["-c", "import sel; print(sel.chosen())"], '
            'not "python -c ...".',
        )
    return tuple(observe)


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
    # ``root`` is already resolved, so ``naive`` differs from ``candidate``
    # exactly when a symlink *inside* the tree redirected the walk — comparing
    # a resolved path against an unresolved one instead would call every
    # relative ``--tree`` a symlink.
    naive = root / mutation.file
    candidate = naive.resolve()
    if not str(candidate).startswith(str(root) + os.sep):
        raise RefusalError(
            "containment",
            f"{mutation.id}: {mutation.file} resolves to {candidate}, outside the "
            f"tree {root} — refusing to write outside the tree under test",
        )
    if not candidate.is_file():
        raise RefusalError("containment", f"{mutation.id}: {mutation.file} is not a file in {root}")
    if candidate != naive:
        raise RefusalError(
            "containment",
            f"{mutation.id}: {mutation.file} reaches its target through a symlink "
            f"({candidate}) — refusing, because the report would name a path that "
            "is not the file the bytes land in",
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


def _check_observables(
    table: MutationTable, tree: Path, observer: Observer
) -> dict[tuple[str, ...], str]:
    """Prove every declared observable is a usable witness, on the pristine tree.

    Returns the pristine digest per distinct argv. Deduplicated across entries:
    two entries sharing one probe pay for two runs in total, not two each.

    An observable is the thing that will decide whether a survivor is a weak
    guard or a table defect, so it is checked the way the baseline is — before
    any file is written, and refusing rather than guessing:

    * **Nondeterministic** (a timestamp, a duration, an unsorted set) — the two
      pristine runs differ, so it would "differ" against any mutation too and
      would silently certify every entry as live. That is an unguarded degree of
      freedom of exactly the kind #360 refused a blast-radius threshold for.
    * **Already failing** on the pristine tree — a broken probe breaks
      identically on both trees, producing identical digests and reporting every
      mutation ``inert``: a wrong verdict that accuses the table, delivered with
      confidence. This is the green-baseline rule, applied to the observable.
    * **Unrunnable** — infrastructure, not a fact about the tree, so it raises
      :class:`RunnerUnavailableError` (exit 3) rather than refusing, the same
      split :func:`_check_baseline` already makes.

    No captured output reaches any message here. The argv is named instead; the
    operator re-runs it in their own terminal.
    """
    by_argv: dict[tuple[str, ...], list[str]] = {}
    for mutation in table.mutations:
        if mutation.observe:
            by_argv.setdefault(mutation.observe, []).append(mutation.id)

    digests: dict[tuple[str, ...], str] = {}
    for observe, idents in by_argv.items():
        where = f"the observable for {', '.join(idents)} ({_argv_text(observe)})"
        runs = []
        for attempt in (1, 2):
            observation = observer(tree, observe)
            if not observation.ok:
                raise RunnerUnavailableError(
                    f"{where} did not complete on run {attempt} of 2 on the "
                    f"pristine tree: {observation.detail or 'no detail'}"
                )
            if observation.returncode != 0:
                raise RefusalError(
                    "observable",
                    f"{where} exited {observation.returncode} on the pristine tree. "
                    "A probe that is already failing breaks identically on the "
                    "mutated tree, so every entry would report `inert` — an "
                    "accusation against the table, made on no evidence.",
                )
            runs.append(observation)
        if runs[0].digest != runs[1].digest:
            raise RefusalError(
                "observable",
                f"{where} is not deterministic: two runs on the pristine tree "
                f"digested {runs[0].digest[:12]}… and {runs[1].digest[:12]}…. "
                "It would differ against any mutation and certify every entry as "
                "live. Sort what it prints, and drop any clock, duration, path or "
                "address from it.",
            )
        digests[observe] = runs[0].digest
    return digests


def _argv_text(observe: tuple[str, ...]) -> str:
    """The observable as the operator would re-type it. Argv only — never output."""
    return " ".join(["<python>", *observe])


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
    mutation: Mutation,
    outcome: RunOutcome,
    baseline: Baseline,
    *,
    pristine_digest: str = "",
    mutated: Observation | None = None,
) -> EntryResult:
    """The one rule: ``observed == kills``, with the survivor forked on liveness.

    The fork touches ``survived`` and nothing else. ``killed`` and
    ``mispredicted`` are unchanged (AC-5) and are never asked for a second
    witness: an entry that killed something is manifestly live, and letting a
    narrow probe downgrade a real kill would have the observable deciding cases
    it is not qualified to decide.
    """
    observed = outcome.observed
    missing = mutation.kills - observed
    unexpected = observed - mutation.kills
    detail = outcome.detail
    mutated_digest = ""
    if not outcome.ok:
        verdict = "errored"
    elif observed == mutation.kills:
        verdict = "killed"
    elif not observed:
        verdict, detail, mutated_digest = _classify_survivor(
            mutation, pristine_digest, mutated, detail
        )
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
        pristine_digest=pristine_digest if mutated_digest else "",
        mutated_digest=mutated_digest,
    )


def _classify_survivor(
    mutation: Mutation,
    pristine_digest: str,
    mutated: Observation | None,
    detail: str,
) -> tuple[Outcome, str, str]:
    """Nothing died. Did anything *happen*?

    Three answers, and the point of #365 is that they are three rather than one:
    no observable was declared (``survived``, unproven — rendered as such), the
    observable moved (``survived``, and now genuinely evidence that the guard is
    weak), or it did not (``inert``, a table defect).

    A mutated observation that could not complete is ``errored``, never
    ``inert``: reading a missing measurement as a measurement of nothing is how
    a harness lies in the operator's favour.
    """
    if not mutation.observe:
        return "survived", detail, ""
    if mutated is None or not mutated.ok:
        why = (mutated.detail if mutated is not None else "") or "no detail"
        named = f"{_argv_text(mutation.observe)} did not complete on the mutated tree: {why}"
        return "errored", f"{detail}; {named}" if detail else named, ""
    if mutated.returncode != 0:
        # A nonzero exit is a genuine difference from the pristine tree, which
        # the digest already carries — this branch exists only so the report can
        # say *why* it differed without printing the probe's output.
        detail = (
            f"{detail}; " if detail else ""
        ) + f"the observable exited {mutated.returncode} on the mutated tree"
    if mutated.digest == pristine_digest:
        return "inert", detail, mutated.digest
    return "survived", detail, mutated.digest


def run_plan(
    table: MutationTable,
    tree: Path,
    *,
    runner: Runner,
    observer: Observer | None = None,
    work_dir: Path | None = None,
    only: Sequence[str] = (),
    out: TextIO | None = None,
) -> Report:
    """Validate, baseline, then run every selected entry against a pristine tree.

    ``out`` receives the work-dir announcement (default ``sys.stdout``). It is a
    parameter rather than a bare print so a test can prove the announcement
    happened on a path that never returns a report.
    """
    targets = check_plan(table, tree, only=only)
    select = list(table.select)

    baseline = _check_baseline(table, runner(tree, select))
    _check_predictions(table, baseline)
    # After `prediction`, still before any write. A mistyped node id is the
    # cheaper defect to find, so it must not be paid for at observable prices.
    observe_with: Observer = observer if observer is not None else PythonObserver()
    pristine_digests = _check_observables(table, tree, observe_with)

    work_dir = work_dir or Path(tempfile.mkdtemp(prefix="mutate-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    # Announced here, before the first write, and flushed — not folded into the
    # report. The report is only reached on a clean return, so deferring this
    # line to it would print the recovery path in exactly the cases that do not
    # need it and withhold it in the one that does: a crash, a SIGTERM, or the
    # SIGKILL no handler can catch, after which these backups are the only copy
    # of the pre-run bytes and this path is the only way to find them.
    print(f"work dir: {work_dir}", file=out if out is not None else sys.stdout, flush=True)
    backups = _Backups(work_dir=work_dir)
    backups.take(targets.values(), tree)

    selected = [m for m in table.mutations if not only or m.id in set(only)]
    results: list[EntryResult] = []
    for mutation in selected:
        # The single restore guarantee. Every path out of this block goes
        # through it: a normal return, a runner exception, the ``SystemExit`` a
        # ``SIGTERM`` handler raises. An outer ``try/finally`` around the whole
        # loop was written first and then deleted — it was mutation-proved to
        # kill nothing, because no code outside this block can leave a target
        # written, so it was defence that could not be exercised.
        mutated: Observation | None = None
        try:
            _apply(targets[mutation.id], mutation)
            outcome = runner(tree, select)
            # Inside the try, so the tree is still mutated — and only for a
            # would-be survivor, the one case whose verdict depends on it.
            if mutation.observe and outcome.ok and not outcome.observed:
                mutated = observe_with(tree, mutation.observe)
        finally:
            backups.restore()
        results.append(
            _classify(
                mutation,
                outcome,
                baseline,
                pristine_digest=pristine_digests.get(mutation.observe, ""),
                mutated=mutated,
            )
        )

    return Report(
        baseline=baseline,
        results=tuple(results),
        work_dir=work_dir,
        select=tuple(select),
    )


def exit_code(report: Report) -> int:
    """0 only when every entry killed exactly what it predicted.

    ``4`` dominates ``1`` (#365): an ``inert`` entry means the report cannot be
    read as evidence *at all*, which is a louder answer than "a guard is weak".
    An *unproven* survivor stays ``1`` — the report says so on its own line, and
    the entry did fail its prediction either way.
    """
    if any(result.outcome == "inert" for result in report.results):
        return 4
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
        f"baseline: {len(baseline.passed)} passed, {baseline.collected} collected, "
        f"{baseline.duration_s:.1f}s  [{' '.join(report.select)}]",
    ]
    for result in report.results:
        lines.append(
            f"{result.mutation.id:<24} {_label(result):<13} "
            f"{len(result.mutation.kills)} predicted, {len(result.observed)} observed, "
            f"collected {result.collected}, {result.duration_s:.1f}s"
        )
        for advisory in _liveness_advisory(result):
            lines.append(f"{'':<24}   {advisory}")
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
    inert = sum(1 for r in report.results if r.outcome == "inert")
    if exit_code(report) == 0:
        lines.append("RESULT: honest — every entry killed exactly what it predicted")
    elif inert:
        lines.append(
            f"RESULT: {inert} entr{'y is' if inert == 1 else 'ies are'} inert — "
            "the table is defective, not the guard"
        )
    else:
        bad = sum(1 for r in report.results if r.outcome != "killed")
        lines.append(f"RESULT: {bad} entr{'y' if bad == 1 else 'ies'} did not kill as predicted")
    return "\n".join(lines)


def _label(result: EntryResult) -> str:
    """The outcome column, with the qualifier that says what a survivor means.

    The word ``SURVIVED`` keeps its place — a reader skims the column — and the
    qualifier sits immediately beside it, because the whole defect #365 fixes is
    that ``SURVIVED`` alone was an unclassified result a reader could take for
    whichever of two meanings suited them.
    """
    if result.outcome != "survived":
        return result.outcome.upper()
    return "SURVIVED (LIVE)" if result.mutation.observe else "SURVIVED (UNPROVEN)"


def _liveness_advisory(result: EntryResult) -> list[str]:
    """What the entry's liveness means, and — when it is unknown — what to add.

    Digests are abbreviated and the observable's captured output appears
    nowhere, per this module's "node ids, counts and durations only" rule.
    """
    if result.outcome == "inert":
        return [
            f"the observable produced identical output on the pristine and mutated "
            f"tree (sha256 {result.mutated_digest[:12]}…). The mutation changed no "
            f"behaviour: this is a defect in entry `{result.mutation.id}`, not a weak guard.",
        ]
    if result.outcome != "survived":
        return []
    if result.mutation.observe:
        return [
            f"the observable moved ({result.pristine_digest[:12]}… → "
            f"{result.mutated_digest[:12]}…): the mutation was live and the guard "
            "did not notice it. A real gap.",
        ]
    return [
        f"unproven: entry `{result.mutation.id}` declares no `observe`, so nothing "
        "shows this mutation was live — it may simply have changed nothing, as four "
        "of #336's twenty entries did. This is not evidence that the guard is weak.",
        'add e.g. observe = ["-c", "import <module>; print(<what this edit should '
        'change>)"] to the entry, and re-run.',
    ]


def json_report(report: Report) -> dict[str, object]:
    """The same observations as :func:`render`, shaped for a machine reader (#363).

    An automated reader runs this module as a subprocess and has to classify
    each entry without a human in the loop. The alternative — parsing
    :func:`render` — is textually the defect #207 *is*, so the producer grows a
    machine channel rather than the consumer growing a scraper.

    The **same** disclosure rule applies as to :func:`render`, and it binds
    harder here because the output is pasted into a ticket: node ids, counts,
    durations and digests only. In particular a
    mutation's ``old``/``new`` are exact source substrings of the tree under
    review and are deliberately **absent**; ``id`` is the handle a consumer cites
    by, and it is the one the entry's author chose.

    ``predicted`` / ``observed`` / ``missing`` / ``unexpected`` travel as sorted
    node-id **lists**, not counts: ``observed`` being a strict superset of
    ``predicted`` is what makes a collection-breaker legible as ``mispredicted``,
    and equal-sized-but-different sets are indistinguishable by count alone. A
    consumer that only needs the counts can take the lengths; one that only has
    the counts cannot recover the sets.
    """
    return {
        "select": list(report.select),
        "baseline": {
            "passed": len(report.baseline.passed),
            "collected": report.baseline.collected,
            "duration_s": report.baseline.duration_s,
        },
        "results": [
            {
                "id": result.mutation.id,
                "outcome": result.outcome,
                "predicted": sorted(result.mutation.kills),
                "observed": sorted(result.observed),
                "missing": sorted(result.missing),
                "unexpected": sorted(result.unexpected),
                "collected": result.collected,
                "duration_s": result.duration_s,
                "detail": result.detail,
                "pristine_digest": result.pristine_digest,
                "mutated_digest": result.mutated_digest,
            }
            for result in report.results
        ],
    }


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


@dataclass(frozen=True)
class PythonObserver:
    """Runs ``[sys.executable, *observe]`` in ``tree`` and digests what came back.

    The interpreter is prepended here rather than named in the table, which is
    what keeps the module's "the only binary it may spawn is this interpreter"
    property structural rather than remembered — see :func:`_parse_observe`.

    The observable is arbitrary Python running as the invoking user with
    ``cwd=tree``, i.e. exactly the trust the tree's own suite already carries.
    Sandboxing it would be a second, weaker copy of that same decision. One
    consequence is worth stating plainly rather than guarding: the restore
    guarantee covers only the declared targets, so an observable that *writes*
    into the tree can leave it dirty and this harness will not notice.
    """

    timeout_s: float = DEFAULT_TIMEOUT_S

    def __call__(self, tree: Path, observe: tuple[str, ...]) -> Observation:
        with tempfile.TemporaryDirectory(prefix="mutate-observe-") as scratch:
            env = dict(os.environ)
            # Load-bearing, not hygiene — the same trap as the runner's, arriving
            # through the new path. A mutation is very often exactly the same
            # size as what it replaced, so an in-tree ``__pycache__`` written in
            # the same clock second would serve the *unmutated* module here and
            # the observable would digest identically: a live mutation certified
            # ``inert``, which is the one verdict this stage must never invent.
            env["PYTHONPYCACHEPREFIX"] = str(Path(scratch) / "pycache")
            started = time.monotonic()
            try:
                completed = subprocess.run(  # noqa: S603 - list form, argv[0] is this interpreter
                    [sys.executable, *observe],
                    cwd=tree,
                    env=env,
                    capture_output=True,
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return Observation(
                    ok=False,
                    duration_s=time.monotonic() - started,
                    detail=f"timed out after {self.timeout_s:.0f}s",
                )
            except OSError as exc:
                return Observation(
                    ok=False,
                    duration_s=time.monotonic() - started,
                    detail=f"could not spawn the observable: {exc}",
                )
            return Observation(
                ok=True,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                duration_s=time.monotonic() - started,
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
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_path",
        metavar="PATH",
        help="also write the report as JSON for a machine consumer (#363)",
    )
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
            observer=PythonObserver(timeout_s=args.timeout),
            work_dir=args.work_dir,
            only=args.only,
        )
    except RefusalError as refusal:
        print(f"refused ({refusal.reason}): {refusal}", file=sys.stderr)
        return 2
    except RunnerUnavailableError as unavailable:
        print(f"runner unavailable: {unavailable}", file=sys.stderr)
        return 3

    if args.json_path is not None:
        args.json_path.write_text(json.dumps(json_report(report), indent=2), encoding="utf-8")
    print(render(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
