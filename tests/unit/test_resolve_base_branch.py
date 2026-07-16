"""``harness.cli._git.resolve_base_branch`` — the base-branch resolution order.

CAL-1106: the base a run builds off (and a merged worktree is reclaimed against)
is no longer the literal ``"dev"``. It resolves, in order:

1. an explicit value (``start --base``),
2. ``branches.integration`` from the repo's CONTEXT.md,
3. the repo's actual default branch (``git symbolic-ref refs/remotes/origin/HEAD``),
4. ``"dev"`` as the final back-compat fallback.

These tests lock each rung and the precedence between them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from harness.cli._git import origin_default_branch, resolve_base_branch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(repo: Path, branch: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", "-b", branch, str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "init")


def _write_context(repo: Path, integration: str) -> None:
    (repo / "CONTEXT.md").write_text(f"branches:\n  integration: {integration}\n")


def test_explicit_base_wins_over_everything(tmp_path: Path) -> None:
    """An explicit value short-circuits — CONTEXT and git are never consulted."""
    repo = tmp_path / "repo"
    _init_repo(repo, "dev")
    _write_context(repo, "trunk")
    assert resolve_base_branch(repo, "hotfix") == "hotfix"


def test_context_integration_used_when_no_explicit(tmp_path: Path) -> None:
    """With no explicit value, ``branches.integration`` from CONTEXT.md wins."""
    repo = tmp_path / "repo"
    _init_repo(repo, "dev")
    _write_context(repo, "trunk")
    assert resolve_base_branch(repo, None) == "trunk"


def test_git_default_used_when_no_context(tmp_path: Path) -> None:
    """No explicit and no CONTEXT ``branches:`` → the repo's origin default HEAD."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "mainline", str(origin)],
        check=True,
        capture_output=True,
    )
    repo = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "init")
    _git(repo, "push", "-q", "origin", "mainline")
    # Record origin/HEAD as a populated clone would (the empty clone above could
    # not — git only records it once the remote has a branch to point at).
    _git(repo, "remote", "set-head", "origin", "-a")
    # No CONTEXT.md → resolution falls to the origin default branch.
    assert origin_default_branch(repo) == "mainline"
    assert resolve_base_branch(repo, None) == "mainline"


def test_dev_is_the_final_fallback(tmp_path: Path) -> None:
    """No explicit, no CONTEXT, no origin/HEAD → the back-compat ``"dev"``."""
    repo = tmp_path / "repo"
    _init_repo(repo, "whatever")  # no remote, so origin/HEAD is unresolvable
    assert origin_default_branch(repo) is None
    assert resolve_base_branch(repo, None) == "dev"
