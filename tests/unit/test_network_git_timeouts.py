"""CAL-1004 — network git calls carry a timeout, and a fired timeout is handled.

The verbs shell out to ``git fetch`` / ``git push`` over the network. Before this
change those calls passed no timeout: a network partition or a hung remote would
hang the verb forever (``run_git`` accepts ``timeout`` but only ``worktrees``
used it). These tests pin two things at every network site:

* **The call passes a timeout.** A monkeypatched ``run_git`` records the
  ``timeout`` kwarg each site hands it; the network op (fetch / push / push
  --delete) must carry :data:`NETWORK_GIT_TIMEOUT_SECONDS`, a value in the
  documented 60–120s band. (Local, non-network git — checkout, merge, prune,
  branch -D — deliberately passes no timeout.)
* **A fired timeout does not leak.** ``run_git`` raises
  :class:`subprocess.TimeoutExpired` on expiry (it never swallows it); each site
  converts that into its own normal failure shape — ``close`` → ``_CloseError``,
  ``checkpoint`` → ``_CheckpointError``, ``start`` fetch → a clean ``None``
  (restart, not error), and best-effort teardown → no raise at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import promotion as promotion_mod
from harness.cli import _git as git_mod
from harness.cli import checkpoint as checkpoint_mod
from harness.cli import close as close_mod
from harness.cli import start as start_mod
from harness.cli._git import NETWORK_GIT_TIMEOUT_SECONDS, teardown_worktree


def _ok(*, stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


def _recorder(
    calls: list[tuple[tuple[str, ...], float | None]],
    *,
    on: dict[str, subprocess.CompletedProcess[str]] | None = None,
):
    """A fake ``run_git`` that records ``(args, timeout)`` and returns a clean CP.

    ``on`` maps a leading-arg keyword (e.g. ``"rev-parse"``) to a specific result;
    everything else returns a zero-exit no-op so a happy path runs to completion.
    """

    def _fake(
        cwd: Path, *args: str, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, timeout))
        if on is not None and args and args[0] in on:
            return on[args[0]]
        return _ok()

    return _fake


# ---------------------------------------------------------------------------
# The default sits in the documented 60–120s band.
# ---------------------------------------------------------------------------


def test_network_timeout_default_in_documented_band() -> None:
    assert 60 <= NETWORK_GIT_TIMEOUT_SECONDS <= 120


# ---------------------------------------------------------------------------
# Each network site passes the timeout.
# ---------------------------------------------------------------------------


def test_checkpoint_push_passes_network_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], float | None]] = []
    monkeypatch.setattr(checkpoint_mod, "run_git", _recorder(calls))

    checkpoint_mod._push_branch(worktree_path=Path("/wt"), branch="harness/x")

    push = [t for a, t in calls if a[:2] == ("push", "origin")]
    assert push == [NETWORK_GIT_TIMEOUT_SECONDS]


def test_start_fetch_passes_network_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], float | None]] = []
    monkeypatch.setattr(
        start_mod,
        "run_git",
        _recorder(calls, on={"rev-parse": _ok(stdout="abc123\n")}),
    )

    sha = start_mod._fetch_origin_branch(Path("/repo"), "harness/x")
    assert sha == "abc123"

    fetch = [t for a, t in calls if a[0] == "fetch"]
    assert fetch == [NETWORK_GIT_TIMEOUT_SECONDS]
    # The local FETCH_HEAD resolve is not a network op — no timeout on it.
    rev = [t for a, t in calls if a[0] == "rev-parse"]
    assert rev == [None]


def test_promote_fetch_origin_passes_network_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``harness.promotion.fetch_origin`` is a network site (CAL-1004): its
    ``git fetch origin`` carries the network timeout."""
    calls: list[tuple[tuple[str, ...], float | None]] = []
    monkeypatch.setattr(promotion_mod, "run_git", _recorder(calls))

    promotion_mod.fetch_origin(Path("/repo"))

    fetch = [t for a, t in calls if a[0] == "fetch"]
    assert fetch == [NETWORK_GIT_TIMEOUT_SECONDS]


