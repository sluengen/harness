"""The nightly promotion step, **executed** rather than read (#396).

``scripts/promotion-step.sh`` is the shell the nightly ``dev → staging`` job
runs. Until #396 the property that mattered — *every verb invocation on the
runner receives a ``--repo`` inside the exported ``HARNESS_WORKSPACE_ROOTS``
allowlist* — was asserted by deriving call sites out of the workflow's YAML with
a regex. That instrument cost four tickets (#390, #391, #393, #394), each
teaching it one more way shell writes the same call, and it went red on the
refactor that would have removed the defect class outright. The rule it broke is
now recorded: ``specs/architecture-principles.md`` → *CI logic lives in a script,
not in a `run:` block*.

So this module runs the script. ``uv`` and ``harness`` are stubbed onto ``PATH``;
the stub records, per invocation, the allowlist **as the verb saw it** together
with the argv it was handed. That one record collapses the three text assertions
the old guard needed — the export exists, it precedes the first call, its value
admits the argument — into one executed check, because a call made before the
export records an empty allowlist and the production
:func:`~harness.workspace.resolve_repo_root` then refuses it. Ordering stops
being a text property.

Two further things follow from executing rather than reading:

* **Spelling stops mattering.** ``--repo`` is resolved by ``click`` itself, from
  the flag name the production ``REPO_OPTION`` declares, so ``--repo=x``, a
  backslash continuation, a repeated flag and an argument expanded from a shell
  array are all just argv by the time the assertion sees them. The four
  spellings below rewrite the *script's own* text and re-run it, which is how
  that claim is measured rather than argued — including the indirect shape the
  old instrument structurally forbade and #397 will ship.
* **The branches are reachable.** A ``needs_ticket`` start, a non-``pr_ready``
  continue, a red gate and a failing verb are canned payloads, so the refusal
  paths are exercised instead of being asserted as text.

Nothing here can touch the real repository or the real gate. The ``uv`` shim
``exec``s only inside its own stub directory, the subprocess runs with ``cwd``
under ``tmp_path``, and the only ``scripts/verify.sh`` the script can reach is
the fake one this module writes into the candidate worktree.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import click
import pytest

from harness.cli._repo import REPO_OPTION
from harness.workspace import (
    WORKSPACE_ROOTS_ENV,
    NotAGitTopLevel,
    WorkspaceNotAllowed,
    resolve_repo_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"

#: The verbs the promotion drives, in the order it drives them.
_LIFECYCLE_VERBS = ("promote start", "promote continue", "promote pr")

#: The promotion id every canned payload reports. Filename-safe: it lands in
#: ``$RUNNER_TEMP/promotion-gate-<id>.log``.
_PROMOTION_ID = "p-2026-08-12-1"

#: Written by the fake gate into its *current directory*, so its presence is
#: evidence the script ran the gate inside the worktree the verb named.
_GATE_SENTINEL = "gate-ran"

#: Echoed by the fake gate, so the captured gate log can be shown to be the
#: fake gate's output rather than an empty file.
_GATE_TOKEN = "fake-gate-output-marker"

#: The `indirect` rewrite declares its arrays immediately before this, their
#: first use — a position derived from the rewrite itself rather than from any
#: other line of the script.
_FIRST_ARRAY_USE = '"${repo_flag_1[@]}"'

#: Every refusal the property below raises carries this, so a test asserting on
#: the refusal cannot be satisfied by the coverage floor's message instead.
_REFUSED = "did not resolve inside the exported allowlist"

#: The unallowlisted argument the refuse-direction tests substitute. Deliberately
#: not under ``/tmp``: the mutation table points the allowlist itself at ``/tmp``,
#: and a "bad" path that happened to sit inside the mutated root would be refused
#: for the wrong reason.
_OUTSIDE_THE_CHECKOUT = "/outside-the-checkout"

#: A transparent ``uv`` shim. ``__STUB_DIR__`` is substituted at write time and
#: the ``exec`` is by **absolute path inside the stub dir**: a renamed or deleted
#: recorder is an exec failure, never a fall-through to the project's real
#: ``harness`` console script, which is on ``PATH`` during a gate run.
_UV_STUB = """#!/bin/sh
set -eu
if [ "${1-}" != "run" ]; then
  echo "stub uv: unexpected invocation: $*" >&2
  exit 97
