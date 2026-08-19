"""The nightly promotion step, **executed** rather than read (#396, #435, #485).

Admission (ADR 0017 D5): class (a) — executable behaviour of
``scripts/promotion-step.sh``, the shell the nightly ``dev → main`` job runs.

Until #396 the script's properties were asserted by deriving call sites out of
the workflow's YAML with a regex. That instrument cost four tickets (#390, #391,
#393, #394), each teaching it one more way shell writes the same call, and it
went red on the refactor that would have removed the defect class outright. The
rule it broke is now recorded: ``specs/architecture-principles.md`` → *CI logic
lives in a script, not in a `run:` block*.

So this module runs the script. **#435 changed what it drives, not whether it is
driven**; **#485 changed it again, and further.** ``main`` is protected and
requires a pull request, so ``github-actions[bot]`` cannot update
``refs/heads/main`` at all (GH006) and the job had never once succeeded. The
nightly now **opens or reuses a ``dev → main`` pull request and merges it
through the API**, with the merge bound server-side to the gated SHA. Two
consequences for this module:

* ``gh`` joins ``git`` as a stubbed binary, appending to **the same** record
  file. The shared record is what makes ordering assertions possible — that the
  merge came after the poll and the poll came after the gate — which per-binary
  records cannot express. The fake gate appends to it too, so "the gate ran" is
  an index rather than only a file.
* **Fast-forward-only publishing is retired** (ADR 0003 as amended 2026-08-19).
  A PR merge puts a commit on ``main`` that ``dev`` does not contain, so the old
  ``merge-base --is-ancestor origin/main <candidate>`` precheck would refuse
  every night after the first. What replaces it is a *pair*: a **pre-condition**
  that ``main`` contributes no content relative to the merge base — the exact
  condition under which the merge is content-trivial — and **post-conditions**
  on the merge SHA the API returned, that the candidate is contained in it and
  that ``tree(merge) == tree(candidate)``.

What executing buys, and what a text guard could not have shown:

* **The gate decides.** The fake ``scripts/verify.sh`` this module writes into
  the workspace is the only gate the script can reach, and its exit code is
  chosen per test. A red gate must leave the merge unrecorded — asserted on the
  recorded argv, not on the script's text, so a rewrite that hoists the merge
  above the gate check fails here rather than passing a grep.
* **The empty check-run set is never success.** A renamed CI job or a typo'd
  ``REQUIRED_CHECK`` yields no runs, and "no failed run found" must not read as
  a green one (``review-discipline/references/craft.md`` → *``all()`` over a
  possibly-empty iterable is constant-true*).
* **Fail-closed inputs.** Each required environment variable is removed in turn
  and the script must abort *before* the gate and *before* any ``gh`` call.

Nothing here can touch the real repository, the real gate, or the real GitHub.
Every ``git`` and ``gh`` invocation goes to a stub on ``PATH``, the subprocess
runs with ``cwd`` under ``tmp_path``, and the only ``scripts/verify.sh`` the
script can reach is the fake one this module writes into the workspace it is
handed. The fixture's repository slug is deliberately **not** this repo's, so a
test that passed because the real slug leaked in could not hide.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"
NIGHTLY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-promotion.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The environment inputs Actions supplies and the script requires. ``GH_TOKEN``
#: and ``GITHUB_REPOSITORY`` arrived with the PR mechanism (#485).
_REQUIRED_ENV = ("GITHUB_WORKSPACE", "RUNNER_TEMP", "GITHUB_REPOSITORY", "GH_TOKEN")

#: Deliberately not ``sluengen/harness``: every assertion about a call site's
#: repository is derived from this value, so a script that hardcoded the real
#: slug — or a test that did — fails instead of passing for the wrong reason.
_REPO = "stub-owner/stub-repo"

#: The candidate SHA the stubbed ``git rev-parse`` reports. Filename-safe: it
#: lands in ``$RUNNER_TEMP/promotion-gate-<sha>.log``.
_CANDIDATE = "0123456789abcdef0123456789abcdef01234567"

#: What the merge API returns. Distinct from the candidate, so an assertion that
#: confuses the two cannot pass.
_MERGE_SHA = "fedcba9876543210fedcba9876543210fedcba98"

#: What the plain (non-``--is-ancestor``) ``git merge-base`` prints.
_MERGE_BASE = "89abcdef0123456789abcdef0123456789abcdef"

#: What ``gh pr create`` prints. The PR *number* every assertion uses is parsed
#: back out of this URL rather than written twice.
_PR_URL = f"https://github.com/{_REPO}/pull/17"

#: Written by the fake gate into its *current directory*, so its presence is
#: evidence the script ran the gate inside the workspace rather than wherever
#: the subprocess happened to start.
_GATE_SENTINEL = "gate-ran"

#: Echoed by the fake gate, so the captured gate log can be shown to be the fake
#: gate's output rather than an empty file.
_GATE_TOKEN = "fake-gate-output-marker"

#: The recorded call the fake gate appends. Ordering assertions read it.
_GATE_CALL = "gate"

#: The opening of the script's own fail-closed message. ``set -u`` aborts on an
#: unset variable too, so an assertion satisfied by either could not tell a
#: deliberate check from an accident of the shell.
_ENV_ABORT = "the promotion step needs"

#: A ``git`` recorder. One record per invocation, fields NUL-separated and
#: records newline-separated: ``[cwd, binary, *argv]``. Behaviour is driven by
#: files the fixture writes, so a test scripts a scenario without rewriting the
#: stub. Exits are keyed by **argument set**, never globally: the script asks
#: ``merge-base --is-ancestor`` two different questions, and one file driving
#: both would mean a single fixture edit killed two guards with neither
#: isolated.
_GIT_STUB = r"""#!/bin/sh
set -eu
{ printf '%s\0' "$PWD" git "$@"; printf '\n'; } >> "$STUB_RECORD"

