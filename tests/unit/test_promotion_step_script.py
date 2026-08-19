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

**#491 changed what the stub emits.** ``gh`` turns server responses into
merge-or-refuse decisions inside three ``--jq`` programs, and the stub used to
emit **post-jq** text at every call site — so no test evaluated any of them, and
``test_an_empty_check_set_is_never_success`` passed because the fixture was told
to print an empty string rather than because the expression yielded one.
Swapping the check-run slice ``.[-1:][]`` for ``last`` kept the whole suite
green while making a named arm dead code. The stub now holds **raw JSON** and
runs each call's own program over it with a real engine, so the expressions
decide. ``jq`` is resolved through :func:`_jq`, and that is load-bearing: the
resolution is what puts jq in the set the gate's toolchain preflight is derived
from (``tests/unit/_toolchain.py``), so the engine these tests need cannot go
missing from a gate that reports green.

The gap that leaves, stated so it does not read as closed: ``gh --jq`` is
evaluated by the engine embedded in ``gh``, **not** by the ``jq`` binary. What
is measured here is these programs under ``jq``; a divergence between the two
engines is live and nothing here claims gh's answer.

Nothing here can touch the real repository, the real gate, or the real GitHub.
Every ``git`` and ``gh`` invocation goes to a stub on ``PATH``, the subprocess
runs with ``cwd`` under ``tmp_path``, and the only ``scripts/verify.sh`` the
script can reach is the fake one this module writes into the workspace it is
handed. The fixture's repository slug is deliberately **not** this repo's, so a
test that passed because the real slug leaked in could not hide.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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

#: The check-run poll's slice, mutated by the AC-5 differential below. Written
#: once, so the landing assert and the replacement cannot drift apart.
_CHECK_RUN_SLICE = ".[-1:][]"


def _jq() -> str:
    """The engine this module evaluates the script's ``--jq`` programs with.

    Resolved through ``shutil.which``, and that is **load-bearing rather than
    stylistic**: resolving it here is what puts ``jq`` in the set
    ``tests/unit/_toolchain.py`` derives, which is what obliges
    ``scripts/verify.sh`` to probe it (#491). Invoking jq by literal name
    instead would leave it out of that set, the probe would fail the preflight's
    stale direction, and the two halves of #491 would contradict each other.
    """
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq not available")
    return jq


def _check_run(status: str, conclusion: str | None, started_at: str) -> dict[str, object]:
    """One entry of GitHub's ``check_runs`` array, as the API returns it."""
    return {"status": status, "conclusion": conclusion, "started_at": started_at}


def _check_runs(*runs: Mapping[str, object]) -> str:
    """A raw ``/check-runs`` response document."""
    return json.dumps({"check_runs": list(runs)})


def _pull_request(number: int, *, draft: bool = False, head: str = _CANDIDATE) -> dict[str, object]:
    """One entry of ``gh pr list --json number,isDraft,headRefOid``."""
    return {"number": number, "isDraft": draft, "headRefOid": head}


def _pr_list(*entries: Mapping[str, object]) -> str:
    """A raw ``gh pr list`` response document."""
    return json.dumps(list(entries))


#: No run of the required check exists on the candidate. The document the AC-5
#: differential turns on: the shipped slice yields nothing from it, ``last``
#: yields ``null``.
_NO_CHECK_RUNS = _check_runs()

#: The promotable default — one completed, successful run.
_GREEN_CHECK = _check_runs(_check_run("completed", "success", "2026-08-19T02:00:00Z"))