fi
shift
cmd="$1"
shift
exec "__STUB_DIR__/$cmd" "$@"
"""

#: The recorder. One record per invocation, fields NUL-separated and records
#: newline-separated: ``[allowlist as the verb saw it, cwd, *argv]``. Recording
#: the allowlist *per invocation* is the load-bearing choice — it is what turns
#: "the export precedes the first call" from a text property into an executed
#: one.
_HARNESS_STUB = """#!/bin/sh
set -eu
{ printf '%s\\0' "${HARNESS_WORKSPACE_ROOTS-}" "$PWD" "$@"; printf '\\n'; } \\
  >> "$HARNESS_STUB_RECORD"
payload="$HARNESS_STUB_PAYLOADS/$1-$2.json"
if [ ! -f "$payload" ]; then
  echo "stub harness: no canned payload for $1-$2" >&2
  exit 96
fi
cat "$payload"
code="$HARNESS_STUB_PAYLOADS/$1-$2.exit"
if [ -f "$code" ]; then
  exit "$(cat "$code")"
fi
exit 0
"""


# --- Running the script -------------------------------------------------------


@dataclass(frozen=True)
class Invocation:
    """One recorded verb call."""

    allowlist: str
    cwd: str
    argv: tuple[str, ...]

    @property
    def call(self) -> str:
        """``promote start`` and friends — the site a failure names."""
        return " ".join(self.argv[:2])


@dataclass(frozen=True)
class StepRun:
    """Everything one execution of the script produced."""

    returncode: int
    stdout: str
    stderr: str
    invocations: tuple[Invocation, ...]
    gate_log: str
    workspace: Path
    candidate: Path
    copy: Path


def _default_payloads(candidate: Path) -> dict[str, str]:
    """The happy path: a gated candidate, a clean continue, an opened PR."""
    return {
        "promote-start.json": json.dumps(
            {
                "promotion_id": _PROMOTION_ID,
                "status": "gate_pending",
                "worktree_path": str(candidate),
            }
        ),
        "promote-continue.json": json.dumps(
            {"promotion_id": _PROMOTION_ID, "status": "pr_ready"}
        ),
        "promote-pr.json": json.dumps({"promotion_id": _PROMOTION_ID, "status": "opened"}),
    }


def _run_promotion_step(
    script_text: str,
    tmp_path: Path,
    *,
    gate_exit: int = 0,
    payloads: dict[str, str] | None = None,
) -> StepRun:
    """Execute ``script_text`` as the runner would, against stubbed binaries.

    Every test in this module goes through here, the baseline included: the real
    script is *copied* rather than executed in place, so one code path serves the
    real input and every rewritten spelling, and
    :func:`test_the_real_script_runs_every_verb_inside_the_allowlist` asserts the
    copy is byte-identical to the tracked file.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    # ``is_git_top_level`` only stats for a ``.git`` entry (it must accept a
    # linked worktree, whose ``.git`` is a file), so no real repository is needed.
    (workspace / ".git").touch()

    candidate = tmp_path / "candidate"
    (candidate / "scripts").mkdir(parents=True, exist_ok=True)
    gate = candidate / "scripts" / "verify.sh"
    gate.write_text(
        f'#!/bin/sh\n: > "{_GATE_SENTINEL}"\necho "{_GATE_TOKEN}"\nexit {gate_exit}\n',
        encoding="utf-8",
    )

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    for name, text in (
        ("uv", _UV_STUB.replace("__STUB_DIR__", str(stub_dir))),
        ("harness", _HARNESS_STUB),
    ):
        stub = stub_dir / name
        stub.write_text(text, encoding="utf-8")
        stub.chmod(0o755)
    # Pinned rather than ambient: the script's three ``python -c`` reads must
    # resolve to this interpreter, not to whatever ``python`` the host has.
    interpreter = stub_dir / "python"
    if not interpreter.exists():
        interpreter.symlink_to(sys.executable)

    payload_dir = tmp_path / "payloads"
    payload_dir.mkdir(exist_ok=True)
    for name, content in {**_default_payloads(candidate), **(payloads or {})}.items():
        (payload_dir / name).write_text(content, encoding="utf-8")

    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    record = tmp_path / "invocations"
    record.write_bytes(b"")

    copy = tmp_path / "promotion-step.sh"
    copy.write_text(script_text, encoding="utf-8")

    env = {**os.environ}
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    env["GITHUB_WORKSPACE"] = str(workspace)
    env["RUNNER_TEMP"] = str(runner_temp)
    env["HARNESS_STUB_RECORD"] = str(record)
    env["HARNESS_STUB_PAYLOADS"] = str(payload_dir)
    # Load-bearing, not hygiene. A developer shell or the Docker wrapper may
    # export this; if it leaked in, deleting the export from the script would
    # still leave every verb with a valid allowlist and the mutation that proves
    # this module measures the export would survive.
    env.pop(WORKSPACE_ROOTS_ENV, None)

    result = subprocess.run(
        ["bash", str(copy)],
        # Deliberately not the repo root: it is the second, independent control
        # that keeps the real four-minute ``scripts/verify.sh`` unreachable when
        # the script's own ``cd "$worktree"`` is removed.
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        # Comfortably under the global 120s pytest-timeout cap, so a script that
        # hangs is reported here — naming the script — rather than as a timed-out
        # test naming nothing.
        timeout=60,
    )

    logs = sorted(runner_temp.glob("promotion-gate-*.log"))
    return StepRun(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        invocations=_parse_record(record),
        gate_log=logs[0].read_text(encoding="utf-8") if logs else "",
        workspace=workspace,
        candidate=candidate,
        copy=copy,
    )


