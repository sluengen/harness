"""The tracker seam — one factory, backend-agnostic verbs (CAL-1197).

Split from CAL-1105: extract the interface the verbs already use so a second
backend (GitHub) can slot in without touching ``start``/``review``/``close``/
``defer``/``reclaim``. This pins the seam contract:

* ``LinearClient`` is *one* structural implementation of the ``Tracker`` seam
  (the conformance pin — AC-2, the Linear path is untouched).
* :func:`tracker_client` resolves the backend from CONTEXT.md's ``tracker:`` key
  (via :mod:`harness.layers`) and returns the right implementation — a
  ``LinearClient`` for ``linear``, a ``GitHubClient`` for ``github``, ``None`` for
  ``none`` (tracker-less).
* ``github`` with a complete ``github:`` config block resolves a ``GitHubClient``
  (CAL-1105); a ``tracker: github`` with **no** config block is a misconfiguration
  that **raises** ``GitHubConfigError`` rather than silently degrading to a
  tracker-less run.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from harness.github import GitHubClient, GitHubConfigError
from harness.linear import LinearClient
from harness.tracker import Tracker, tracker_client


def _context(repo_root: Path, body: str) -> None:
    (repo_root / "CONTEXT.md").write_text(body)


def test_linear_client_satisfies_the_tracker_protocol() -> None:
    """``LinearClient`` structurally *is* a ``Tracker`` — the conformance pin.

    A missing or renamed seam method on ``LinearClient`` breaks this, catching a
    drift between the interface the verbs depend on and its Linear impl.
    """
    client = LinearClient(api_key="test-key")
    assert isinstance(client, Tracker)


def test_tracker_client_returns_a_linear_client_for_tracker_linear(
    tmp_path: Path,
) -> None:
    _context(tmp_path, "repo:\n  linear: CAL\ntracker: linear\n")
    with patch("harness.tracker.linear_api_key", return_value="test-key"):
        client = tracker_client(tmp_path)
    assert isinstance(client, LinearClient)


def test_tracker_client_returns_none_for_tracker_none(tmp_path: Path) -> None:
    _context(tmp_path, "tracker: none\n")
    # A tracker-less repo has no credentials; the factory must return ``None``
    # *without* reaching for a key (which would raise for a real none-repo).
    with patch(
        "harness.tracker.linear_api_key",
        side_effect=AssertionError("fetched a key for a tracker-less repo"),
    ):
        assert tracker_client(tmp_path) is None


def test_tracker_client_threads_repo_linear_team_into_the_client(
    tmp_path: Path,
) -> None:
    """The factory reads ``repo.linear`` and hands it to the LinearClient, so the
    unscoped reclaim sweep (#174) can filter by team when given no project. The seam
    stays clean — the team is client config, not a per-call argument."""
    _context(tmp_path, "repo:\n  linear: CAL\ntracker: linear\n")
    with patch("harness.tracker.linear_api_key", return_value="test-key"):
        client = tracker_client(tmp_path)
    assert isinstance(client, LinearClient)
    assert client._team == "CAL"


def test_reclaimable_scope_is_nullable_across_the_seam() -> None:
    """AC-4 (#174): the seam and both impls accept ``project: str | None`` — a
    nullable scope pinned by signature, so a backend narrowing it back to a
    mandatory ``str`` is caught here rather than at a consumer."""
    import inspect

    for obj in (Tracker, LinearClient, GitHubClient):
        sig = inspect.signature(obj.fetch_reclaimable_issues)
        assert sig.parameters["project"].annotation == "str | None", obj.__name__


def test_tracker_client_returns_a_github_client_for_configured_github(
    tmp_path: Path,
) -> None:
    """A ``tracker: github`` with a complete ``github:`` block resolves a GitHubClient."""
    _context(
        tmp_path,
        "tracker: github\ngithub:\n  repo: acme/widgets\n  project: acme/7\n",
    )
    with patch("harness.tracker.github_token", return_value="gh-token"):
        client = tracker_client(tmp_path)
    assert isinstance(client, GitHubClient)
    assert isinstance(client, Tracker)


def test_tracker_client_raises_config_error_for_github_without_block(
    tmp_path: Path,
) -> None:
    """``tracker: github`` with no ``github:`` block is a misconfiguration — fail loud."""
    _context(tmp_path, "tracker: github\n")
    with pytest.raises(GitHubConfigError, match="github"):
        tracker_client(tmp_path)
