"""Tests for the design-comment contract — #211 (ADR 0007).

The ``design`` verb posts its artifact — the change spec's Design section — to
the ticket as a **marked** comment, so a later reader (human or tooling) can
pick it out among the ticket's other comments. AC-4: that marker is
single-sourced in a marker module and covered by tests, the
:mod:`harness.reclaim_marker` precedent.

The non-collision tests matter for the same reason they do for reclaim vs
handoff: three marked-comment protocols now share one ticket's comment stream,
and each reader must be blind to the other two.
"""

from __future__ import annotations

from pathlib import Path

from harness.design_marker import DESIGN_MARKER, format_design_comment
from harness.reclaim_marker import (
    HANDOFF_MARKER,
    RECLAIM_MARKER,
    parse_handoff_branch,
    parse_preserved_branch,
)

_RUN_ID = "01KYCK0P27AQR6XH74GFDFBQPK"
_DESIGN = "### Data model\n\nNo change.\n\n### Interface / contract\n\nOne verb.\n"
_HASH = "a" * 64
_SHA = "b" * 40
_WHEN = "2026-07-25T12:00:00Z"


def _comment() -> str:
    return format_design_comment(
        _RUN_ID,
        _DESIGN,
        design_hash=_HASH,
        grounded_sha=_SHA,
        when=_WHEN,
    )


def test_comment_opens_with_the_marker() -> None:
    """The marker is the opening phrase, so a reader keys on the prefix."""
    assert _comment().startswith(DESIGN_MARKER)


def test_comment_carries_the_run_id_hash_and_grounded_sha() -> None:
    """The provenance a ledger reader needs to tie the comment to its event."""
    body = _comment()
    assert _RUN_ID in body
    assert _HASH in body
    assert _SHA in body
    assert _WHEN in body


def test_comment_carries_the_design_verbatim() -> None:
    """The design itself is the artifact — it is embedded, never summarised."""
    assert _DESIGN in _comment()


def test_marker_is_distinct_from_the_reclaim_and_handoff_markers() -> None:
    """Three marked-comment protocols, three distinct keys (the CAL-923 rule)."""
    assert DESIGN_MARKER != RECLAIM_MARKER
    assert DESIGN_MARKER != HANDOFF_MARKER
    assert RECLAIM_MARKER not in DESIGN_MARKER
    assert HANDOFF_MARKER not in DESIGN_MARKER


def test_design_comment_is_not_read_as_a_reclaim_or_handoff() -> None:
    """A design comment must never yield a resume branch to either reader.

    ``start --resume`` walks a ticket's comments; a design comment that parsed
    as a reclaim/handoff would resume a run from a ref that was never pushed.
    """
    body = _comment()
    assert parse_preserved_branch(body) is None
    assert parse_handoff_branch(body) is None


def test_marker_literal_is_single_sourced() -> None:
    """AC-4: the marker string appears in exactly one production module.

    The reclaim-marker precedent is a *module* that owns the contract; a second
    inlined copy of the phrase in the verb would let writer and reader drift.
    """
    package = Path(__file__).resolve().parents[2] / "harness"
    owners = sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if DESIGN_MARKER in path.read_text(encoding="utf-8")
    )
    assert owners == ["design_marker.py"], (
        f"the design marker literal must live only in harness/design_marker.py, "
        f"found it in: {owners}"
    )