def _parse_record(record: Path) -> tuple[Invocation, ...]:
    """Read the recorder's file back into invocations."""
    invocations: list[Invocation] = []
    for line in record.read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        fields = line.split("\0")
        if fields and fields[-1] == "":
            fields = fields[:-1]
        invocations.append(
            Invocation(allowlist=fields[0], cwd=fields[1], argv=tuple(fields[2:]))
        )
    return tuple(invocations)


def _recorded_flag(run: StepRun, call: str, flag: str) -> str:
    """The value ``call`` was handed for ``flag``."""
    matches = [inv for inv in run.invocations if inv.call == call]
    assert len(matches) == 1, (
        f"expected exactly one `harness {call}` invocation; recorded "
        f"{[inv.call for inv in run.invocations]}"
    )
    argv = list(matches[0].argv)
    assert flag in argv, f"`harness {call}` was not passed {flag}: {argv}"
    return argv[argv.index(flag) + 1]


# --- The property, asserted against the production resolver -------------------

#: The flag spelling comes from the production option, so a rename follows
#: automatically rather than being restated here.
_REPO_DECLS = tuple(REPO_OPTION.param_decls)


def _repo_argument(argv: list[str]) -> str | None:
    """The value ``click`` itself resolves ``--repo`` to, for this argv.

    Implemented with ``click`` rather than by hand because a hand-rolled scan
    would re-implement exactly the semantics four tickets got wrong — the joiner,
    flag order, and a repeated flag resolving to the *last* occurrence.
    """
    captured: dict[str, str | None] = {}

    @click.command(
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True}
    )
    @click.option(*_REPO_DECLS, "repo", default=None)
    @click.argument("rest", nargs=-1, type=click.UNPROCESSED)
    def probe(repo: str | None, rest: tuple[str, ...]) -> None:
        captured["repo"] = repo

    probe.main(args=list(argv), standalone_mode=False)
    return captured["repo"]


