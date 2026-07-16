"""CAL-1106 — the workflow guard recognises a ``trunk`` default branch.

``hooks/workflow-guard.js`` warns (advisory, never blocks) when source is edited
on a *default* branch. Its default-branch set was ``main|master|dev|develop`` —
overfit to the common names and blind to ``trunk``. These tests execute the hook
as a node subprocess (the style of ``test_registry_self_version_hook``) against a
real git repo checked out on ``trunk`` and assert the guard names ``trunk`` as
the default branch it recognised.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "workflow-guard.js"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo_on(tmp_path: Path, branch: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", branch, str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "init")
    return repo


def _run_guard(repo: Path, edited: Path) -> str:
    """Run the guard for a Write of ``edited`` in ``repo``; return additionalContext.

    ``TMPDIR`` is redirected into the repo so the guard's 4h debounce marker is
    isolated and cannot suppress the warning across runs. The guard reads git
    state from the process CWD, so ``cwd`` is the repo under test.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    (repo / "_tmp").mkdir(exist_ok=True)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(edited)}}
    env = {**os.environ, "TMPDIR": str(repo / "_tmp")}
    proc = subprocess.run(
        [node, str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(repo),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    return json.loads(proc.stdout).get("additionalContext", "")


def test_guard_recognises_trunk_as_default(tmp_path: Path) -> None:
    """Editing source on ``trunk`` warns *because it is a default branch* — the
    message names ``trunk``, not the fall-through "not in a task worktree"."""
    repo = _repo_on(tmp_path, "trunk")
    ctx = _run_guard(repo, repo / "app.py")
    assert "WORKFLOW-GUARD" in ctx, f"expected an advisory warning; got: {ctx!r}"
    assert "you are on 'trunk'" in ctx, (
        f"the guard must recognise 'trunk' as a default branch (onDefault), not "
        f"warn only via the worktree fallback; got: {ctx!r}"
    )


def test_guard_does_not_call_a_feature_branch_a_default(tmp_path: Path) -> None:
    """A non-default branch name must not be reported as a default branch — the
    'on <branch>' phrasing is reserved for the recognised default set."""
    repo = _repo_on(tmp_path, "feature-x")
    ctx = _run_guard(repo, repo / "app.py")
    # (A plain checkout is not a worktree, so the guard still warns — but via the
    # worktree fallback, never claiming 'feature-x' is a default branch.)
    assert "you are on 'feature-x'" not in ctx, (
        f"a feature branch must not be recognised as a default branch; got: {ctx!r}"
    )