_mapped() {
  # $1: map file (TAB-separated key/value). $2: key. Prints the value, or nothing.
  if [ -f "$STUB_STATE/$1" ]; then
    awk -F '\t' -v key="$2" '$1 == key { print $2; exit }' "$STUB_STATE/$1"
  fi
}

case "$1" in
  rev-parse)
    for arg in "$@"; do
      if [ "$arg" = "rev-parse" ]; then continue; fi
      value="$(_mapped rev-parse.map "$arg")"
      if [ -n "$value" ]; then echo "$value"; else echo "$STUB_CANDIDATE"; fi
    done
    ;;
  merge-base)
    code="$(_mapped merge-base.map "$*")"
    case " $* " in
      *" --is-ancestor "*) : ;;
      *) echo "$STUB_MERGE_BASE" ;;
    esac
    exit "${code:-0}"
    ;;
  ls-remote)
    branch=""
    for arg in "$@"; do branch="$arg"; done
    branch="${branch#refs/heads/}"
    if [ -f "$STUB_STATE/ls-remote.$branch.out" ]; then cat "$STUB_STATE/ls-remote.$branch.out"; fi
    code="$(_mapped ls-remote.map "$branch")"
    exit "${code:-0}"
    ;;
  diff)
    code="$(_mapped exit.map diff)"
    exit "${code:-0}"
    ;;
  push)
    code="$(_mapped exit.map push)"
    exit "${code:-0}"
    ;;
  *) : ;;
esac
exit 0
"""

#: A ``gh`` recorder, appending to the same record file. The check-runs read is
#: **sequenced** — each call takes the next scripted observation — so a test can
#: script "in_progress, in_progress, success" and assert the script actually
#: looped rather than reading once.
_GH_STUB = r"""#!/bin/sh
set -eu
{ printf '%s\0' "$PWD" gh "$@"; printf '\n'; } >> "$STUB_RECORD"

_emit() {
  if [ -f "$STUB_STATE/$1" ]; then cat "$STUB_STATE/$1"; fi
}

_code() {
  if [ -f "$STUB_STATE/$1" ]; then cat "$STUB_STATE/$1"; else echo 0; fi
}

case "$1" in
  pr)
    case "${2:-}" in
      list) _emit pr-list.out ;;
      create)
        code="$(_code pr-create.exit)"
        if [ "$code" -eq 0 ]; then _emit pr-create.out; else echo "gh: refused (stub)" >&2; fi
        exit "$code"
        ;;
      *) : ;;
    esac
    ;;
  api)
    case " $* " in
      *check-runs*)
        n=0
        if [ -f "$STUB_STATE/check-runs.n" ]; then n="$(cat "$STUB_STATE/check-runs.n")"; fi
        n=$((n + 1))
        echo "$n" > "$STUB_STATE/check-runs.n"
        if [ -f "$STUB_STATE/check-runs.$n.out" ]; then
          cat "$STUB_STATE/check-runs.$n.out"
        else
          _emit check-runs.last.out
        fi
        ;;
      *"/merge"*)
        code="$(_code merge.exit)"
        if [ "$code" -eq 0 ]; then _emit merge.out; else echo "gh: merge refused (stub)" >&2; fi
        exit "$code"
        ;;
      *) : ;;
    esac
    ;;
  *) : ;;