def _assert_every_invocation_resolves_inside_the_allowlist(
    run: StepRun, *, expected_calls: tuple[str, ...] = _LIFECYCLE_VERBS
) -> None:
    """Every recorded invocation resolved a repo path inside its own allowlist.

    ``resolve_repo_root`` is the production function every verb resolves through;
    restating the allowlist rule here would assert nothing about the code that
    enforces it. The coverage floor is ``>=`` rather than ``==`` so a fourth verb
    call added later is *covered* rather than refused — the derivation guard's one
    genuine virtue, kept.
    """
    assert expected_calls, "an empty expectation would make the floor below vacuous"
    calls = {inv.call for inv in run.invocations}
    assert calls >= set(expected_calls), (
        f"the script recorded {sorted(calls)}, which does not cover "
        f"{sorted(expected_calls)} — nothing below was measured on the missing calls"
    )

    # Every offending invocation is reported, not just the first. A refusal that
    # stopped at invocation one would name only that call site, so a test asking
    # whether *its* call was refused would be answered about someone else's.
    problems: list[str] = []
    for inv in run.invocations:
        repo = _repo_argument(list(inv.argv))
        if repo is None:
            problems.append(f"`harness {inv.call}` passed no --repo at all: {inv.argv}")
            continue
        try:
            resolved = resolve_repo_root(repo, {WORKSPACE_ROOTS_ENV: inv.allowlist})
        except (WorkspaceNotAllowed, NotAGitTopLevel) as refusal:
            problems.append(
                f"`harness {inv.call}` {_REFUSED}: --repo {repo!r} against "
                f"{WORKSPACE_ROOTS_ENV}={inv.allowlist!r} — {refusal}"
            )
            continue
        if resolved != run.workspace.resolve():
            problems.append(
                f"`harness {inv.call}` {_REFUSED}: --repo {repo!r} resolved to "
                f"{resolved}, not the checkout {run.workspace.resolve()}"
            )
    assert not problems, "\n".join(problems)


# --- Rewriting the script's own spelling (AC-3) -------------------------------

#: A ``--repo`` and the argument written for it, in either joiner spelling.
_REPO_PAIR = re.compile(r"--repo(?:\s+|=)(\S+)")

_SPELLINGS = ("spaced", "glued", "continued", "indirect")


def _logical_lines(text: str) -> list[str]:
    """Fold trailing-backslash continuations, preserving the text on rejoin."""
    blocks: list[str] = []
    buffered = ""
    for line in text.split("\n"):
        buffered = f"{buffered}\n{line}" if buffered else line
        if not line.rstrip().endswith("\\"):
            blocks.append(buffered)
            buffered = ""
    if buffered:
        blocks.append(buffered)
    return blocks


def _rewrite(spelling: str, text: str) -> str:
    """Rewrite every ``--repo`` pair into ``spelling``, preserving its argument."""
    if spelling == "spaced":
        return text
    if spelling == "glued":
        return _REPO_PAIR.sub(lambda m: f"--repo={m.group(1)}", text)
    if spelling == "continued":
        return _REPO_PAIR.sub(lambda m: f"--repo \\\n  {m.group(1)}", text)
    if spelling == "indirect":
        return _indirect(text)
    raise AssertionError(f"unknown spelling {spelling!r}")


def _indirect(text: str) -> str:
    """The #397 shape: a ``--repo`` that exists nowhere at the call sites.

    Each pair becomes a shell array expanded at the call site, declared
    immediately before the **first use** — deliberately not "after the export",
    which would tie this rewrite to the export's position and make the variant
    break under a mutation that merely moves it. This is the shape the old text
    instrument structurally forbade.
    """
    values: list[str] = []

    def replace(match: re.Match[str]) -> str:
        values.append(match.group(1))
        return f'"${{repo_flag_{len(values)}[@]}}"'

    replaced = _REPO_PAIR.sub(replace, text)
    lines = replaced.split("\n")
    uses = [i for i, line in enumerate(lines) if _FIRST_ARRAY_USE in line]
    assert uses, f"the rewrite produced no {_FIRST_ARRAY_USE} to declare before"
    at = uses[0]
    lines[at:at] = [
        f"repo_flag_{index}=( --repo {value} )" for index, value in enumerate(values, start=1)
    ]
    return "\n".join(lines)


