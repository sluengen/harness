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
    WorkspaceNotAllowed,
    allowed_roots,
    resolve_repo_root,
    resolve_within_allowlist,
)

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
    repo = root / "repo"
    repo.mkdir(parents=True)
    env = {WORKSPACE_ROOTS_ENV: str(root)}
    assert resolve_repo_root(repo, env) == repo.resolve()


def test_resolve_repo_root_fails_closed_when_unset(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(repo, {})


def test_resolve_repo_root_rejects_outside_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    env = {WORKSPACE_ROOTS_ENV: str(root)}
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(outside, env)