esac
exit 0
"""


@dataclass(frozen=True)
class Scenario:
    """One night the script could meet, as data the stubs read.

    Every default is the promotable night: ``main`` exists, does not contain the
    candidate, carries no content of its own, ``dev`` still points at the
    candidate, no PR is open yet, and the required check is already green.
    """

    gate_exit: int = 0
    main_exists: bool = True
    #: ``git diff --quiet <base> origin/main`` — 0 means main contributes nothing.
    diff_exit: int = 0
    #: Keyed by the *whole* ``merge-base`` argument set, so the two ancestry
    #: questions the script asks are independently scriptable.
    ancestor_exits: Mapping[str, int] = field(default_factory=dict)
    #: ``git rev-parse <arg>`` overrides, keyed by argument.
    rev_parse: Mapping[str, str] = field(default_factory=dict)
    #: What ``git ls-remote --heads origin dev`` reports.
    dev_head: str = _CANDIDATE
    #: What ``gh pr list`` prints — one ``<number> <isDraft> <headRefOid>`` line.
    pr_list: str = ""
    pr_create_out: str = _PR_URL
    pr_create_exit: int = 0
    #: The scripted check-run observations, one per poll, the last one repeating.
    check_runs: Sequence[str] = ("completed success",)
    merge_exit: int = 0
    merge_sha: str = _MERGE_SHA
    #: Poll tunables, overridden so a timeout costs seconds rather than minutes.
    check_wait_seconds: int = 2
    check_poll_seconds: int = 1


@dataclass(frozen=True)
class Invocation:
    """One recorded call — ``git``, ``gh``, or the gate."""

    cwd: str
    binary: str
    argv: tuple[str, ...]

    @property
    def call(self) -> str:
        """``git push``, ``gh pr create``, ``gh api``, ``gate`` — the site a failure names."""
        if not self.argv:
            return self.binary
        if self.binary == "gh" and self.argv[0] == "pr" and len(self.argv) > 1:
            return f"gh pr {self.argv[1]}"
        return f"{self.binary} {self.argv[0]}"


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

    def index_of(self, call: str) -> int:
        """The first index at which ``call`` was recorded; -1 when it never was."""
        for index, inv in enumerate(self.invocations):
            if inv.call == call:
                return index
        return -1

    @property
    def merges(self) -> list[tuple[int, tuple[str, ...]]]:
        """Indexed merge-API calls: a ``--method`` request at a ``.../merge`` path."""
        return [
            (index, inv.argv)
            for index, inv in enumerate(self.invocations)
            if inv.call == "gh api"
            and "--method" in inv.argv
            and any(token.endswith("/merge") for token in inv.argv)
        ]

    @property
    def check_reads(self) -> list[int]:
        """Indexed check-run reads."""
        return [
            index
            for index, inv in enumerate(self.invocations)
            if inv.call == "gh api" and any("check-runs" in token for token in inv.argv)
        ]


def _write_map(path: Path, entries: Mapping[str, object]) -> None:
    rows = "".join(f"{key}\t{value}\n" for key, value in entries.items())
    path.write_text(rows, encoding="utf-8")


def _write_stubs(bin_dir: Path, state: Path, scenario: Scenario) -> None:
    """Install the two recorders and the files that drive them."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    for name, text in (("git", _GIT_STUB), ("gh", _GH_STUB)):
        stub = bin_dir / name
        stub.write_text(text, encoding="utf-8")
        stub.chmod(0o755)

    _write_map(
        state / "merge-base.map",
        {
            # The promotable default: main does *not* already contain the candidate.
            f"merge-base --is-ancestor {_CANDIDATE} refs/remotes/origin/main": 1,
            **scenario.ancestor_exits,
        },
    )
    _write_map(state / "rev-parse.map", scenario.rev_parse)
    _write_map(state / "exit.map", {"diff": scenario.diff_exit})
    _write_map(state / "ls-remote.map", {} if scenario.main_exists else {"main": 2})
    (state / "ls-remote.dev.out").write_text(
        f"{scenario.dev_head}\trefs/heads/dev\n", encoding="utf-8"
    )
    (state / "pr-list.out").write_text(scenario.pr_list, encoding="utf-8")
    (state / "pr-create.out").write_text(f"{scenario.pr_create_out}\n", encoding="utf-8")
    (state / "pr-create.exit").write_text(str(scenario.pr_create_exit), encoding="utf-8")
    for number, observation in enumerate(scenario.check_runs, start=1):
        (state / f"check-runs.{number}.out").write_text(observation, encoding="utf-8")
    (state / "check-runs.last.out").write_text(
        scenario.check_runs[-1] if scenario.check_runs else "", encoding="utf-8"
    )
    (state / "merge.out").write_text(f"{scenario.merge_sha}\n", encoding="utf-8")
    (state / "merge.exit").write_text(str(scenario.merge_exit), encoding="utf-8")


def _write_gate(workspace: Path, gate_exit: int) -> None:
    """The only ``scripts/verify.sh`` the script can reach.

    It writes a sentinel into its *current directory* and appends to the shared
    record, so "the gate ran" is answerable both as a place and as an index.
    """
    (workspace / "scripts").mkdir(parents=True, exist_ok=True)
    (workspace / "scripts" / "verify.sh").write_text(
        "#!/bin/sh\n"
        f': > "{_GATE_SENTINEL}"\n'
        "{ printf '%s\\0' \"$PWD\" " + _GATE_CALL + "; printf '\\n'; } >> \"$STUB_RECORD\"\n"
        f'echo "{_GATE_TOKEN}"\n'
        f"exit {gate_exit}\n",
        encoding="utf-8",
    )


def _run_promotion_step(
    tmp_path: Path,
    scenario: Scenario | None = None,
    *,
    script_text: str | None = None,
    drop_env: str | None = None,
) -> StepRun:
    """Execute the script as the runner would, against stubbed ``git`` and ``gh``.

    Every test in this module goes through here, the baseline included: the real
    script is *copied* rather than executed in place, so one code path serves the
    real input and every variation, and
    :func:`test_the_real_script_promotes_by_merging_a_pull_request` asserts the
    copy is byte-identical to the tracked file.
    """
    scenario = scenario or Scenario()
    workspace = tmp_path / "workspace"
    record = tmp_path / "invocations"
    record.write_bytes(b"")
    _write_gate(workspace, scenario.gate_exit)

    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    _write_stubs(bin_dir, state, scenario)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    copy = tmp_path / "promotion-step.sh"
    copy.write_text(_script() if script_text is None else script_text, encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_WORKSPACE": str(workspace),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_REPOSITORY": _REPO,
        "GH_TOKEN": "stub-token-never-echoed",
        "STUB_RECORD": str(record),
        "STUB_STATE": str(state),
        "STUB_CANDIDATE": _CANDIDATE,
        "STUB_MERGE_BASE": _MERGE_BASE,
        "PROMOTION_CHECK_WAIT_SECONDS": str(scenario.check_wait_seconds),
        "PROMOTION_CHECK_POLL_SECONDS": str(scenario.check_poll_seconds),
    }
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
        invocations.append(Invocation(cwd=fields[0], binary=fields[1], argv=tuple(fields[2:])))
    return tuple(invocations)


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _nightly_workflow() -> str:
    return NIGHTLY_WORKFLOW.read_text(encoding="utf-8")


