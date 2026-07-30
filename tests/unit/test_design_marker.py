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

import pytest

from harness.cli.design_protocol import design_content_hash
from harness.design_marker import (
    DESIGN_MARKER,
    format_design_comment,
    parse_design_comment,
)
from harness.reclaim_marker import (
    HANDOFF_MARKER,
    RECLAIM_MARKER,
    format_handoff_comment,
    format_reclaim_comment,
    parse_handoff_branch,
    parse_preserved_branch,
)
from tests._gitutil import tracked_py_sources

_RUN_ID = "01KYCK0P27AQR6XH74GFDFBQPK"
_DESIGN = "### Data model\n\nNo change.\n\n### Interface / contract\n\nOne verb.\n"
_HASH = "a" * 64
_SHA = "b" * 40
_WHEN = "2026-07-25T12:00:00Z"

#: A design that exercises every recovery hazard at once: markdown headings, a
#: fenced code block, and an embedded ``\n\n---\n\n`` of its own — the separator
#: the reader splits on. A design *about* the design contract looks like this.
_EMBEDDED_SEPARATOR_DESIGN = (
    "### Data model\n\nA `ParsedDesign` tuple.\n\n---\n\n"
    "### Notes\n\n```python\nx = 1\n```\n"
)


def _comment(design: str = _DESIGN, design_hash: str = _HASH) -> str:
    return format_design_comment(
        _RUN_ID,
        design,
        design_hash=design_hash,
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


def test_round_trip_recovers_the_design_byte_identically() -> None:
    """AC-1: the reader's whole reason to exist — the design survives the trip.

    One equality against the original string, over a body carrying headings, a
    code fence, and an embedded separator, so the split rule (first occurrence,
    whole remainder) and the no-strip rule are both under test from the start.
    """
    parsed = parse_design_comment(_comment(design=_EMBEDDED_SEPARATOR_DESIGN))
    assert parsed is not None
    assert parsed.design_markdown == _EMBEDDED_SEPARATOR_DESIGN


def test_round_trip_preserves_a_trailing_newline() -> None:
    """Nothing is stripped — byte-identity is what the caller's hash needs."""
    parsed = parse_design_comment(_comment(design="### Notes\n\nOne line.\n"))
    assert parsed is not None
    assert parsed.design_markdown == "### Notes\n\nOne line.\n"


def test_header_fields_round_trip() -> None:
    """AC-2: the provenance a caller authenticates against, recovered as written."""
    parsed = parse_design_comment(_comment())
    assert parsed is not None
    assert parsed.run_id == _RUN_ID
    assert parsed.design_hash == _HASH
    assert parsed.grounded_sha == _SHA


def test_a_header_missing_its_hash_clause_still_recovers_the_design() -> None:
    """AC-2: header drift costs the provenance, never the design text.

    Each field is independently optional, so a caller decides what to do with an
    unauthenticatable design instead of losing the design along with the clause.
    """
    body = _comment().replace(f" (design_hash `{_HASH}`)", "")
    parsed = parse_design_comment(body)
    assert parsed is not None
    assert parsed.design_markdown == _DESIGN
    assert parsed.design_hash is None
    assert parsed.run_id == _RUN_ID


def test_the_stated_hash_is_reported_unverified() -> None:
    """AC-5: the parser reports the claim; it does not judge it.

    ADR 0008 puts authentication on the *writing* verb — it recomputes the hash
    over the recovered text and refuses a mismatch. Proving the parser hands back
    a hash that demonstrably does not match its body is what documents that
    split, and what fails if anyone later "helpfully" verifies here.
    """
    stated = "0" * 64
    parsed = parse_design_comment(_comment(design_hash=stated))
    assert parsed is not None
    assert parsed.design_hash == stated
    assert design_content_hash(parsed.design_markdown) != stated


_POISONED_DESIGN = "### Notes\n\nThe stated design_hash `deadbeef` is only a claim.\n"


def test_the_design_body_does_not_shadow_a_present_header_clause() -> None:
    """A design legitimately writes about ``design_hash`` — this module's own did."""
    parsed = parse_design_comment(_comment(design=_POISONED_DESIGN))
    assert parsed is not None
    assert parsed.design_hash == _HASH


#: Each provenance field, with the header clause that carries it and a decoy of
#: the same shape planted in the design body. Parametrized over **all three**
#: because the header-slice rule governs all three — a guard covering only
#: ``design_hash`` would be narrower than the rule it enforces, and the other two
#: extractions could silently widen to the whole comment with the suite green.
_PROVENANCE_FIELDS = [
    ("design_hash", f" (design_hash `{_HASH}`)", "design_hash `deadbeef`"),
    ("grounded_sha", f"grounded at `{_SHA}` ", "grounded at `deadbeef`"),
    ("run_id", f"for run `{_RUN_ID}`, ", "for run `01DECOY`"),
]


@pytest.mark.parametrize(("field", "header_clause", "decoy"), _PROVENANCE_FIELDS)
def test_the_design_body_cannot_supply_provenance_the_header_lacks(
    field: str, header_clause: str, decoy: str
) -> None:
    """The header-poisoning case: fields come from the header slice, never the body.

    This is the direction that actually bites, and the one a whole-comment
    ``search`` gets wrong. With the header's clause *present*, a whole-comment
    search still returns it — it matches first — so that arrangement cannot tell
    the two implementations apart. Strip the header's clause and the body's decoy
    becomes the only match: the comment would then sign itself with provenance
    nobody recorded, and a caller would authenticate against a value the design
    supplied. ``None`` is the honest answer, and it is what makes a caller decline
    to adopt and re-design instead.
    """
    design = f"### Notes\n\nThe stated {decoy} is only a claim.\n"
    body = _comment(design=design).replace(header_clause, "")
    parsed = parse_design_comment(body)
    assert parsed is not None
    assert parsed.design_markdown == design
    assert getattr(parsed, field) is None


@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("empty", ""),
        ("plain prose", "Just a human comment about the ticket."),
        ("marker only", DESIGN_MARKER),
        ("truncated before the separator", _comment().split("\n\n---\n\n")[0]),
        ("nothing after the separator", DESIGN_MARKER + " at x.\n\n---\n\n"),
        ("whitespace-only remainder", DESIGN_MARKER + " at x.\n\n---\n\n   \n"),
        ("marker not at the start", "Quoting a design:\n\n" + _comment()),
    ],
)
def test_malformed_comments_parse_to_none_without_raising(label: str, body: str) -> None:
    """AC-4: every ambiguity degrades to ``None``, and nothing raises.

    The parametrization is the "raises nothing" evidence. The last case is the
    prefix gate: a comment that merely *quotes* a design is not a design comment,
    which a substring gate would have accepted.
    """
    assert parse_design_comment(body) is None, label


def test_reclaim_and_handoff_comments_are_not_read_as_designs() -> None:
    """AC-3: the third direction of the non-collision guard.

    Built from the real formatters, not hand-written strings, so a change to
    either sibling contract is caught here rather than drifting past a fixture.
    """
    reclaim = format_reclaim_comment(_RUN_ID, "harness/wip", when=_WHEN)
    handoff = format_handoff_comment(_RUN_ID, "harness/wip", when=_WHEN)
    assert parse_design_comment(reclaim) is None
    assert parse_design_comment(handoff) is None


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
        for path in tracked_py_sources("harness")
        if DESIGN_MARKER in path.read_text(encoding="utf-8")
    )
    assert owners == ["design_marker.py"], (
        f"the design marker literal must live only in harness/design_marker.py, "
        f"found it in: {owners}"
    )