def _shell_text(text: str) -> str:
    """``text`` without its comment lines — what the spelling floors measure."""
    return "\n".join(line for line in text.split("\n") if not line.lstrip().startswith("#"))


def _assert_the_rewrite_is_real(spelling: str, original: str, rewritten: str) -> None:
    """A rewrite that silently did nothing would make a variant a copy of the baseline."""
    pairs = _REPO_PAIR.findall(original)
    assert len(pairs) >= 3, (
        f"expected at least the three lifecycle call sites to pass --repo; found {pairs}"
    )
    assert "--from dev --to staging" in original, (
        "the known `promote start` call site is gone, so these rewrites are "
        "operating on something other than the promotion"
    )
    assert not [
        line
        for line in original.split("\n")
        if line.lstrip().startswith("#") and _REPO_PAIR.search(line)
    ], "a comment line matches the rewriter's pattern, so a rewrite would edit prose"

    body = _shell_text(rewritten)
    if spelling == "spaced":
        assert rewritten == original, "the baseline spelling must be the identity"
        return

    assert rewritten != original, f"the {spelling!r} rewrite changed nothing"
    if spelling == "glued":
        assert "--repo=" in body and "--repo " not in body, body
    elif spelling == "continued":
        assert "--repo \\\n" in body, body
    elif spelling == "indirect":
        assert body.count("repo_flag_1=(") == 1, body
        naming = [line for line in body.split("\n") if "--repo" in line]
        assert naming and all(line.lstrip().startswith("repo_flag_") for line in naming), naming


def _with_call_argument(text: str, call: str, value: str) -> str:
    """Rewrite the ``--repo`` argument of the ``harness <call>`` invocation only."""
    blocks = _logical_lines(text)
    hits = [i for i, block in enumerate(blocks) if f"harness {call}" in block]
    assert len(hits) == 1, (
        f"expected exactly one `harness {call}` invocation in the script; found {len(hits)}"
    )
    rewritten, count = _REPO_PAIR.subn(lambda _: f"--repo {value}", blocks[hits[0]])
    assert count == 1, f"`harness {call}` passes --repo {count} times, expected 1"
    assert rewritten != blocks[hits[0]], "the rewrite changed nothing, so it controls for nothing"
    blocks[hits[0]] = rewritten
    return "\n".join(blocks)


# --- The tests ----------------------------------------------------------------


def test_the_real_script_runs_every_verb_inside_the_allowlist(tmp_path: Path) -> None:
    """AC-2, on the byte-identical tracked script.

    Every invocation the script made resolved a ``--repo`` inside the allowlist
    that invocation itself saw — checked through the production resolver, so no
    copy of the allowlist rule exists in this module.
    """
    run = _run_promotion_step(SCRIPT.read_text(encoding="utf-8"), tmp_path)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert run.copy.read_bytes() == SCRIPT.read_bytes(), (
        "the executed copy is not the tracked script, so this proves nothing about it"
    )
    _assert_every_invocation_resolves_inside_the_allowlist(run)


@pytest.mark.parametrize("spelling", _SPELLINGS)
def test_the_property_holds_however_the_flag_is_spelled(spelling: str, tmp_path: Path) -> None:
    """AC-3, accept direction: the same script, four ways of writing ``--repo``.

    ``indirect`` is the case that matters most — it is the shape the old text
    instrument structurally forbade and the one #397 will ship.
    """
    original = SCRIPT.read_text(encoding="utf-8")
    rewritten = _rewrite(spelling, original)
    _assert_the_rewrite_is_real(spelling, original, rewritten)

    run = _run_promotion_step(rewritten, tmp_path)

    assert run.returncode == 0, f"the {spelling!r} script failed: {run.stderr}\n{run.stdout}"
    _assert_every_invocation_resolves_inside_the_allowlist(run)