def _script_constant(pattern: str) -> str:
    """The one value ``pattern`` captures in the tracked script.

    Exactly one match: a constant that appears twice, or not at all, is a
    question the caller must answer rather than a value to read past.
    """
    matches = re.findall(pattern, _script(), re.MULTILINE)
    assert len(matches) == 1, (
        f"expected exactly one {pattern!r} in {SCRIPT.name}; found {matches}"
    )
    return str(matches[0])


def _ci_job_keys() -> set[str]:
    """The check-run names ``ci.yml`` produces, derived from its ``jobs:`` mapping.

    A check run is named after the job's ``name:`` when it declares one, and
    after its **key** otherwise — so a key is only the right answer while no
    ``name:`` shadows it. Deriving keys alone would let someone add
    ``name: Build & test`` to the ``lint-and-test`` job and leave this
    correspondence green while the poll waited forever for a check that no
    longer exists under that name (#485). The effective name is derived here
    instead, so the guard measures what GitHub will actually publish.
    """
    names: set[str] = set()
    current: str | None = None
    in_jobs = False
    for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line.strip() and not line.startswith(" "):
            break
        match = re.match(r"^ {2}([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            names.add(current)
            continue
        # A job-level `name:` (exactly four spaces) replaces the key it shadows.
        shadow = re.match(r"^ {4}name:\s*(\S.*?)\s*$", line)
        if shadow and current is not None:
            names.discard(current)
            names.add(shadow.group(1).strip("'\""))
            current = None
    return names


def _pr_number() -> str:
    """The PR number, parsed back out of what the stub printed."""
    return _PR_URL.rsplit("/", 1)[1]


# --- The happy path -----------------------------------------------------------


def test_the_real_script_promotes_by_merging_a_pull_request(tmp_path: Path) -> None:
    """AC: on a green gate and a green required check, the tracked script merges.

    The copy is asserted byte-identical to the tracked file, so every other test
    in this module — which run rewritten or re-environed copies through the same
    function — is measuring the real script's behaviour and not a paraphrase.

    Every argv assertion is on an **exact token**, never a substring of the
    joined command line: the candidate SHA also appears in the gate-log path and
    the PR body path, and the word ``merge`` appears in the API path itself, so
    ``sha=<candidate> in " ".join(argv)`` and ``"merge" in argv`` would both pass
    for the wrong reason.
    """
    run = _run_promotion_step(tmp_path)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert run.copy.read_bytes() == SCRIPT.read_bytes(), (
        "the executed copy is not the tracked script, so this proves nothing about it"
    )
    assert len(run.merges) == 1, f"expected exactly one merge API call; recorded {run.merges}"
    argv = run.merges[0][1]
    assert f"repos/{_REPO}/pulls/{_pr_number()}/merge" in argv, (
        f"the merge must PUT the PR the stub opened, under the repository the "
        f"environment names; got {argv}"
    )
    assert f"sha={_CANDIDATE}" in argv, (
        f"the merge must bind server-side to the gated candidate; got {argv}"
    )
    assert "merge_method=merge" in argv, (
        f"only a merge commit keeps tree(merge) == tree(candidate); got {argv}"
    )


def test_the_promotion_never_pushes_a_ref(tmp_path: Path) -> None:
    """The old path is gone, stated as an absence over the recorded calls.

    ``main`` is protected: a direct ``refs/heads/main`` update by
    ``github-actions[bot]`` is refused with GH006, which is why the job had never
    once succeeded. A reinstated push line must fail here.
    """
    run = _run_promotion_step(tmp_path)

    assert "git push" not in run.calls, (
        f"the script still pushes a ref ({run.argv_for('git push')}); main is "
        "protected and the promotion goes through a pull request"
    )


def test_the_pull_request_is_opened_from_dev_with_a_body_file(tmp_path: Path) -> None:
    """One PR, ``dev`` into ``main``, its body passed as a file.

    Head-is-``dev`` is the whole mechanism: the head commit already carries the
    green required check raised by the ordinary ``push: dev`` trigger, so no new
    run and no approval is needed. The body is a **file** because it quotes
    commit subjects — untrusted text that must never be interpolated into a
    shell word.
    """
    run = _run_promotion_step(tmp_path)

    creates = run.argv_for("gh pr create")
    assert len(creates) == 1, f"expected exactly one `gh pr create`; recorded {creates}"
    argv = creates[0]
    assert "--base" in argv and argv[argv.index("--base") + 1] == "main", argv
    assert "--head" in argv and argv[argv.index("--head") + 1] == "dev", argv
    assert "--body-file" in argv, f"the PR body must be passed as a file; got {argv}"
    assert "--body" not in argv, f"the PR body must never be a shell word; got {argv}"


def test_every_api_call_names_the_repository_the_environment_gave_it(tmp_path: Path) -> None:
    """``GITHUB_REPOSITORY`` is single-sourced into every ``gh`` call site.

    The slug is the fixture's, not this repo's, so a call site that hardcoded
    ``sluengen/harness`` fails here rather than passing because the real name
    happened to be right.
    """
    run = _run_promotion_step(tmp_path)

    gh_calls = [inv for inv in run.invocations if inv.binary == "gh"]
    assert gh_calls, "no `gh` call was recorded at all — the stub was bypassed"
    for inv in gh_calls:
        assert any(_REPO in token for token in inv.argv), (
            f"`gh {' '.join(inv.argv)}` names no repository, or names one the "
            f"environment did not supply ({_REPO})"
        )


def test_the_merge_comes_after_the_check_which_comes_after_the_gate(tmp_path: Path) -> None:
    """Ordering, read off the shared record.

    A merge hoisted above the poll, or a poll hoisted above the gate, has no
    textual signature — both orders run the same lines. Only execution against
    one record separates them.
    """
    run = _run_promotion_step(tmp_path)

    gate = run.index_of(_GATE_CALL)
    assert gate >= 0, "the gate never ran"
    assert run.check_reads, "the required check was never read"
    assert run.merges, "nothing was merged"
    assert gate < min(run.check_reads), (
        "the required check was read before the gate ran — the poll must observe "
        "the check on a candidate this job has already gated"
    )
    assert max(run.check_reads) < run.merges[0][0], (
        "the merge was issued before the last check observation — it must merge "
        "only after observing a completed, successful required check"
    )


def test_the_gate_runs_inside_the_checkout(tmp_path: Path) -> None:
    """The gate is invoked in ``GITHUB_WORKSPACE``, and its output is captured.

    Two independent witnesses that it ran there at all: the sentinel the fake
    gate writes into its *current directory*, and the token it echoes into the
    captured log. Removing the script's ``cd "$GITHUB_WORKSPACE"`` leaves both
    absent, because the subprocess's own cwd is deliberately not a checkout.
    """
    run = _run_promotion_step(tmp_path)

    assert run.returncode == 0, f"the script failed: {run.stderr}\n{run.stdout}"
    assert (run.workspace / _GATE_SENTINEL).is_file(), (
        "the gate did not run inside the checkout the workflow handed the script"
    )
    assert _GATE_TOKEN in run.gate_log, f"the gate log holds no gate output: {run.gate_log!r}"


# --- The refusal directions ---------------------------------------------------
#
# Every case below asserts **two** things: that nothing mutated, and a positive
# witness that the script reached the branch under test. With this many refusal
# paths, a script that died on its first line would satisfy every "nothing
# mutated" assertion in the module and none of them would notice.


def _assert_nothing_was_merged(run: StepRun, why: str) -> None:
    """The refusal direction, in one place so every caller measures the same thing.

    Asserted on the *recorded invocations*, never on the script's text: a merge
    reordered above the check that forbids it is the regression this bounds, and
    it has no distinguishing text. ``git push`` is included because the mutation
    this script used to make is still one command away.
    """
    assert not run.merges, (
        f"{why}, but the script still merged the pull request ({run.merges}) — "
        "main was advanced anyway"
    )
    assert "git push" not in run.calls, (
        f"{why}, but the script still ran `git push` ({run.argv_for('git push')})"
    )


def _assert_no_pull_request_was_opened(run: StepRun, why: str) -> None:
    """A refusal that has already opened a PR has spent a mutation of its own."""
    assert "gh pr create" not in run.calls, (
        f"{why}, but the script opened a pull request anyway "
        f"({run.argv_for('gh pr create')})"
    )


@pytest.mark.parametrize("gate_exit", [1, 2, 97])
def test_a_red_gate_never_promotes(gate_exit: int, tmp_path: Path) -> None:
    """R1. Behaviour identity: the step never repairs and never rounds a red gate.

    Three exit codes, because the retired verb classified them differently (97
    was the toolchain-unrunnable code) and the promotion must not acquire a code
    it treats as success. Carried from the pre-#485 script; what is new is that
    the bounded mutation is now the *merge*, and that no PR is opened either.
    """
    run = _run_promotion_step(tmp_path, Scenario(gate_exit=gate_exit))

    assert run.returncode != 0, "a red gate left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert str(gate_exit) in run.stdout, (
        f"the annotation must report the gate's own exit code {gate_exit}: {run.stdout!r}"
    )
    assert (run.workspace / _GATE_SENTINEL).is_file(), (
        "the gate never ran, so this run refused for some earlier reason and "
        "proves nothing about a red gate"
    )
    _assert_no_pull_request_was_opened(run, f"the gate exited {gate_exit}")
    _assert_nothing_was_merged(run, f"the gate exited {gate_exit}")


