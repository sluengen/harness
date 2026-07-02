"""Round-trip guard for the reclaim-comment contract (CAL-739).

``harness reclaim`` (CAL-735) posts a comment naming the preserved
(checkpoint-pushed) branch; ``harness start --resume`` (CAL-739) reads that
comment back to continue the dead run from its branch. The comment format has
**two parties**, so it lives in one place — :mod:`harness.reclaim_marker` —
rather than as a private helper the reader copies. These tests pin
``format_reclaim_comment`` ↔ ``parse_preserved_branch`` so the reader can never
silently drift from the writer: a wording change that broke the parse would fail
here, not in production (where it would degrade resume to a silent clean restart).

The same module now carries the **proactive context-rollover handoff** contract
(CAL-923): a *sibling* marker for the alive-but-near-limit case that keeps the
ticket In Progress, distinct from death-keyed reclamation. Its tests pin the same
round-trip guarantee **and** the non-collision — a handoff comment is never read
as a reclaim comment, and vice versa — the property the two protocols rely on to
not step on each other's resume resolution.
"""

from __future__ import annotations

from harness.reclaim_marker import (
    HANDOFF_MARKER,
    NO_BRANCH_SENTINEL,
    RECLAIM_LABEL,
    RECLAIM_MARKER,
    format_handoff_comment,
    format_reclaim_comment,
    parse_handoff_branch,
    parse_preserved_branch,
)


def test_round_trip_recovers_the_branch() -> None:
    """A comment built for a real branch parses back to exactly that branch."""
    body = format_reclaim_comment("01JRUN", "harness/01JRUN", when="2026-06-16T00:00:00Z")
    assert parse_preserved_branch(body) == "harness/01JRUN"


def test_round_trip_no_branch_parses_to_none() -> None:
    """A reclaim with no durable WIP names the sentinel, which parses to None —
    the no-resumable-branch signal that degrades to a clean restart."""
    body = format_reclaim_comment("01JRUN", None, when="2026-06-16T00:00:00Z")
    assert NO_BRANCH_SENTINEL in body
    assert parse_preserved_branch(body) is None


def test_comment_carries_the_marker_and_label() -> None:
    """The body names the reclaim marker (so the reader can identify a reclaim
    comment) and the ``reclaimed`` label (the structured re-pick signal)."""
    body = format_reclaim_comment(None, "harness/01J", when="2026-06-16T00:00:00Z")
    assert RECLAIM_MARKER in body
    assert RECLAIM_LABEL in body


def test_non_reclaim_comment_parses_to_none() -> None:
    """An unrelated comment that happens to mention a branch is not parsed — the
    reader keys on the reclaim marker, so it never picks up a stray ref."""
    assert parse_preserved_branch("Just a normal comment about `harness/foo`.") is None


def test_parse_ignores_a_marker_without_a_preserved_clause() -> None:
    """A reclaim-marked comment missing the preserved-branch clause yields None
    rather than raising — every non-branch case degrades safely."""
    assert parse_preserved_branch(f"{RECLAIM_MARKER} at 2026-06-16T00:00:00Z.") is None


def test_label_value_is_stable() -> None:
    """The label literal both parties key on is exactly ``reclaimed`` (CAL-735 D1)."""
    assert RECLAIM_LABEL == "reclaimed"


# ---------------------------------------------------------------------------
# Proactive context-rollover handoff — the sibling marker (CAL-923)
# ---------------------------------------------------------------------------


def test_handoff_round_trip_recovers_the_branch() -> None:
    """A handoff comment built for a real branch parses back to exactly it —
    the read side ``harness start --resume`` uses to continue the same ticket."""
    body = format_handoff_comment("01JRUN", "harness/01JRUN", when="2026-07-02T00:00:00Z")
    assert parse_handoff_branch(body) == "harness/01JRUN"


def test_handoff_no_branch_parses_to_none() -> None:
    """A handoff with no durable WIP names the sentinel → parses to None, the
    same clean-restart signal as reclaim (a handoff should always checkpoint
    first, but the contract degrades safely if it did not)."""
    body = format_handoff_comment("01JRUN", None, when="2026-07-02T00:00:00Z")
    assert NO_BRANCH_SENTINEL in body
    assert parse_handoff_branch(body) is None


def test_handoff_comment_carries_marker_and_stays_in_progress() -> None:
    """The handoff body names the handoff marker (the reader keys on it) and says
    the ticket stays In Progress — the visible signal it is NOT a reclamation."""
    body = format_handoff_comment("01J", "harness/01J", when="2026-07-02T00:00:00Z")
    assert HANDOFF_MARKER in body
    assert "In Progress" in body


def test_handoff_marker_is_distinct_from_reclaim_marker() -> None:
    """The two marker strings differ — the structural basis for non-collision:
    a reader keying on one can never match a comment written for the other."""
    assert HANDOFF_MARKER != RECLAIM_MARKER
    assert RECLAIM_MARKER not in HANDOFF_MARKER
    assert HANDOFF_MARKER not in RECLAIM_MARKER


def test_reclaim_comment_is_not_read_as_handoff() -> None:
    """AC-3 (non-collision): a death-keyed reclaim comment is not parsed by the
    handoff reader — the proactive path never picks up a reclamation's branch."""
    body = format_reclaim_comment("R1", "harness/reclaimed", when="2026-07-02T00:00:00Z")
    assert parse_handoff_branch(body) is None


def test_handoff_comment_is_not_read_as_reclaim() -> None:
    """AC-3 (non-collision): a proactive handoff comment is not parsed by the
    reclaim reader — reclamation never resumes from a handoff's branch, and a
    handoff comment carries no ``reclaimed`` label claim."""
    body = format_handoff_comment("H1", "harness/handoff", when="2026-07-02T00:00:00Z")
    assert parse_preserved_branch(body) is None
    assert RECLAIM_LABEL not in body