@pytest.mark.parametrize("spelling", _SPELLINGS)
def test_an_unallowlisted_argument_is_refused_however_it_is_spelled(
    spelling: str, tmp_path: Path
) -> None:
    """AC-3's discriminator: the instrument must refuse, in every spelling.

    Without this direction "it passes everything" would satisfy the accept
    direction above. It doubles as proof each rewrite produced a *runnable*
    script rather than shell that happens to parse.
    """
    original = _with_call_argument(
        SCRIPT.read_text(encoding="utf-8"), "promote start", _OUTSIDE_THE_CHECKOUT
    )
    rewritten = _rewrite(spelling, original)
    _assert_the_rewrite_is_real(spelling, original, rewritten)

    run = _run_promotion_step(rewritten, tmp_path)

    assert run.returncode == 0, f"the {spelling!r} script failed: {run.stderr}\n{run.stdout}"
    with pytest.raises(AssertionError) as refused:
        _assert_every_invocation_resolves_inside_the_allowlist(run)
    assert _REFUSED in str(refused.value), str(refused.value)


@pytest.mark.parametrize("call", _LIFECYCLE_VERBS)
def test_an_unallowlisted_argument_at_any_call_site_is_refused(
    call: str, tmp_path: Path
) -> None:
    """Every call site is covered, not merely the first one.

    The refusal must also *name* the mutated call, which is what ties each
    parameter to its own invocation rather than to whichever one happens to fail.
    """
    text = _with_call_argument(SCRIPT.read_text(encoding="utf-8"), call, _OUTSIDE_THE_CHECKOUT)

    run = _run_promotion_step(text, tmp_path)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    with pytest.raises(AssertionError) as refused:
        _assert_every_invocation_resolves_inside_the_allowlist(run)
    assert _REFUSED in str(refused.value), str(refused.value)
    assert f"`harness {call}`" in str(refused.value), str(refused.value)


def test_the_gate_runs_inside_the_worktree_the_verb_named(tmp_path: Path) -> None:
    """The gate is invoked in ``worktree_path``, and its exit code is forwarded.

    Two independent witnesses that it ran there at all: the sentinel the fake gate
    writes into its *current directory*, and the token it echoes into the gate log
    the script captures. Removing the script's ``cd "$worktree"`` leaves both
    absent, because the subprocess's own cwd is deliberately not a checkout.
    """
    run = _run_promotion_step(SCRIPT.read_text(encoding="utf-8"), tmp_path, gate_exit=0)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert (run.candidate / _GATE_SENTINEL).is_file(), (
        "the gate did not run inside the worktree the verb named"
    )
    assert _GATE_TOKEN in run.gate_log, f"the gate log holds no gate output: {run.gate_log!r}"
    assert _recorded_flag(run, "promote continue", "--gate-exit") == "0"
    assert _recorded_flag(run, "promote continue", "--gate-log").endswith(
        f"promotion-gate-{_PROMOTION_ID}.log"
    )


def test_a_red_gate_is_reported_as_its_own_exit_code(tmp_path: Path) -> None:
    """A failing gate reaches ``promote continue`` as ``--gate-exit 1``.

    Behaviour identity (AC-1): the step never repairs and never rounds a red gate
    to green — it hands the verb the code it observed and lets the verb classify.
    """
    run = _run_promotion_step(SCRIPT.read_text(encoding="utf-8"), tmp_path, gate_exit=1)

    assert _recorded_flag(run, "promote continue", "--gate-exit") == "1"