def test_a_source_branch_that_moved_under_the_gate_is_refused(tmp_path: Path) -> None:
    """R2. ``dev`` moving after the gate means the PR head is no longer gated.

    The gate certified one SHA; the pull request's head is the *branch*, so a
    push landing between the checkout and the merge would carry ungated commits
    into ``main``. This is the early, named refusal — the residual window after
    it is closed server-side by the merge's ``sha=`` head match. Nothing is
    repaired: tonight simply does not promote.
    """
    moved = "1111111111111111111111111111111111111111"
    run = _run_promotion_step(tmp_path, Scenario(dev_head=moved))

    assert run.returncode != 0, "a moved source branch left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert moved in run.stdout, (
        f"the annotation must name the head it actually observed: {run.stdout!r}"
    )
    assert (run.workspace / _GATE_SENTINEL).is_file(), (
        "the gate never ran, so this run refused before the window this test is about"
    )
    _assert_no_pull_request_was_opened(run, "dev moved past the gated candidate")
    _assert_nothing_was_merged(run, "dev moved past the gated candidate")


def test_a_candidate_main_already_contains_is_a_clean_night(tmp_path: Path) -> None:
    """R3. Nothing to promote exits 0 — and does not spend the gate.

    GitHub answers a PR with no commits between the refs with a 422; this is the
    same predicate, evaluated locally first, so an empty night is a clean night
    rather than a red job. The **absent** gate sentinel is the positive witness:
    it is the only thing that distinguishes this early exit from a script that
    gated first and then found nothing to do.
    """
    already_contained = {
        f"merge-base --is-ancestor {_CANDIDATE} refs/remotes/origin/main": 0,
    }
    run = _run_promotion_step(tmp_path, Scenario(ancestor_exits=already_contained))

    assert run.returncode == 0, f"an empty night must be clean: {run.stderr}\n{run.stdout}"
    assert not (run.workspace / _GATE_SENTINEL).exists(), (
        "the gate ran on a night with nothing to promote — the no-op check must "
        "come first, or every empty night burns a full gate"
    )
    _assert_no_pull_request_was_opened(run, "main already contains the candidate")
    _assert_nothing_was_merged(run, "main already contains the candidate")


