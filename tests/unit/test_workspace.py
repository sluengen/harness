"""Unit tests for :mod:`harness.workspace` — the ``HARNESS_WORKSPACE_ROOTS``
allowlist primitive (CAL-584).

These cover the helper in isolation: env parsing, realpath normalization, the
path-boundary descendant check, and fail-closed behaviour on an unset/empty
allowlist. The CLI wiring (exit code 2) is covered separately in
``test_cli_workspace_gate.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.workspace import (
    WORKSPACE_ROOTS_ENV,
    NotAGitTopLevel,
    WorkspaceNotAllowed,
    allowed_roots,
    resolve_repo_root,
    resolve_within_allowlist,
)
from tests._gitutil import init_repo

# ---------------------------------------------------------------------------
# resolve_within_allowlist — the path-boundary check
# ---------------------------------------------------------------------------


def test_path_under_allowed_root_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "work"
    repo = root / "repo"
    repo.mkdir(parents=True)
    assert resolve_within_allowlist(repo, [root.resolve()]) == repo.resolve()


def test_path_equal_to_root_is_accepted(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    assert resolve_within_allowlist(root, [root.resolve()]) == root.resolve()


def test_path_outside_all_roots_is_rejected_and_names_path(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(WorkspaceNotAllowed) as excinfo:
        resolve_within_allowlist(outside, [root.resolve()])
    # The message must name the rejected path (AC: "naming the path").
    assert str(outside.resolve()) in str(excinfo.value)


def test_dotdot_traversal_escaping_roots_is_rejected(tmp_path: Path) -> None:
    # ``work/repo/../..`` climbs out of the allowed root; a naive string-prefix
    # check would wrongly accept it. realpath normalization defeats the escape.
    work = tmp_path / "work"
    repo = work / "repo"
    repo.mkdir(parents=True)
    escaping = repo / ".." / ".."
    with pytest.raises(WorkspaceNotAllowed):
        resolve_within_allowlist(escaping, [work.resolve()])


def test_symlink_resolving_outside_roots_is_rejected(tmp_path: Path) -> None:
    allowed = tmp_path / "work"
    allowed.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    link = allowed / "escape"
    link.symlink_to(secret)
    with pytest.raises(WorkspaceNotAllowed):
        resolve_within_allowlist(link, [allowed.resolve()])


def test_string_prefix_sibling_is_rejected(tmp_path: Path) -> None:
    # ``/work/repo-evil`` shares a string prefix with root ``/work/repo`` but is
    # not a path-segment descendant — it must be rejected (boundary test).
    root = tmp_path / "repo"
    root.mkdir()
    sibling = tmp_path / "repo-evil"
    sibling.mkdir()
    with pytest.raises(WorkspaceNotAllowed):
        resolve_within_allowlist(sibling, [root.resolve()])


def test_empty_roots_rejects_all(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceNotAllowed):
        resolve_within_allowlist(tmp_path, [])


# ---------------------------------------------------------------------------
# allowed_roots — env parsing
# ---------------------------------------------------------------------------


def test_allowed_roots_unset_is_empty() -> None:
    assert allowed_roots({}) == []


def test_allowed_roots_empty_string_is_empty() -> None:
    assert allowed_roots({WORKSPACE_ROOTS_ENV: ""}) == []


def test_allowed_roots_whitespace_only_is_empty() -> None:
    assert allowed_roots({WORKSPACE_ROOTS_ENV: "  :  : "}) == []


def test_allowed_roots_splits_colons_and_strips_empty_segments(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    env = {WORKSPACE_ROOTS_ENV: f"{a}::{b}:"}
    assert allowed_roots(env) == [a.resolve(), b.resolve()]


def test_allowed_roots_realpath_normalizes_each(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert allowed_roots({WORKSPACE_ROOTS_ENV: str(link)}) == [real.resolve()]


# ---------------------------------------------------------------------------
# resolve_repo_root — the env-driven verb entry point
# ---------------------------------------------------------------------------


def test_resolve_repo_root_accepts_under_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "work"
    repo = init_repo(root / "repo")
    env = {WORKSPACE_ROOTS_ENV: str(root)}
    assert resolve_repo_root(repo, env) == repo.resolve()


def test_resolve_repo_root_fails_closed_when_unset(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(repo, {})


def test_resolve_repo_root_rejects_outside_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    outside = init_repo(tmp_path / "outside")
    env = {WORKSPACE_ROOTS_ENV: str(root)}
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(outside, env)


# ---------------------------------------------------------------------------
# resolve_repo_root — the git-top-level check (#214)
#
# The allowlist alone accepted *any* resolvable path, so a verb invoked one
# directory too deep (``<repo>/harness/`` — this repo's package dir shares the
# repo's name) silently planted its worktree, branch, and ledger rows under the
# wrong root instead of refusing. These pin the narrowing: inside the allowlist
# is necessary but no longer sufficient — the candidate must be a repo root.
# ---------------------------------------------------------------------------


def test_resolve_repo_root_rejects_a_subdirectory_of_a_real_repo(
    tmp_path: Path,
) -> None:
    """The reported bug: ``--repo <repo>/harness`` must refuse, not silently pass.

    The subdirectory resolves, and it is squarely *inside* the allowlist — the
    allowlist check cannot catch it. Only the top-level check can.
    """
    repo = init_repo(tmp_path / "repo")
    package_dir = repo / "harness"
    package_dir.mkdir()
    env = {WORKSPACE_ROOTS_ENV: str(tmp_path)}

    with pytest.raises(NotAGitTopLevel) as excinfo:
        resolve_repo_root(package_dir, env)

    # The refusal names the rejected path, so the operator can see which
    # directory they were standing in.
    assert str(package_dir.resolve()) in str(excinfo.value)


def test_resolve_repo_root_rejects_a_directory_that_is_not_a_repo(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    env = {WORKSPACE_ROOTS_ENV: str(tmp_path)}
    with pytest.raises(NotAGitTopLevel):
        resolve_repo_root(plain, env)


def test_resolve_repo_root_accepts_a_linked_worktree_whose_git_is_a_file(
    tmp_path: Path,
) -> None:
    """A ``git worktree add`` root carries ``.git`` as a *file*, and must pass.

    Load-bearing, not academic: ``checkpoint`` / ``review`` / ``close`` are
    routinely invoked with ``--repo`` pointing at a run's worktree (#179), and
    ``commands/harness.md`` Step 1 tells the orchestrator to ``cd`` into it. A
    check written as ``.is_dir()`` would refuse every in-flight run.
    """
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
    env = {WORKSPACE_ROOTS_ENV: str(tmp_path)}

    assert resolve_repo_root(worktree, env) == worktree.resolve()


def test_resolve_repo_root_reports_the_allowlist_refusal_first(
    tmp_path: Path,
) -> None:
    """Allowlist precedence: the security boundary is checked before validity.

    A path that is *both* outside the roots and not a repo keeps reporting the
    allowlist refusal it reported before this change — the git check only ever
    narrows what the allowlist already admitted.
    """
    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    env = {WORKSPACE_ROOTS_ENV: str(root)}

    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(outside, env)


def test_not_a_git_top_level_is_not_a_workspace_not_allowed(tmp_path: Path) -> None:
    """The two refusals stay distinct types, so neither prints the other's story.

    ``WorkspaceNotAllowed`` means *outside the security boundary*;
    ``NotAGitTopLevel`` means *inside it, but not a repo root*. Collapsing them
    would have a verb tell an operator standing in ``<repo>/harness`` that their
    path is "outside the allowed workspace roots", which it is not.
    """
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    env = {WORKSPACE_ROOTS_ENV: str(tmp_path)}

    with pytest.raises(NotAGitTopLevel) as excinfo:
        resolve_repo_root(plain, env)

    assert not isinstance(excinfo.value, WorkspaceNotAllowed)
    # ...and the message does not borrow the allowlist's vocabulary.
    assert "outside the allowed workspace roots" not in str(excinfo.value)


def test_resolve_within_allowlist_does_not_apply_the_git_check(
    tmp_path: Path,
) -> None:
    """The pure boundary primitive keeps its single concern.

    ``resolve_within_allowlist`` answers *is this path inside the roots* and
    nothing else; the git check belongs to ``resolve_repo_root``, the verbs'
    entry point. Pinned so a later edit cannot quietly fold git into the
    boundary check and break callers that legitimately pass non-repo paths.
    """
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert resolve_within_allowlist(plain, [tmp_path.resolve()]) == plain.resolve()
