"""The nightly promotion step, **executed** rather than read (#396, #435).

``scripts/promotion-step.sh`` is the shell the nightly ``dev → staging`` job
runs. Until #396 its properties were asserted by deriving call sites out of the
workflow's YAML with a regex. That instrument cost four tickets (#390, #391,
#393, #394), each teaching it one more way shell writes the same call, and it
went red on the refactor that would have removed the defect class outright. The
rule it broke is now recorded: ``specs/architecture-principles.md`` → *CI logic
lives in a script, not in a `run:` block*.

So this module runs the script. **#435 changed what it drives, not whether it is
driven.** ADR 0015 retires the ``harness promote`` verb; the operator decision
keeps the ``dev → staging → main`` topology and this nightly automation, so the
script was rewritten to plain git and this guard was rewritten to stub ``git``
instead of ``uv``/``harness``. The allowlist property it used to measure
(``HARNESS_WORKSPACE_ROOTS`` admitting each verb's ``--repo``) went with the verb
— there is no allowlist in plain git — and is not replaced by a look-alike.

What executing buys, and what a text guard could not have shown:

* **The gate decides.** The fake ``scripts/verify.sh`` this module writes into
  the workspace is the only gate the script can reach, and its exit code is
  chosen per test. A red gate must leave ``git push`` unrecorded — asserted on
  the recorded argv, not on the script's text, so a rewrite that reorders the
  push above the gate check fails here rather than passing a grep.
* **Fast-forward or nothing.** ``git merge-base --is-ancestor`` is stubbed to
  refuse, and the push must again not happen. This is the case that has no
  textual signature at all: both the refusal and the success run the same lines.
* **Fail-closed inputs.** Each required environment variable is removed in turn
  and the script must abort *before* recording any git mutation.

Nothing here can touch the real repository or the real gate. Every ``git``
invocation goes to a stub on ``PATH``, the subprocess runs with ``cwd`` under
``tmp_path``, and the only ``scripts/verify.sh`` the script can reach is the fake
one this module writes into the workspace it is handed.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"

#: The two environment inputs Actions supplies and the script requires.
_REQUIRED_ENV = ("GITHUB_WORKSPACE", "RUNNER_TEMP")

#: The candidate SHA the stubbed ``git rev-parse`` reports. Filename-safe: it
#: lands in ``$RUNNER_TEMP/promotion-gate-<sha>.log``.
_CANDIDATE = "0123456789abcdef0123456789abcdef01234567"

#: Written by the fake gate into its *current directory*, so its presence is
#: evidence the script ran the gate inside the workspace rather than wherever
#: the subprocess happened to start.
_GATE_SENTINEL = "gate-ran"

#: Echoed by the fake gate, so the captured gate log can be shown to be the fake
#: gate's output rather than an empty file.
_GATE_TOKEN = "fake-gate-output-marker"

#: The mutation this whole module exists to bound. Every refusal test asserts
#: this subcommand was never recorded.
_MUTATION = "push"

#: A ``git`` recorder. One record per invocation, fields NUL-separated and
#: records newline-separated: ``[cwd, *argv]``. Behaviour per subcommand is
#: driven by files the fixture writes, so a test can make ``is-ancestor`` refuse
#: without rewriting the stub.
_GIT_STUB = """#!/bin/sh
set -eu
{ printf '%s\\0' "$PWD" "$@"; printf '\\n'; } >> "$GIT_STUB_RECORD"
case "$1" in
  rev-parse) echo "$GIT_STUB_CANDIDATE" ;;
  ls-remote) exit "$(cat "$GIT_STUB_DIR/ls-remote.exit" 2>/dev/null || echo 0)" ;;
  merge-base) exit "$(cat "$GIT_STUB_DIR/merge-base.exit" 2>/dev/null || echo 0)" ;;
  fetch) : ;;
  push) exit "$(cat "$GIT_STUB_DIR/push.exit" 2>/dev/null || echo 0)" ;;
  *) : ;;