def test_a_target_carrying_its_own_content_is_refused(tmp_path: Path) -> None:
    """R4. The pre-condition: relative to the merge base, ``main`` contributes nothing.

    That is exactly the condition under which the PR merge is content-trivial —
    ``tree(merge) == tree(candidate)``. It replaces the retired fast-forward
    precheck (ADR 0003 as amended 2026-08-19), and unlike an allowlist it earns
    itself from its subject: it reopens the moment a hotfix landed on ``main``
    reaches ``dev``, and has no exemption to go stale.
    """
    run = _run_promotion_step(tmp_path, Scenario(diff_exit=1))

    assert run.returncode != 0, "a divergent target left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "content" in run.stdout, (
        f"the annotation must name what diverged — content, not ancestry: {run.stdout!r}"
    )
    assert not (run.workspace / _GATE_SENTINEL).exists(), (
        "the gate ran despite a doomed night; the pre-condition comes first"
    )
    _assert_no_pull_request_was_opened(run, "main carries content dev does not")
    _assert_nothing_was_merged(run, "main carries content dev does not")


def test_a_target_that_does_not_exist_yet_is_refused(tmp_path: Path) -> None:
    """R9. A missing remote ``main`` now stops the job.

    A behaviour change, stated: the pre-#485 script skipped its ancestry check
    when the target did not exist and let the push create it. A pull request
    cannot create its base branch, so a missing target is a loud refusal rather
    than a silent first promotion.
    """
    run = _run_promotion_step(tmp_path, Scenario(main_exists=False))

    assert run.returncode != 0, "a missing target left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "main" in run.stdout, run.stdout
    assert not (run.workspace / _GATE_SENTINEL).exists(), (
        "the gate ran despite there being no branch to promote onto"
    )
    _assert_no_pull_request_was_opened(run, "the target branch does not exist")
    _assert_nothing_was_merged(run, "the target branch does not exist")


@pytest.mark.parametrize("variable", _REQUIRED_ENV)
def test_a_missing_required_input_aborts_before_any_mutation(variable: str, tmp_path: Path) -> None:
    """R8. Fail-closed: each required input is asserted before anything happens.

    Removed one at a time rather than together, so each variable is shown to be
    load-bearing on its own — dropping both would let one assertion cover for a
    missing other. The abort must carry the script's **own** message: ``set -u``
    would also abort on an unset variable, so an assertion satisfied by either
    could not tell a deliberate fail-closed check from an accident of the shell.

    ``GH_TOKEN`` is asserted like the rest and, unlike the rest, never echoed:
    ``${GH_TOKEN:?...}`` prints the message, not the value.
    """
    run = _run_promotion_step(tmp_path, drop_env=variable)

    assert run.returncode != 0, (
        f"the script ran to completion with {variable} unset; the required "
        "inputs must be asserted before any mutation"
    )
    assert variable in run.stderr, f"the abort must name the missing input: {run.stderr!r}"
    assert _ENV_ABORT in run.stderr, (
        f"the abort must be the script's own assertion, not `set -u` catching it "
        f"later: {run.stderr!r}"
    )
    assert "stub-token-never-echoed" not in (run.stderr + run.stdout), (
        "the token was echoed; it must never reach a log"
    )
    assert not (run.workspace / _GATE_SENTINEL).exists(), (
        f"the gate ran despite {variable} being unset — the assertion is not "
        "before the work"
    )
    assert not [inv for inv in run.invocations if inv.binary == "gh"], (
        f"the script reached GitHub with {variable} unset: "
        f"{[inv.argv for inv in run.invocations if inv.binary == 'gh']}"
    )
    _assert_nothing_was_merged(run, f"{variable} was unset")


def test_a_failed_required_check_is_refused_immediately(tmp_path: Path) -> None:
    """R5. A completed, non-successful required check stops the night.

    Named, so the log says which conclusion was observed rather than "the check
    was not green". The pull request is deliberately **left open** — the next
    run reuses it — so a refusal here must not close anything either.
    """
    run = _run_promotion_step(tmp_path, Scenario(check_runs=("completed failure",)))

    assert run.returncode != 0, "a failed required check left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "failure" in run.stdout, (
        f"the annotation must name the conclusion it observed: {run.stdout!r}"
    )
    assert run.check_reads, "the required check was never read"
    assert "gh pr close" not in run.calls, (
        "the script closed the pull request; it is left open for the next run to reuse"
    )
    _assert_nothing_was_merged(run, "the required check concluded failure")