def test_close_fetch_and_push_pass_network_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], float | None]] = []
    monkeypatch.setattr(close_mod, "run_git", _recorder(calls))

    close_mod._merge_and_push(
        repo_root=Path("/repo"), base_branch="dev", worktree_branch="harness/x"
    )

    fetch = [t for a, t in calls if a[0] == "fetch"]
    push = [t for a, t in calls if a[:2] == ("push", "origin")]
    assert fetch == [NETWORK_GIT_TIMEOUT_SECONDS]
    assert push == [NETWORK_GIT_TIMEOUT_SECONDS]
    # Local git in the same flow (checkout, the two merges) carries no timeout.
    local = [t for a, t in calls if a[0] in {"checkout", "merge"}]
    assert local and all(t is None for t in local)


def test_teardown_push_delete_passes_network_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[tuple[str, ...], float | None]] = []
    monkeypatch.setattr(git_mod, "run_git", _recorder(calls))

    # worktree_path outside the .worktrees area → removal skipped; the branch and
    # remote-delete steps still run, and the remote delete is the network op.
    teardown_worktree(
        tmp_path / "repo",
        worktree_path=tmp_path / "outside",
        branch="harness/x",
        delete_remote=True,
    )

    delete = [t for a, t in calls if a[:3] == ("push", "origin", "--delete")]
    assert delete == [NETWORK_GIT_TIMEOUT_SECONDS]


# ---------------------------------------------------------------------------
# A fired timeout is converted into the site's normal failure shape.
# ---------------------------------------------------------------------------


def _raise_timeout_on(keyword: str):
    """A fake ``run_git`` that raises ``TimeoutExpired`` on the named git op."""

    def _fake(
        cwd: Path, *args: str, timeout: float | None = None
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == keyword:
            raise subprocess.TimeoutExpired(["git", *args], timeout or 0)
        if args and args[0] == "rev-parse":
            return _ok(stdout="abc123\n")
        return _ok()

    return _fake


def test_checkpoint_push_timeout_raises_checkpoint_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checkpoint_mod, "run_git", _raise_timeout_on("push"))
    with pytest.raises(checkpoint_mod._CheckpointError):
        checkpoint_mod._push_branch(worktree_path=Path("/wt"), branch="harness/x")


def test_start_fetch_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fetch that times out is a clean restart signal, not a raised error."""
    monkeypatch.setattr(start_mod, "run_git", _raise_timeout_on("fetch"))
    assert start_mod._fetch_origin_branch(Path("/repo"), "harness/x") is None


def test_promote_fetch_origin_timeout_raises_mechanics_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fetch that times out is surfaced as a ``PromotionMechanicsError`` — the
    promotion cannot proceed on unreachable refs (not a silent restart)."""
    monkeypatch.setattr(promotion_mod, "run_git", _raise_timeout_on("fetch"))
    with pytest.raises(promotion_mod.PromotionMechanicsError) as exc_info:
        promotion_mod.fetch_origin(Path("/repo"))
    assert exc_info.value.reason == "fetch_failed"


def test_close_fetch_timeout_raises_close_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(close_mod, "run_git", _raise_timeout_on("fetch"))
    with pytest.raises(close_mod._CloseError):
        close_mod._merge_and_push(
            repo_root=Path("/repo"), base_branch="dev", worktree_branch="harness/x"
        )


def test_teardown_push_delete_timeout_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Teardown is best-effort — a timed-out remote delete must not raise (CAL-767)."""
    monkeypatch.setattr(git_mod, "run_git", _raise_timeout_on("push"))
    # Must return normally despite the push --delete timing out.
    teardown_worktree(
        tmp_path / "repo",
        worktree_path=tmp_path / "outside",
        branch="harness/x",
        delete_remote=True,
    )
