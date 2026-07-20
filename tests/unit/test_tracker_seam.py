"""The tracker seam — one factory, backend-agnostic verbs (CAL-1197).

Split from CAL-1105: extract the interface the verbs already use so a second
backend (GitHub) can slot in without touching ``start``/``review``/``close``/
``defer``/``reclaim``. This pins the seam contract:

* ``LinearClient`` is *one* structural implementation of the ``Tracker`` seam
  (the conformance pin — AC-2, the Linear path is untouched).
* :func:`tracker_client` resolves the backend from CONTEXT.md's ``tracker:`` key
  (via :mod:`harness.layers`) and returns the right implementation — a
  ``LinearClient`` for ``linear``, ``None`` for ``none`` (tracker-less).
* An unimplemented backend (``github``) **raises** ``UnsupportedTrackerError``
  rather than silently degrading to a tracker-less run — the wiring point the
  CAL-1105 follow-up fills in.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from harness.linear import LinearClient
from harness.tracker import Tracker, UnsupportedTrackerError, tracker_client


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


def test_tracker_client_raises_unsupported_for_tracker_github(tmp_path: Path) -> None:
    _context(tmp_path, "tracker: github\n")
    with pytest.raises(UnsupportedTrackerError, match="github"):
        tracker_client(tmp_path)