#: What ``gh api --method PUT .../merge`` returns. More than the one field the
#: script reads, so ``--jq .sha`` is doing work rather than echoing the document.
_MERGE_RESPONSE = json.dumps(
    {"sha": _MERGE_SHA, "merged": True, "message": "Pull Request successfully merged"}
)

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
#:
#: Until #491 every scenario field was **post-jq** text: the stub never saw a
#: ``--jq`` program, so none of the script's three expressions was evaluated by
#: anything and ``test_an_empty_check_set_is_never_success`` passed because the
#: fixture said to print an empty string. The stub now holds **raw JSON** and
#: runs the call's own program over it with a real engine, so the expressions
#: decide the outcome the way they do in production.
#:
#: Three properties this shape needs, each of which is a defect if missed:
#:
#: * both spellings are accepted (``--jq PROG`` and ``--jq=PROG``). The script
#:   uses the two-token form at all three sites; a stub that fell through
#:   silently on the other is #490's exact defect.
#: * a call the fixture hands a document to and which carries **no** ``--jq``
#:   fails loudly. Otherwise a script that stopped filtering would push raw JSON
#:   into ``$pr_line`` and the module would go on passing about the wrong thing.
#: * jq is invoked by the absolute path the module resolved (``STUB_JQ``),
#:   mirroring ``_node()``, rather than trusting the stub to inherit a usable
#:   ``PATH``. The document arrives on **stdin from a file** and the program is
#:   one argument, so a program containing shell metacharacters is data.
_GH_STUB = r"""#!/bin/sh
set -eu
{ printf '%s\0' "$PWD" gh "$@"; printf '\n'; } >> "$STUB_RECORD"

jq_prog=""
have_jq=0
prev=""
for arg in "$@"; do
  case "$arg" in
    --jq=*) jq_prog="${arg#--jq=}"; have_jq=1; break ;;
  esac
  if [ "$prev" = "--jq" ]; then jq_prog="$arg"; have_jq=1; break; fi
  prev="$arg"
done

_filter() {
  if [ ! -f "$STUB_STATE/$1" ]; then return 0; fi
  if [ "$have_jq" -eq 0 ]; then
    echo "gh stub: handed the raw document $1 with no --jq program to filter it" >&2
    exit 3
  fi
  "$STUB_JQ" -r "$jq_prog" < "$STUB_STATE/$1"
}

_emit() {
  if [ -f "$STUB_STATE/$1" ]; then cat "$STUB_STATE/$1"; fi
}

_code() {
  if [ -f "$STUB_STATE/$1" ]; then cat "$STUB_STATE/$1"; else echo 0; fi
}

case "$1" in
  pr)
    case "${2:-}" in
      list) _filter pr-list.json ;;
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
        if [ -f "$STUB_STATE/check-runs.$n.json" ]; then
          _filter "check-runs.$n.json"
        else
          _filter check-runs.last.json
        fi
        ;;
      *"/merge"*)
        code="$(_code merge.exit)"
        if [ "$code" -eq 0 ]; then _filter merge.json; else echo "gh: merge refused (stub)" >&2; fi
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
    #: The **raw** ``gh pr list`` document. The script's own ``--jq`` projection
    #: turns it into the ``<number> <isDraft> <headRefOid>`` line it reads.
    pr_list_json: str = "[]"
    pr_create_out: str = _PR_URL
    pr_create_exit: int = 0
    #: The scripted **raw** check-run documents, one per poll, the last one
    #: repeating. The poll's own ``sort_by``/slice decides what it observes.
    check_runs_json: Sequence[str] = (_GREEN_CHECK,)
    merge_exit: int = 0
    #: The **raw** merge response. ``--jq .sha`` is what reads the SHA out of it.
    merge_json: str = _MERGE_RESPONSE
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
    (state / "pr-list.json").write_text(scenario.pr_list_json, encoding="utf-8")
    (state / "pr-create.out").write_text(f"{scenario.pr_create_out}\n", encoding="utf-8")
    (state / "pr-create.exit").write_text(str(scenario.pr_create_exit), encoding="utf-8")
    assert scenario.check_runs_json, (
        "a scenario with no check-run document at all would leave the poll "
        "filtering nothing; the absent-check case is the empty *document* "
        f"{_NO_CHECK_RUNS!r}, which is what the slice has to answer about"
    )
    for number, document in enumerate(scenario.check_runs_json, start=1):
        (state / f"check-runs.{number}.json").write_text(document, encoding="utf-8")
    (state / "check-runs.last.json").write_text(
        scenario.check_runs_json[-1], encoding="utf-8"
    )
    (state / "merge.json").write_text(scenario.merge_json, encoding="utf-8")
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
        "STUB_JQ": _jq(),
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


def _inline_scalar(raw: str) -> str:
    """A YAML **inline** scalar's value, or ``""`` when there is none to read.

    Empty for every spelling whose value is not on this line: nothing at all
    (``name:``), and a block or folded indicator (``name: >-``) whose scalar
    begins on the next one. The caller turns that into a refusal — reading it as
    "no name declared" is the silent mis-derivation this exists to make loud.
    """
    value = raw.strip()
    if value[:1] in {"'", '"'}:
        end = value.find(value[0], 1)
        return value[1:end] if end != -1 else ""
    value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    return "" if value in {"", "|", ">", "|-", ">-", "|+", ">+"} else value


def _check_run_names(workflow: str) -> set[str]:
    """The check-run names ``workflow``'s ``jobs:`` mapping will publish.

    GitHub names a check run after the job's ``name:`` where it declares one and
    after its **key** otherwise, so a key is the right answer only while no
    ``name:`` shadows it: adding ``name: Build and test`` to ``lint-and-test``
    would leave a key-derived correspondence green while the poll waited forever
    for a check that no longer exists under that name (#485).

    Two rules keep this from becoming the same defect one spelling over — the
    hole a second review found live in the first fix, which read an *inline*
    ``name:`` and silently kept the key for every other spelling:

    * a ``name:`` whose value is not on its own line is a **refusal**, not a
      fall back to the key (``ADR 0016`` — an unresolvable anchor must fail
      rather than go quiet);
    * the value is read as a YAML inline scalar, so a trailing comment or
      surrounding quotes do not become part of the published name.

    Takes the text rather than reading the one file, because a derivation fed
    only production data is indistinguishable from a hardcoded constant: the
    cases below feed it input whose answer differs from this repo's.
    """
    names: set[str] = set()
    current: str | None = None
    declared: str | None = None
    in_jobs = False

    for line in workflow.splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line.strip() and not line.startswith(" "):
            break
        key = re.match(r"^ {2}([A-Za-z0-9_-]+):\s*$", line)
        if key is not None:
            if current is not None:
                names.add(current if declared is None else declared)
            current, declared = key.group(1), None
            continue
        # A job-level `name:` — exactly four spaces — shadows the key.
        shadow = re.match(r"^ {4}name:(.*)$", line)
        if shadow is None or current is None:
            continue
        value = _inline_scalar(shadow.group(1))
        assert value, (
            f"job {current!r} declares a `name:` whose value this derivation "
            f"cannot read ({line!r}). GitHub will publish that name, not "
            f"{current!r}, and guessing the key here is exactly the silent "
            "mis-derivation this refusal exists to stop — put the value on the "
            "`name:` line, or teach this function the spelling"
        )
        assert declared is None, (
            f"job {current!r} declares `name:` twice ({declared!r}, then "
            f"{value!r}); which one GitHub publishes is not this guard's guess "
            "to make"
        )
        declared = value

    if current is not None:
        names.add(current if declared is None else declared)
    return names


def _ci_check_run_names() -> set[str]:
    """:func:`_check_run_names` over the tracked ``ci.yml``."""
    return _check_run_names(CI_WORKFLOW.read_text(encoding="utf-8"))


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
    # E3 (AC-4). The merge response carries three fields and the script reads one
    # of them with `--jq .sha`. Reporting the SHA the expression pulled out is
    # what makes that filter load-bearing: `.commit.sha`, or no filter at all,
    # yields `null`, which this assertion refuses.
    assert _MERGE_SHA in run.stdout, (
        f"the promotion did not report the SHA the merge API returned: {run.stdout!r}"
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
    failed = _check_runs(_check_run("completed", "failure", "2026-08-19T02:00:00Z"))
    run = _run_promotion_step(tmp_path, Scenario(check_runs_json=(failed,)))

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
        Scenario(
            check_runs_json=(_check_runs(_check_run("in_progress", None, "2026-08-19T02:00:00Z")),),
            check_wait_seconds=2,
            check_poll_seconds=1,
        ),
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

    **Which arm** it takes is asserted too, and that half only became a
    measurement at #491. Until then the stub was *told* to print an empty
    string, so the assertion held whatever the poll's expression did; now the
    empty document goes through a real engine and the emptiness is the
    expression's own answer. The arm matters because both arms exit non-zero:
    the mutation from ``.[-1:][]`` to ``last`` reports a state
    (``null null``) the API never returned, which is a night an operator
    debugs in the wrong place.
    """
    run = _run_promotion_step(tmp_path, Scenario(check_runs_json=(_NO_CHECK_RUNS,)))

    assert run.returncode != 0, (
        "an empty check-run set left the step reporting success — an absent "
        "required check must never read as a passed one"
    )
    assert "::error::" in run.stdout, run.stdout
    assert run.check_reads, "the required check was never read"
    assert "no run of" in run.stdout, (
        "the poll reported something other than its named empty-set arm for a "
        f"check-run set that is genuinely empty: {run.stdout!r}"
    )
    assert "null null" not in run.stdout, (
        "the poll reported an observed state of `null null`, which GitHub never "
        f"returned — the expression read past the end of an empty array: {run.stdout!r}"
    )
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


#: A head that is emphatically not the gated candidate.
_MOVED_HEAD = "2222222222222222222222222222222222222222"


@pytest.mark.parametrize(
    ("pr_list_json", "why", "named"),
    [
        (
            _pr_list(_pull_request(23, head=_MOVED_HEAD)),
            "its head is not the candidate",
            _MOVED_HEAD,
        ),
        (_pr_list(_pull_request(23, draft=True)), "it is a draft", "draft=true"),
    ],
    ids=["head-moved", "draft"],
)
def test_an_unusable_open_pull_request_is_refused(
    pr_list_json: str, why: str, named: str, tmp_path: Path
) -> None:
    """R13. A reusable pull request must be exactly the one this run would open.

    Head ``dev`` into base ``main`` *is* the promotion by definition, so reusing
    a human's is benign — but only when its head is the gated candidate and it
    is not a draft. Anything else is refused rather than merged or amended.

    AC-4: both cases are decided by ``gh pr list``'s own ``--jq`` projection.
    The fixture is the raw array GitHub returns; the refusal names the field the
    expression pulled out of it, so a projection that dropped ``isDraft`` or
    ``headRefOid`` — or reordered them — reports the wrong thing here rather
    than passing on pre-filtered text that could not have been wrong.
    """
    run = _run_promotion_step(tmp_path, Scenario(pr_list_json=pr_list_json))

    assert run.returncode != 0, f"an open pull request was merged although {why}"
    assert "::error::" in run.stdout, run.stdout
    assert "gh pr list" in run.calls, "the open pull requests were never listed"
    assert named in run.stdout, (
        f"the refusal must name what the projection actually observed ({named}): "
        f"{run.stdout!r}"
    )
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


# --- The `--jq` expressions, under a real engine -------------------------------
#
# AC-4. `scripts/promotion-step.sh` turns server responses into merge-or-refuse
# decisions inside three `--jq` programs, and until #491 no test evaluated any
# of them: the stub emitted post-jq text at every call site, so the expressions
# were asserted *past* rather than measured. The cases below feed raw documents
# and let each expression's own output decide.
#
# What is measured, and what is not. These programs are evaluated here by the
# **jq binary** this module resolves; in production they are evaluated by the
# engine embedded in `gh`. A divergence between the two is a live gap this
# change does not close, and nothing below claims gh's answer. Two facts were
# measured out of gate rather than assumed (gh 2.93.0, 2026-08-19), because the
# script's `awk` parsing depends on them and this repo has shipped a platform
# mechanism asserted from memory before:
#
#   gh api repos/sluengen/harness --jq .name              -> `harness\n`
#   gh api repos/sluengen/harness --jq '"\(.name) \(.private)"' -> `harness false\n`
#
# i.e. gh prints a string result raw, without quotes, and renders a boolean as a
# bare word — which is what makes `awk '{ print $2 }'` read `false` rather than
# `"false"`. The expressions here stay inside the core subset both engines
# share, and every `started_at` is distinct so nothing depends on sort stability.


def _run_gh_stub(
    tmp_path: Path, argv: Sequence[str], documents: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    """Drive the ``gh`` stub directly, with no script in the way."""
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "gh"
    stub.write_text(_GH_STUB, encoding="utf-8")
    stub.chmod(0o755)
    for name, text in documents.items():
        (state / name).write_text(text, encoding="utf-8")
    record = tmp_path / "invocations"
    record.write_bytes(b"")
    return subprocess.run(
        [str(stub), *argv],
        env={
            "PATH": "/usr/bin:/bin",
            "STUB_RECORD": str(record),
            "STUB_STATE": str(state),
            "STUB_JQ": _jq(),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize(
    "flag",
    [["--jq", ".[] | .number"], ["--jq=.[] | .number"]],
    ids=["two-token", "equals"],
)
def test_the_gh_stub_evaluates_the_program_the_call_carries(
    flag: list[str], tmp_path: Path
) -> None:
    """The instrument's own test — a defect here is a silent green module-wide.

    The stub is now the thing that decides what every promotion test observes,
    so it is exercised directly: a known program over a known document, with an
    answer that is neither the document nor any substring of the fixture. Both
    ``--jq`` spellings are covered because a stub that fell through silently on
    the one the script does not currently use would be a hole that opens the day
    someone respells a call site (#490).
    """
    proc = _run_gh_stub(
        tmp_path,
        ["pr", "list", "--repo", _REPO, *flag],
        {"pr-list.json": _pr_list(_pull_request(7), _pull_request(9))},
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "7\n9\n", (
        f"the stub did not evaluate the program it was handed: {proc.stdout!r}"
    )


def test_the_gh_stub_refuses_a_call_that_filters_nothing(tmp_path: Path) -> None:
    """A document handed to a call with no ``--jq`` is a loud failure.

    Without this, a script that stopped filtering would push a raw JSON document
    into ``$pr_line``, and every assertion in this module would go on passing
    about text that production never produces.
    """
    proc = _run_gh_stub(
        tmp_path,
        ["pr", "list", "--repo", _REPO],
        {"pr-list.json": _pr_list(_pull_request(7))},
    )

    assert proc.returncode != 0, (
        f"the stub filtered nothing and reported success anyway: {proc.stdout!r}"
    )
    assert "--jq" in proc.stderr, f"the refusal must say what was missing: {proc.stderr!r}"


def test_an_open_pull_request_this_run_would_have_opened_is_reused(tmp_path: Path) -> None:
    """E1, the accepting direction: a usable open pull request is merged, not re-created.

    Last night's refused promotion leaves its pull request open, and a second one
    from the same head would be refused by GitHub anyway. Two entries, so the
    ``.[]`` in the projection yields two lines and ``awk 'NR == 1'`` has
    something to choose: the decoy second entry is a draft on a moved head, and
    reading it instead would turn this run into a refusal.
    """
    listing = _pr_list(
        _pull_request(23),
        _pull_request(99, draft=True, head=_MOVED_HEAD),
    )

    run = _run_promotion_step(tmp_path, Scenario(pr_list_json=listing))

    assert run.returncode == 0, f"a reusable pull request was refused: {run.stdout}\n{run.stderr}"
    assert "gh pr create" not in run.calls, (
        f"a pull request was opened although one was reusable: {run.argv_for('gh pr create')}"
    )
    assert len(run.merges) == 1, f"expected exactly one merge; recorded {run.merges}"
    assert f"repos/{_REPO}/pulls/23/merge" in run.merges[0][1], (
        f"the merge did not name the pull request the listing's first entry gave: "
        f"{run.merges[0][1]}"
    )


@pytest.mark.parametrize(
    ("latest", "earliest", "promotes"),
    [
        (
            _check_run("completed", "success", "2026-08-19T02:00:00Z"),
            _check_run("completed", "failure", "2026-08-19T01:00:00Z"),
            True,
        ),
        (
            _check_run("completed", "failure", "2026-08-19T02:00:00Z"),
            _check_run("completed", "success", "2026-08-19T01:00:00Z"),
            False,
        ),
    ],
    ids=["latest-is-green", "latest-is-red"],
)
def test_the_poll_scores_the_latest_run_by_started_at_not_by_array_order(
    latest: Mapping[str, object],
    earliest: Mapping[str, object],
    promotes: bool,
    tmp_path: Path,
) -> None:
    """E2, the case that makes ``sort_by(.started_at)`` real.

    "Latest by ``started_at``" matches how branch protection scores a name with
    several runs, so a re-run after a flake does not strand the candidate. In
    both documents the array's **last** element is the *earlier* run, so an
    expression that dropped the sort would read the wrong one — and both
    directions are here, because a single case would be satisfied by an
    expression that always answers the same way. Distinct timestamps throughout:
    nothing may depend on sort stability.
    """
    document = _check_runs(latest, earliest)

    run = _run_promotion_step(tmp_path, Scenario(check_runs_json=(document,)))

    if promotes:
        assert run.returncode == 0, (
            f"the latest run concluded success and the night still refused: {run.stdout}"
        )
        assert run.merges, "nothing was merged although the latest run was green"
    else:
        assert run.returncode != 0, (
            f"the latest run concluded failure and the night promoted anyway: {run.stdout}"
        )
        assert "failure" in run.stdout, (
            f"the annotation must name the conclusion it observed: {run.stdout!r}"
        )
        _assert_nothing_was_merged(run, "the latest required-check run concluded failure")


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


def test_every_ls_remote_names_a_fully_qualified_ref() -> None:
    """F5. Every ``ls-remote`` pattern is a full ``refs/heads/`` ref (#485).

    ``git ls-remote --heads origin dev`` matches on the ref name's **tail**, so
    it also selects ``refs/heads/anything/dev`` — measured on this repo, where
    ``git ls-remote --heads . 485`` answers ``refs/heads/work/485``. The source
    call site then reads ``awk 'NR == 1'``, i.e. whichever the remote listed
    first, and would compare the gated candidate against a stranger's tip.

    This is a **text** guard over an executed script, which needs its reason
    stated: nothing the executed suite runs can see the difference. The ``git``
    stub takes the call's last argument and strips a leading ``refs/heads/``, so
    a qualified and a bare pattern arrive at the same fixture key by
    construction — reverting either call site leaves the whole module green
    (mutation-proved). The stub still distinguishes a *wrong* branch; it cannot
    distinguish a *wrongly-scoped* one, and this is where that half lives.

    Both floors are here rather than assumed: the call sites are counted, and
    the count of sites this guard actually read is compared with the count of
    ``git ls-remote`` occurrences in the script, so a third call site written in
    a spelling the pattern below misses fails instead of going unmeasured.
    """
    script = _script()
    occurrences = len(re.findall(r"git ls-remote\b", script))
    patterns = re.findall(r"git ls-remote\s[^\n]*?\sorigin\s+(\S+)", script)

    assert occurrences == 2, (
        f"{SCRIPT.name} makes {occurrences} `git ls-remote` calls, not the two "
        "this guard was written over (the target's existence, and the source's "
        "tip against the gated candidate) — re-derive it rather than widening it"
    )
    assert len(patterns) == occurrences, (
        f"this guard read {len(patterns)} of {occurrences} `git ls-remote` call "
        "sites; one is written in a spelling it cannot see, which would leave "
        "that site unmeasured while the suite stayed green"
    )
    for pattern in patterns:
        assert pattern.startswith('"refs/heads/'), (
            f"`git ls-remote ... origin {pattern}` is an unqualified pattern: "
            "ls-remote matches on the ref name's tail, so it also selects "
            f"`refs/heads/*/{pattern.strip(chr(34))}`. Name the full ref."
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
    published = _ci_check_run_names()
    required = _script_constant(r'REQUIRED_CHECK="([^"]+)"')
    assert published, "no check names were derived from ci.yml, so the check below compares nothing"
    assert required in published, (
        f"scripts/promotion-step.sh waits for a check named {required!r}, which is "
        f"not one ci.yml publishes ({sorted(published)}) — the poll would never "
        "see it complete"
    )


#: ``(id, jobs-block, expected published names)``. Every case answers something
#: this repo's own ``ci.yml`` cannot: it declares no job-level ``name:`` at all,
#: so before these the shadowing branch ran zero times and a green suite said
#: nothing about it.
_PUBLISHED_NAME_CASES = (
    ("a bare key publishes itself", "jobs:\n  lint-and-test:\n    runs-on: x\n", {"lint-and-test"}),
    (
        "an inline name shadows the key",
        "jobs:\n  lint-and-test:\n    name: Build and test\n    runs-on: x\n",
        {"Build and test"},
    ),
    (
        "quotes are not part of the published name",
        'jobs:\n  lint-and-test:\n    name: "Build and test"\n    runs-on: x\n',
        {"Build and test"},
    ),
    (
        "a trailing comment is not part of the published name",
        "jobs:\n  lint-and-test:\n    name: Build  # what GitHub shows\n    runs-on: x\n",
        {"Build"},
    ),
    (
        "a step-level name is not the job's",
        "jobs:\n  lint-and-test:\n    steps:\n      - name: Run the gate\n        run: x\n",
        {"lint-and-test"},
    ),
    (
        "each job resolves on its own",
        "jobs:\n  one:\n    name: First\n    runs-on: x\n  two:\n    runs-on: x\n",
        {"First", "two"},
    ),
    (
        "nothing outside the jobs mapping is read",
        "name: CI\non:\n  push:\n    branches: [dev]\njobs:\n  lint-and-test:\n    runs-on: x\n",
        {"lint-and-test"},
    ),
)


@pytest.mark.parametrize(
    ("jobs", "expected"),
    [pytest.param(block, expected, id=name) for name, block, expected in _PUBLISHED_NAME_CASES],
)
def test_the_published_check_names_are_derived_from_the_workflow(
    jobs: str, expected: set[str]
) -> None:
    """F6. The derivation answers about its input, not about this repo.

    Fed only ``ci.yml``, :func:`_check_run_names` and a hardcoded
    ``{"lint-and-test"}`` are indistinguishable — every case here has an answer
    that differs from this repo's, which is the only way to tell them apart
    (``review-discipline/references/craft.md``).
    """
    assert _check_run_names(jobs) == expected


@pytest.mark.parametrize(
    "declaration",
    ["    name:", "    name: >-", "    name: |", "    name:   "],
    ids=["empty", "folded", "literal", "whitespace"],
)
def test_a_name_this_derivation_cannot_read_is_a_refusal(declaration: str) -> None:
    """F6's other direction, and the one that was live (#485, second review).

    Each spelling here publishes a check name that is **not** the key — the
    scalar simply starts on the next line. The first fix read an inline value
    only and fell back to the key for all of them, so a mutation adding

    .. code-block:: yaml

        lint-and-test:
          name:
            Build and test

    to ``ci.yml`` left the correspondence green while the poll waited forever
    for a check named ``lint-and-test`` that GitHub no longer publishes
    (mutation-proved SURVIVED (LIVE)). An anchor this cannot resolve must fail
    loudly rather than answer confidently (ADR 0016).
    """
    workflow = f"jobs:\n  lint-and-test:\n{declaration}\n      Build and test\n    runs-on: x\n"

    with pytest.raises(AssertionError, match="cannot read"):
        _check_run_names(workflow)


def test_the_live_ci_workflow_still_resolves() -> None:
    """The floor under both cases above: the real corpus is read and answers.

    Synthetic input proves the derivation; it cannot prove the file exists, is
    reachable, or parses. Without this, deleting ``ci.yml`` would leave the
    parametrized cases above green — a sweep with no floor on its corpus.
    """
    assert _ci_check_run_names() == {"lint-and-test"}


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


def test_the_check_run_slice_decides_which_arm_the_poll_takes(tmp_path: Path) -> None:
    """AC-5. ``.[-1:][]`` and ``last`` disagree on an empty check set.

    The differential, run twice: the tracked script, and a copy with the slice
    replaced. On ``{"check_runs": []}`` the shipped slice yields **nothing**, so
    the poll takes its *named* "no run yet" arm; ``last`` yields ``null``, whose
    interpolation is the string ``null null``, so the poll takes the catch-all
    arm and reports a state that was never observed. Both time out and both exit
    non-zero, so an exit-code assertion cannot see this mutation at all — the
    discriminator is which arm the diagnostic names.

    What this measures is **jq**, not ``gh``: ``gh --jq`` is evaluated by the
    engine embedded in ``gh``, and these programs are evaluated here by the
    ``jq`` binary this module resolves. A divergence between the two engines is
    a live gap this does not close, and no assertion here claims gh's answer.
    """
    shipped = _script()
    mutated = shipped.replace(_CHECK_RUN_SLICE, "last")
    assert shipped.count(_CHECK_RUN_SLICE) == 1, (
        f"expected exactly one {_CHECK_RUN_SLICE!r} in {SCRIPT.name}; the "
        "differential below would otherwise mutate nothing, or mutate twice"
    )
    assert mutated != shipped, "the mutation landed nowhere, so this proves nothing"

    scenario = Scenario(check_runs_json=(_NO_CHECK_RUNS,))
    shipped_dir, mutated_dir = tmp_path / "shipped", tmp_path / "mutated"
    shipped_dir.mkdir()
    mutated_dir.mkdir()
    baseline = _run_promotion_step(shipped_dir, scenario)
    variant = _run_promotion_step(mutated_dir, scenario, script_text=mutated)

    assert "no run of" in baseline.stdout, (
        f"the shipped slice did not reach the named empty-set arm: {baseline.stdout!r}"
    )
    assert "no run of" not in variant.stdout, (
        "replacing the check-run slice with `last` changed nothing the suite can "
        "see, so the empty-set arm is dead code no test defends: "
        f"{variant.stdout!r}"
    )
    assert "null null" in variant.stdout, (
        "…and the state `last` actually produces is not what the annotation "
        f"reported, so this differential is measuring something else: {variant.stdout!r}"
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