def test_a_check_that_never_concludes_times_out_after_polling(tmp_path: Path) -> None:
    """R6. The script waits, and waiting means *repeated* observation.

    The exit code alone cannot tell a poll from a single read — both refuse. The
    count is the discriminator: more than one check-runs query proves the script
    loops rather than reading once and giving up, which is the difference
    between tolerating a check still in flight and stranding every candidate
    whose CI has not finished.
    """
    run = _run_promotion_step(
        tmp_path,
        Scenario(check_runs=("in_progress null",), check_wait_seconds=2, check_poll_seconds=1),
    )

    assert run.returncode != 0, "an unfinished required check left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "in_progress" in run.stdout, (
        f"the annotation must name the last state it observed: {run.stdout!r}"
    )
    assert len(run.check_reads) > 1, (
        f"the script read the required check {len(run.check_reads)} time(s); it must "
        "poll until the deadline rather than give up on the first unfinished read"
    )
    _assert_nothing_was_merged(run, "the required check never concluded")


def test_an_empty_check_set_is_never_success(tmp_path: Path) -> None:
    """R7. The anti-vacuity case: no runs of the required name is not a green one.

    ``craft.md`` → *``all()`` over a possibly-empty iterable is constant-true*. A
    poll written as "no failed run found → proceed" is born vacuous: a renamed
    CI job, or a typo in ``REQUIRED_CHECK``, yields an empty set forever and
    would merge every night without a single check having run. It must produce a
    red night instead.
    """
    run = _run_promotion_step(tmp_path, Scenario(check_runs=()))

    assert run.returncode != 0, (
        "an empty check-run set left the step reporting success — an absent "
        "required check must never read as a passed one"
    )
    assert "::error::" in run.stdout, run.stdout
    assert run.check_reads, "the required check was never read"
    _assert_nothing_was_merged(run, "no run of the required check exists on the candidate")


def test_a_refused_merge_fails_the_step(tmp_path: Path) -> None:
    """R10. ``set -e`` holds: the API's own refusal is not swallowed.

    The server refuses with 409 when the pull request's head is no longer the
    SHA the merge names — the residual-window guard that no local check can
    make. Whatever the reason, a non-zero ``gh`` must fail the step rather than
    leave it reporting a promotion that did not happen.
    """
    run = _run_promotion_step(tmp_path, Scenario(merge_exit=1))

    assert run.returncode != 0, "a refused merge left the step reporting success"
    assert run.merges, "the merge was never attempted, so this proves nothing about its refusal"
    assert "Promoted" not in run.stdout, (
        f"the step reported a promotion the API refused: {run.stdout!r}"
    )


def test_a_refused_pull_request_creation_fails_the_step(tmp_path: Path) -> None:
    """R10's sibling: a ``gh pr create`` that fails is not stepped over.

    GitHub answers a pull request with no commits between the refs with a 422,
    and refuses a second one from the same head. The local checks above catch
    the cases this script can see; whatever else the API refuses must fail the
    step rather than leave it merging a pull request number it never got.
    """
    run = _run_promotion_step(tmp_path, Scenario(pr_create_exit=1))

    assert run.returncode != 0, "a refused pull request creation left the step reporting success"
    assert "gh pr create" in run.calls, "creation was never attempted"
    _assert_nothing_was_merged(run, "the pull request could not be created")


def test_a_merge_whose_tree_differs_from_the_candidate_is_an_alarm(tmp_path: Path) -> None:
    """R11. The post-condition that carries the invariant: tree identity.

    What lands on ``main`` must be exactly the tree the gate certified. Under a
    merge-commit merge whose base contributes nothing this holds by
    construction — and a squash, a rebase, or a conflict resolution breaks it.
    Stated honestly: this **detects** rather than prevents, because ``main`` has
    already moved when it runs. The prevention is the pre-condition plus the
    server-side head match.
    """
    run = _run_promotion_step(
        tmp_path,
        Scenario(rev_parse={f"{_MERGE_SHA}^{{tree}}": "9999999999999999999999999999999999999999"}),
    )

    assert run.returncode != 0, "a merge that rewrote the tree left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "tree" in run.stdout, (
        f"the annotation must name tree identity as what failed: {run.stdout!r}"
    )
    assert run.merges, "the merge never happened, so the post-condition proves nothing"


def test_a_merge_that_does_not_contain_the_candidate_is_an_alarm(tmp_path: Path) -> None:
    """R12. The second post-condition: the merge commit contains the candidate.

    Read on the SHA the API returned, never on whatever ``refs/heads/main``
    points at now, so a human pushing to ``main`` a second later cannot produce a
    false alarm. Its stub exit is keyed by the whole argument set, so making
    *this* ancestry question refuse leaves the pre-gate one — the "nothing to
    promote" check — answering as before.
    """
    run = _run_promotion_step(
        tmp_path,
        Scenario(ancestor_exits={f"merge-base --is-ancestor {_CANDIDATE} {_MERGE_SHA}": 1}),
    )

    assert run.returncode != 0, "a merge missing the candidate left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "contain" in run.stdout, (
        f"the annotation must name containment as what failed: {run.stdout!r}"
    )
    assert run.merges, "the merge never happened, so the post-condition proves nothing"


