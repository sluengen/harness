"""The ``.worktrees/harness/<run_id>`` layout convention has one source — CAL-590.

Before CAL-590 the root + per-run path were rebuilt independently in
``harness.identity``, ``harness.worktree``, and ``harness.cli.worktrees``; a
layout change needed all three in lockstep. These tests pin the convergence so
a future divergence fails loudly rather than silently drifting.
"""

from __future__ import annotations

from pathlib import Path

from harness import identity
from harness.cli.worktrees import _worktrees_root
from harness.worktree import WORKTREES_SUBDIR, worktree_path


def test_subdir_is_the_single_source() -> None:
    # The literal layout fact lives in exactly one place and worktree re-exports it.
    assert str(identity.WORKTREES_SUBDIR) == ".worktrees/harness"
    assert WORKTREES_SUBDIR is identity.WORKTREES_SUBDIR


def test_worktree_path_derives_from_subdir() -> None:
    repo = Path("/repo")
    # Non-ULID run_id: worktree's helper must NOT validate (unlike identity's).
    assert worktree_path(repo, "run-1") == repo / identity.WORKTREES_SUBDIR / "run-1"


def test_worktrees_root_derives_from_subdir() -> None:
    repo = Path("/repo")
    assert _worktrees_root(repo) == repo / identity.WORKTREES_SUBDIR


def test_root_and_per_run_path_converge() -> None:
    # A per-run worktree must live directly under the discovery root the
    # `worktrees` CLI walks — the bug class CAL-590 guards against.
    repo = Path("/repo")
    assert worktree_path(repo, "run-1").parent == _worktrees_root(repo)


def test_identity_worktree_dir_uses_the_subdir() -> None:
    run_id = identity.generate_run_id()
    assert identity.worktree_dir(run_id) == identity.WORKTREES_SUBDIR / run_id