esac
exit 0
"""


@dataclass(frozen=True)
class Invocation:
    """One recorded git call."""

    cwd: str
    argv: tuple[str, ...]

    @property
    def call(self) -> str:
        """``push``, ``merge-base`` and friends — the site a failure names."""
        return self.argv[0] if self.argv else ""


@dataclass(frozen=True)
class StepRun:
    """Everything one execution of the script produced."""

    returncode: int
    stdout: str
    stderr: str
    invocations: tuple[Invocation, ...]
    gate_log: str
    workspace: Path
    copy: Path

    @property
    def calls(self) -> set[str]:
        return {inv.call for inv in self.invocations}

    def argv_for(self, call: str) -> list[tuple[str, ...]]:
        return [inv.argv for inv in self.invocations if inv.call == call]


def _run_promotion_step(
    script_text: str,
    tmp_path: Path,
    *,
    gate_exit: int = 0,
    git_exits: dict[str, int] | None = None,
    drop_env: str | None = None,
) -> StepRun:
    """Execute ``script_text`` as the runner would, against a stubbed ``git``.

    Every test in this module goes through here, the baseline included: the real
    script is *copied* rather than executed in place, so one code path serves the
    real input and every variation, and
    :func:`test_the_real_script_promotes_a_green_candidate` asserts the copy is
    byte-identical to the tracked file.
    """
    workspace = tmp_path / "workspace"
    (workspace / "scripts").mkdir(parents=True, exist_ok=True)
    gate = workspace / "scripts" / "verify.sh"
    gate.write_text(
        f'#!/bin/sh\n: > "{_GATE_SENTINEL}"\necho "{_GATE_TOKEN}"\nexit {gate_exit}\n',
        encoding="utf-8",
    )

    stub_dir = tmp_path / "bin"
    stub_dir.mkdir(exist_ok=True)
    stub = stub_dir / "git"
    stub.write_text(_GIT_STUB, encoding="utf-8")
    stub.chmod(0o755)
    for subcommand, code in (git_exits or {}).items():
        (stub_dir / f"{subcommand}.exit").write_text(str(code), encoding="utf-8")

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
    env["GIT_STUB_RECORD"] = str(record)
    env["GIT_STUB_DIR"] = str(stub_dir)
    env["GIT_STUB_CANDIDATE"] = _CANDIDATE
    if drop_env is not None:
        env.pop(drop_env)

    result = subprocess.run(
        ["bash", str(copy)],
        # Deliberately not the repo root, and deliberately not the workspace: it
        # is the independent control that keeps the real multi-minute
        # ``scripts/verify.sh`` unreachable when the script's own ``cd`` is
        # removed.
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
        invocations.append(Invocation(cwd=fields[0], argv=tuple(fields[1:])))
    return tuple(invocations)


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _assert_nothing_was_pushed(run: StepRun, why: str) -> None:
    """The refusal direction, in one place so every caller measures the same thing.

    Asserted on the *recorded invocations*, never on the script's text: a push
    reordered above the check that forbids it is the regression this bounds, and
    it has no distinguishing text.
    """
    assert _MUTATION not in run.calls, (
        f"{why}, but the script still ran `git {_MUTATION}` "
        f"({run.argv_for(_MUTATION)}) — staging was advanced anyway"
    )


# --- The happy path -----------------------------------------------------------


def test_the_real_script_promotes_a_green_candidate(tmp_path: Path) -> None:
    """AC: on a green gate the tracked script fast-forwards ``staging`` and stops.

    The copy is asserted byte-identical to the tracked file, so every other test
    in this module — which run rewritten or re-environed copies through the same
    function — is measuring the real script's behaviour and not a paraphrase.
    """
    run = _run_promotion_step(_script(), tmp_path)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert run.copy.read_bytes() == SCRIPT.read_bytes(), (
        "the executed copy is not the tracked script, so this proves nothing about it"
    )
    pushes = run.argv_for(_MUTATION)
    assert len(pushes) == 1, f"expected exactly one `git push`; recorded {pushes}"
    argv = pushes[0]
    assert "origin" in argv, argv
    refspec = [token for token in argv if ":" in token]
    assert refspec == [f"{_CANDIDATE}:refs/heads/staging"], (
        f"the push must advance staging to the gated candidate; got {argv}"
    )
    assert "--force" not in argv and "-f" not in argv, (
        f"the promotion must never force-update staging; got {argv}"
    )


def test_the_gate_runs_inside_the_checkout(tmp_path: Path) -> None:
    """The gate is invoked in ``GITHUB_WORKSPACE``, and its output is captured.

    Two independent witnesses that it ran there at all: the sentinel the fake
    gate writes into its *current directory*, and the token it echoes into the
    captured log. Removing the script's ``cd "$GITHUB_WORKSPACE"`` leaves both
    absent, because the subprocess's own cwd is deliberately not a checkout.
    """
    run = _run_promotion_step(_script(), tmp_path)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert (run.workspace / _GATE_SENTINEL).is_file(), (
        "the gate did not run inside the checkout the workflow handed the script"
    )
    assert _GATE_TOKEN in run.gate_log, f"the gate log holds no gate output: {run.gate_log!r}"


# --- The refusal directions ---------------------------------------------------


@pytest.mark.parametrize("gate_exit", [1, 2, 97])
def test_a_red_gate_never_advances_staging(gate_exit: int, tmp_path: Path) -> None:
    """Behaviour identity: the step never repairs and never rounds a red gate.

    Three exit codes, because the retired verb classified them differently (97
    was the toolchain-unrunnable code) and plain git must not acquire a code it
    treats as success.
    """
    run = _run_promotion_step(_script(), tmp_path, gate_exit=gate_exit)

    assert run.returncode != 0, "a red gate left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert str(gate_exit) in run.stdout, (
        f"the annotation must report the gate's own exit code {gate_exit}: {run.stdout!r}"
    )
    _assert_nothing_was_pushed(run, f"the gate exited {gate_exit}")


def test_a_non_fast_forward_target_is_refused(tmp_path: Path) -> None:
    """``staging`` holding commits ``dev`` lacks stops the job — no merge, no force.

    The case with no textual signature: refusing and succeeding run the same
    lines, so only executing with ``merge-base --is-ancestor`` refusing can
    distinguish them.
    """
    run = _run_promotion_step(_script(), tmp_path, git_exits={"merge-base": 1})

    assert run.returncode != 0, "a non-fast-forward target left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "fast-forward" in run.stdout, run.stdout
    _assert_nothing_was_pushed(run, "staging is not an ancestor of the candidate")
    assert "merge" not in {inv.call for inv in run.invocations} or run.argv_for("merge") == [], (
        f"the script attempted a merge instead of stopping: {run.argv_for('merge')}"
    )


def test_a_target_that_does_not_exist_yet_is_created(tmp_path: Path) -> None:
    """A missing remote ``staging`` is created by the push, not treated as an error.

    The discriminator for the ancestry check's guard clause: with no remote ref
    there is nothing to be an ancestor of, so skipping the check is correct and
    the push must still happen. Without this, deleting the ``ls-remote`` guard
    would be invisible.
    """
    run = _run_promotion_step(_script(), tmp_path, git_exits={"ls-remote": 2})

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert run.argv_for(_MUTATION), "the first promotion must create the target branch"


def test_a_failing_push_fails_the_step(tmp_path: Path) -> None:
    """``set -e`` holds: the server's own non-fast-forward refusal is not swallowed.

    The second, independent guard on the same property — if the ancestry check is
    ever deleted, the unforced push still refuses server-side, and the step must
    report that rather than exiting 0.
    """
    run = _run_promotion_step(_script(), tmp_path, git_exits={"push": 1})

    assert run.returncode != 0, "a rejected push left the step reporting success"


@pytest.mark.parametrize("variable", _REQUIRED_ENV)
def test_a_missing_required_input_aborts_before_any_mutation(
    variable: str, tmp_path: Path
) -> None:
    """Fail-closed: each required input is asserted before anything mutates.

    Removed one at a time rather than together, so each variable is shown to be
    load-bearing on its own — dropping both would let one assertion cover for a
    missing other.
    """
    run = _run_promotion_step(_script(), tmp_path, drop_env=variable)

    assert run.returncode != 0, (
        f"the script ran to completion with {variable} unset; the required "
        "inputs must be asserted before any mutation"
    )
    assert variable in run.stderr, (
        f"the abort must name the missing input {variable}: {run.stderr!r}"
    )
    _assert_nothing_was_pushed(run, f"{variable} was unset")
    assert not (run.workspace / _GATE_SENTINEL).exists(), (
        f"the gate ran despite {variable} being unset — the assertion is not "
        "before the work"
    )


# --- Floors -------------------------------------------------------------------


def test_the_stub_is_the_only_git_the_script_can_reach(tmp_path: Path) -> None:
    """Every git call the script makes was recorded, and the set is non-trivial.

    The floor under every assertion above: they all read the recorded
    invocations, so a stub that was bypassed — or a script that shelled out to
    something else — would make each of them pass over an empty list.
    """
    run = _run_promotion_step(_script(), tmp_path)

    assert run.calls >= {"rev-parse", "push"}, (
        f"the script recorded {sorted(run.calls)}, which does not cover the "
        "calls the promotion must make — the git stub was bypassed"
    )
    assert all(inv.cwd == str(run.workspace) for inv in run.invocations), (
        f"a git call ran outside the checkout: "
        f"{[(inv.cwd, inv.call) for inv in run.invocations if inv.cwd != str(run.workspace)]}"
    )


def test_the_script_is_shell_that_actually_parses() -> None:
    """``bash -n`` on the tracked file.

    Cheap, and it names the script when the failure is a syntax error rather
    than leaving every test above reporting a non-zero exit with no reason.
    """
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{SCRIPT.name} failed `bash -n`:\n{result.stderr}"