@pytest.mark.parametrize(
    ("pr_list", "why"),
    [
        ("23 false 2222222222222222222222222222222222222222\n", "its head is not the candidate"),
        (f"23 true {_CANDIDATE}\n", "it is a draft"),
    ],
    ids=["head-moved", "draft"],
)
def test_an_unusable_open_pull_request_is_refused(pr_list: str, why: str, tmp_path: Path) -> None:
    """R13. A reusable pull request must be exactly the one this run would open.

    Head ``dev`` into base ``main`` *is* the promotion by definition, so reusing
    a human's is benign — but only when its head is the gated candidate and it
    is not a draft. Anything else is refused rather than merged or amended.
    """
    run = _run_promotion_step(tmp_path, Scenario(pr_list=pr_list))

    assert run.returncode != 0, f"an open pull request was merged although {why}"
    assert "::error::" in run.stdout, run.stdout
    assert "gh pr list" in run.calls, "the open pull requests were never listed"
    _assert_nothing_was_merged(run, f"the open pull request is unusable — {why}")


def test_an_unparseable_pull_request_url_is_refused(tmp_path: Path) -> None:
    """R14. The PR number is validated before it is interpolated into a path.

    ``gh pr create`` prints a URL and the number is taken from its tail. That
    number goes straight into ``repos/<slug>/pulls/<n>/merge``: unvalidated, it
    is path injection. The refusal must happen *before* any request is built
    from it, which the "no path carries the garbage" assertion is what measures.
    """
    garbage = "not-a-number"
    run = _run_promotion_step(tmp_path, Scenario(pr_create_out=f"https://example.invalid/{garbage}"))

    assert run.returncode != 0, "an unparseable pull request URL left the step reporting success"
    assert "::error::" in run.stdout, run.stdout
    assert "gh pr create" in run.calls, "no pull request was created, so nothing was parsed"
    _assert_nothing_was_merged(run, "the pull request URL could not be parsed")
    carriers = [inv.argv for inv in run.invocations if any(garbage in t for t in inv.argv)]
    assert not carriers, f"a request was built out of the unparseable URL: {carriers}"


# --- Floors -------------------------------------------------------------------


def test_the_stubs_are_the_only_git_and_gh_the_script_can_reach(tmp_path: Path) -> None:
    """Every call the script makes was recorded, and the set is non-trivial.

    The floor under every assertion above: they all read the recorded
    invocations, so a stub that was bypassed — or a script that shelled out to
    something else — would make each of them, and every "nothing was merged"
    assertion below, pass over an empty list.
    """
    run = _run_promotion_step(tmp_path)

    required = {
        "git rev-parse",  # the candidate, and the two trees
        "git ls-remote",  # the target exists; dev still points at the candidate
        "git fetch",  # the target, and the merge commit the API returned
        "git merge-base",  # containment, before and after
        "git diff",  # the content-divergence pre-condition
        "gh pr list",  # reuse before create
        "gh pr create",
        "gh api",  # the check poll and the merge
    }
    assert required <= run.calls, (
        f"the script recorded {sorted(run.calls)}, which does not cover "
        f"{sorted(required - run.calls)} — a stub was bypassed, or the promotion "
        "no longer makes the calls its guards read"
    )
    assert all(inv.cwd == str(run.workspace) for inv in run.invocations), (
        f"a call ran outside the checkout: "
        f"{[(inv.cwd, inv.call) for inv in run.invocations if inv.cwd != str(run.workspace)]}"
    )


def test_the_required_check_names_a_job_that_exists() -> None:
    """F3. Structural correspondence: ``REQUIRED_CHECK`` is a job key in ``ci.yml``.

    The constant duplicates the CI job's name, and the poll refuses forever if it
    names a run that is never raised. Both sides are **derived** — the value out
    of the script, the keys out of the workflow — so neither is a literal here
    and a rename on either side fails rather than drifting.

    The half this cannot reach is off-tree: whether ``main``'s branch protection
    *requires* that check is GitHub configuration, which no test in this tree can
    read. That gap is recorded rather than implied by a green suite.
    """
    keys = _ci_job_keys()
    required = _script_constant(r'REQUIRED_CHECK="([^"]+)"')
    assert keys, "no job keys were derived from ci.yml, so the check below compares nothing"
    assert required in keys, (
        f"scripts/promotion-step.sh waits for a check named {required!r}, which is "
        f"not one of ci.yml's jobs ({sorted(keys)}) — the poll would never see it "
        "complete"
    )


def test_the_check_wait_fits_inside_the_job_it_runs_in() -> None:
    """F4. The poll's deadline is strictly inside the workflow's own timeout.

    If the wait outlives the job, the refusal path is unreachable: Actions
    cancels the job, which produces no ``::error::`` annotation and no named
    reason — a silent failure this design has no other defence against. Both
    numbers are derived from their files; neither is pinned here.
    """
    wait = int(_script_constant(r'CHECK_WAIT_SECONDS="\$\{[A-Z_]+:-([0-9]+)\}"'))
    minutes = re.findall(r"^\s*timeout-minutes:\s*([0-9]+)\s*$", _nightly_workflow(), re.MULTILINE)
    assert len(minutes) == 1, (
        f"expected exactly one `timeout-minutes:` in the nightly workflow; found {minutes}"
    )
    assert wait < int(minutes[0]) * 60, (
        f"the check poll waits up to {wait}s inside a job Actions cancels after "
        f"{minutes[0]} minutes; the timeout refusal would never be reached"
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
