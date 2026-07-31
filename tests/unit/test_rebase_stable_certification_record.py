"""#268 — the `rebase-stable-certification` proposal record carries its own retirement.

The proposal spawned three breakdown items in one batch (#266, #267, #268). Two
shipped; the third carried an explicit precondition — *read the measured
`stale_review` rate before building, and close this unbuilt if it is negligible* —
and that precondition fired. The proposal file is where the ticket's own
Precondition section says the number and the decision must be recorded, so this
guards that the record actually carries them rather than the decision surviving
only as a closed issue.

The bar is the one `test_adr_0004_amendment.py` sets for ADR 0004: pin the
load-bearing claims (the measurement, the attribution, the decision, and what
would reverse it), not the prose around them.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = REPO_ROOT / "specs" / "proposals" / "rebase-stable-certification.md"

# The three breakdown items, filed together on 2026-07-30T03:26Z.
SHIPPED_ITEMS = ("#266", "#267")
RETIRED_ITEM = "#268"


def _read() -> str:
    assert PROPOSAL.exists(), (
        "the proposal record must exist at the path #268's Precondition names: "
        f"{PROPOSAL.relative_to(REPO_ROOT)}"
    )
    return PROPOSAL.read_text(encoding="utf-8")


def test_record_ends_in_a_terminal_lifecycle_state() -> None:
    """`templates/proposal.md`: a proposal does not sit half-decided."""
    text = _read()
    match = re.search(r"^status:\s*(\S+)", text, re.MULTILINE)
    assert match is not None, "the record must carry a `status:` field in frontmatter"
    assert match.group(1) in {"shipped", "rejected", "split", "accepted"}, (
        f"status must be a terminal lifecycle state, got {match.group(1)!r}"
    )


def test_record_names_all_three_breakdown_items() -> None:
    """Every item the proposal spawned is accounted for, not just the shipped ones."""
    text = _read()
    for item in (*SHIPPED_ITEMS, RETIRED_ITEM):
        assert item in text, f"the record must name breakdown item {item}"


def test_record_states_the_measured_stale_review_rate() -> None:
    """AC-1: the ticket is closed unbuilt *with that number*."""
    text = _read()
    assert "stale_review" in text, "the record must name the rate it measured"
    assert "zero" in text.lower() or " 0 " in text, (
        "the record must state the measured count, not merely that a measurement happened"
    )
    assert "#263" in text, (
        "the record must name the ticket whose telemetry made the rate readable, so a "
        "reader can tell how wide the instrumented window is"
    )


def test_record_bounds_the_window_the_measurement_covers() -> None:
    """A pre-telemetry era reads as zero refusals, which is not the same as no refusals."""
    text = _read()
    assert re.search(r"\b7\b", text), (
        "the record must state how many close attempts the instrumented window covers — "
        "an unbounded 'zero' overstates the evidence"
    )


def test_record_attributes_every_recent_excess_pass_to_a_removed_cause() -> None:
    """The attribution, not the sample size, is what carries the decision."""
    text = _read()
    for run_ticket in ("#249", "#253", "#269"):
        assert run_ticket in text, (
            f"the record must attribute the excess-pass run on ticket {run_ticket}; "
            "an unattributed count would leave the 'negligible' claim resting on a "
            "one-run sample"
        )


def test_record_states_the_decision_to_close_unbuilt() -> None:
    """The decision itself, in the file the Precondition names."""
    text = _read()
    low = text.lower()
    assert "unbuilt" in low, "the record must state that item 3 was closed unbuilt"
    assert "## decision" in low, (
        "the decision must be its own section, not a remark buried in prose"
    )


def test_record_states_what_would_reverse_the_decision() -> None:
    """A decision made on a measurement must name the measurement that undoes it."""
    text = _read()
    low = text.lower()
    assert "revisit" in low or "reopen" in low or "reverse" in low, (
        "the record must name the condition that would put this work back on the queue — "
        "otherwise a decision taken on thin post-fix evidence becomes permanent by default"
    )


def test_record_notes_the_mechanism_limit_the_design_surfaced() -> None:
    """`--since` serves the merge-resolution route, not a true rebase.

    After a genuine rebase no commit on the branch is the one that passed, so the
    ancestry precondition fails and a full review is paid anyway. That limit is
    half the reason the remaining benefit is negligible, so losing it would leave
    the record resting on the measurement alone.
    """
    text = _read()
    low = text.lower()
    assert "ancestor" in low, (
        "the record must state the ancestry precondition that bounds where --since applies"
    )
    assert "#266" in text, (
        "the record must connect the limit to the change that made merge-not-rebase "
        "the prescribed conflict route"
    )