def test_a_start_that_is_not_gate_pending_stops_the_step(tmp_path: Path) -> None:
    """A refused ``promote start`` stops the job — no gate, no continue, no PR.

    The payload still carries a ``worktree_path``, deliberately: the step must
    stop because it read the *status*, not because the rest of the payload was
    missing. Without it, deleting the status check would fail on a ``KeyError``
    and read like the check still working.
    """
    run = _run_promotion_step(
        SCRIPT.read_text(encoding="utf-8"),
        tmp_path,
        payloads={
            "promote-start.json": json.dumps(
                {
                    "promotion_id": _PROMOTION_ID,
                    "status": "needs_ticket",
                    "worktree_path": str(tmp_path / "candidate"),
                }
            )
        },
    )

    assert run.returncode == 1, f"expected exit 1; got {run.returncode}\n{run.stderr}"
    assert "::error::" in run.stdout, run.stdout
    assert _PROMOTION_ID in run.stdout and "needs_ticket" in run.stdout, run.stdout
    calls = {inv.call for inv in run.invocations}
    assert calls == {"promote start"}, calls
    assert not (run.candidate / _GATE_SENTINEL).exists(), "the gate ran after a refused start"


def test_a_continue_that_is_not_pr_ready_never_advances_staging(tmp_path: Path) -> None:
    """The second status check: a gated candidate that failed never reaches ``pr``."""
    run = _run_promotion_step(
        SCRIPT.read_text(encoding="utf-8"),
        tmp_path,
        payloads={
            "promote-continue.json": json.dumps(
                {"promotion_id": _PROMOTION_ID, "status": "needs_ticket"}
            )
        },
    )

    assert run.returncode == 1, f"expected exit 1; got {run.returncode}\n{run.stderr}"
    assert "::error::" in run.stdout, run.stdout
    assert "staging was not advanced" in run.stdout, run.stdout
    calls = {inv.call for inv in run.invocations}
    assert "promote continue" in calls, calls
    assert "promote pr" not in calls, calls


def test_a_failing_verb_aborts_the_step(tmp_path: Path) -> None:
    """``set -e`` holds: a verb that exits non-zero stops everything after it."""
    run = _run_promotion_step(
        SCRIPT.read_text(encoding="utf-8"),
        tmp_path,
        payloads={"promote-start.exit": "1"},
    )

    assert run.returncode != 0, "a failing verb left the step reporting success"
    calls = {inv.call for inv in run.invocations}
    assert calls == {"promote start"}, calls


# --- Coverage of the argv probe, through the same function the tests use ------

#: ``(id, argv, resolved)``. These pin :func:`_repo_argument`'s own behaviour —
#: the joiner, flag order, last-wins for a repeat, and absence — through the very
#: function the property above calls, so no second copy of the rule can drift.
_ARGV_CASES = [
    ("spaced", ["promote", "start", "--repo", "/a", "--from", "dev", "--to", "staging"], "/a"),
    ("glued", ["promote", "start", "--repo=/a", "--from", "dev"], "/a"),
    ("repeated-last-wins", ["promote", "pr", "--repo", "/a", "--repo", "/tmp"], "/tmp"),
    (
        "interleaved",
        ["promote", "continue", "--promotion-id", "x", "--gate-exit", "0", "--repo", "/a"],
        "/a",
    ),
    ("absent", ["promote", "pr"], None),
]


@pytest.mark.parametrize(
    ("argv", "resolved"),
    [(argv, resolved) for _, argv, resolved in _ARGV_CASES],
    ids=[name for name, _, _ in _ARGV_CASES],
)
def test_the_probe_resolves_repo_the_way_click_does(
    argv: list[str], resolved: str | None
) -> None:
    """Spelling, order and repetition are click's business, and this proves which
    answer it gives — the ``repeated-last-wins`` case is #394's defect, now
    measured by click itself rather than by a regex imitating it."""
    assert _repo_argument(argv) == resolved


def test_the_probe_reads_the_production_flag_spelling() -> None:
    """The floor under the cases above: the probe keys on the flag the verbs
    declare, and on nothing else. A rename of ``REPO_OPTION``'s declaration moves
    this module with it instead of leaving it asserting over a dead flag."""
    assert _REPO_DECLS, "the production --repo option declares no flag name"
    flag = _REPO_DECLS[0]
    assert flag.startswith("--"), flag
    assert _repo_argument(["promote", "pr", flag, "/a"]) == "/a"
    assert _repo_argument(["promote", "pr", "--not-the-repo-flag", "/a"]) is None
