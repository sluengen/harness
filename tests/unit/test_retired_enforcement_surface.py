"""The shape #621 leaves behind: two exports, one advisory, no verdict reader.

ADR 0022 makes three claims this module measures directly, because each one is
a *boundary* rather than a behaviour and nothing else in the suite asserts it
once the modules that used to carry it are deleted.

**Point 3 — a plugin-shipped executable reads what *is*, never what *passed*.**
The retired complex read a verdict: `gate-evidence-guard.js` asked whether a
marker covered the worked tree, `push-target-guard.js` asked the same question
of the pushed tree, and `scripts/mutate.py`'s gate lock asked it of the tree it
was about to mutate. What survives may read the intercepted call, the
declaration in `harness.yaml`, the run's own state and what git can answer.
:func:`test_no_shipped_executable_reads_gate_state` holds that boundary over the
whole shipped executable set rather than over a list of the files this ticket
happened to touch — the enumeration is what went stale twice during #620's
review, and a boundary guard that reads a list stops firing the moment someone
adds a file to it.

**Point 4 — default to no guard; refuse only on two grounds.** The push guard's
branch recognition survives as an advisory, so the assertion is not that it
approves but that it *cannot* deny: an advisory tolerates false negatives and
stays small, and a hook that can still emit `deny` is a refusal wearing an
advisory's name.

**AC-4's sharpest risk, stated as a test.** Narrowing the reader is the one
change in #621 that can *silently* disarm the guard the programme keeps.
`hooks/test-lock-guard.js` reaches the reader for `declaredPaths` alone, and law
7 rests on it; if the narrowing dropped that export the lock would not fail
loudly, it would report itself inactive and let every test edit through. The
export-surface test and the still-deactivates test are the two halves of that
one risk.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

REPO_ROOT = Path(__file__).resolve().parents[2]
READER = REPO_ROOT / "scripts" / "harness-config.js"
HOOKS = REPO_ROOT / "hooks"

#: The reader's whole public surface after #621. `declaredBranches` serves the
#: advisory push guard and `plugin-version.js`; `declaredPaths` serves the test
#: lock. Named rather than counted: a count tells a later reader nothing about
#: which export it may rely on, and the name is the contract.
EXPECTED_EXPORTS = {"declaredBranches", "declaredPaths"}

#: What "reads a verdict" looks like in source. These are the retired complex's
#: own spellings — the marker directory it wrote, the helper that owned it, and
#: the Stop hook that read it. A file matching any of them is reading what
#: passed rather than what is.
VERDICT_READS = re.compile(
    r"harness/gate/|gate-marker|gate_marker|gate-evidence|gate_evidence"
    r"|markerFor|markerPath|reviewed_tree|gate_marker_tree",
)



def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _run_node(script: str, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        [_node(), "-e", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def _repo(tmp_path: Path, name: str, config: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--initial-branch=dev"], cwd=root, check=True)
    (root / "harness.yaml").write_text(config, newline="")
    return root


def _push_hook_output(command: str, cwd: Path) -> dict:
    """The advisory's whole stdout object for a Bash call running ``command``."""
    payload = {
        "session_id": "t",
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    proc = subprocess.run(
        [_node(), str(HOOKS / "push-target-guard.js")],
        input=json.dumps(payload),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"hook errored (rc={proc.returncode}): {proc.stderr}"
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# AC-4 — the reader narrows without disarming the guard that survives.
# --------------------------------------------------------------------------


def test_the_reader_exports_exactly_the_two_names_its_consumers_use(tmp_path: Path) -> None:
    """Both directions. A missing export breaks a consumer; a surviving one is a
    contract nobody has, and every one of the nine removed here had a consumer
    that leaves in this ticket or the next."""
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(JSON.stringify(Object.keys(c)));",
        tmp_path,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert set(json.loads(proc.stdout)) == EXPECTED_EXPORTS


def test_the_test_lock_still_reports_inactive_when_no_test_path_is_declared(
    tmp_path: Path,
) -> None:
    """The narrowing's sharpest failure mode is silent, not loud: `declaredPaths`
    gone would make the lock read *no declared test path* — which is exactly how
    it reports a repo that declares none — so law 7 would stop holding with
    nothing on stderr. This asserts the two cases still differ."""
    declared = _repo(tmp_path, "declares", "paths:\n  tests: tests/\n")
    silent = _repo(tmp_path, "silent", "repo:\n  name: x\n")

    script = (
        "const c = require(process.env.READER);"
        "process.stdout.write(JSON.stringify(c.declaredPaths(process.cwd())));"
    )
    with_tests = _run_node(script, declared, {"READER": str(READER)})
    without = _run_node(script, silent, {"READER": str(READER)})

    assert with_tests.returncode == 0, with_tests.stderr
    assert without.returncode == 0, without.stderr
    assert json.loads(with_tests.stdout).get("tests") == "tests/"
    assert json.loads(without.stdout).get("tests") in (None, "")


# --------------------------------------------------------------------------
# AC-3 — the push guard advises and cannot refuse.
# --------------------------------------------------------------------------


def test_a_push_to_a_declared_branch_warns_and_proceeds(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "declared", "branches:\n  integration: dev\n  release: main\n")
    out = _push_hook_output("git push origin dev", repo)

    assert out.get("continue") is True
    assert "permissionDecision" not in out
    assert "dev" in out.get("additionalContext", "")


def test_a_push_to_an_undeclared_branch_says_nothing(tmp_path: Path) -> None:
    """An advisory that fires on everything is noise, and noise is how a warning
    stops being read."""
    repo = _repo(tmp_path, "undeclared", "branches:\n  integration: dev\n  release: main\n")
    out = _push_hook_output("git push origin scratch/experiment", repo)

    assert out.get("continue") is True
    assert "additionalContext" not in out


def test_the_advisory_cannot_deny(tmp_path: Path) -> None:
    """Across every shape the retired guard refused — a bare push, an explicit
    refspec, a force, a push from outside a repository — the reduced hook emits
    no decision at all. `deny` is not reachable, which is what makes this an
    advisory rather than a refusal that currently happens to approve."""
    repo = _repo(tmp_path, "nodeny", "branches:\n  integration: dev\n  release: main\n")
    for command in (
        "git push",
        "git push origin dev",
        "git push origin HEAD:dev",
        "git push --force origin dev",
        "git push origin +HEAD:dev",
        "git -C /elsewhere push origin main",
    ):
        out = _push_hook_output(command, repo)
        assert out.get("continue") is True, command
        assert "permissionDecision" not in out, command


def test_an_unreadable_declaration_is_loud_and_falls_back_conservatively(
    tmp_path: Path,
) -> None:
    """Preserved from `test_hooks_unreadable_declaration_is_loud.py`, which #621
    deletes because its subject was two hooks agreeing and only one is left.

    The surviving half is this one, and it does not depend on there being two:
    a declaration the reader cannot parse must leave the advisory warning on the
    conservative fallback set and saying so on stderr. Degrading to an *empty*
    set would be a guard that has quietly stopped answering — the #302 shape,
    and the reason `.claude/rules/scripts.md` states the floor.
    """
    repo = _repo(tmp_path, "unreadable", "branches: {integration: dev\n")
    payload = {
        "session_id": "t",
        "cwd": str(repo),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
    }
    proc = subprocess.run(
        [_node(), str(HOOKS / "push-target-guard.js")],
        input=json.dumps(payload),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out.get("continue") is True
    assert "main" in out.get("additionalContext", ""), (
        "an unreadable declaration left the advisory protecting nothing rather "
        f"than the fallback set; stderr was {proc.stderr!r}"
    )


# --------------------------------------------------------------------------
# ADR 0022 point 3 — over the shipped set, not over a list.
# --------------------------------------------------------------------------


def test_no_shipped_executable_reads_gate_state() -> None:
    """The boundary, swept rather than enumerated.

    Prose and specs are excluded deliberately: a record may *describe* the
    retired mechanism, and ADR 0022 itself quotes the sentence it forbids. What
    point 3 binds is executable code.

    No exemptions. This carried a self-retiring one for `land.js` and
    `harness-refs.js` while they were still #622's to delete; the operator folded
    that deletion into this ticket instead, because `land.js` requires the marker
    helper directly and is non-functional without it, so the exemption went with
    the files rather than outliving them.
    """
    reading = {}
    for path in sorted(tracked_files_under("hooks") | tracked_files_under("scripts")):
        if path.suffix not in {".js", ".py", ".sh"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = sorted({m.group(0) for m in VERDICT_READS.finditer(text)})
        if hits:
            reading[str(path.relative_to(REPO_ROOT))] = hits

    assert reading == {}, (
        "ADR 0022 point 3: a plugin-shipped executable reads what *is*, never "
        f"what *passed*. These read gate state: {reading}"
    )
