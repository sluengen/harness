"""Doc guard — the proactive context-rollover handoff protocol + its distinction
from death-keyed reclamation are documented in ``commands/harness.md`` (CAL-923).

The marker contract (``reclaim_marker``), the reader (``fetch_handoff_branch``),
and the ``start --resume`` fall-through are pinned by their own unit tests. What
those cannot pin is the *documented protocol* — proposal
``ground-specs-and-context-rollover`` WS-B AC-1 ("a documented trigger + protocol
… composing checkpoint + resume") and AC-3 ("the proactive-handoff vs
death-reclamation distinction is explicit in the marker contract / docs"). This
guard is that check: it fails if the handoff protocol or the distinction is
dropped from the command doc, and it ties the doc's marker phrase back to the
:data:`~harness.reclaim_marker.HANDOFF_MARKER` constant so the two cannot drift.
"""

from __future__ import annotations

from pathlib import Path

from harness.reclaim_marker import HANDOFF_MARKER, RECLAIM_MARKER

REPO_ROOT = Path(__file__).parent.parent.parent
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness" / "run.md"


def _doc() -> str:
    return HARNESS_COMMAND.read_text()


def test_handoff_protocol_composes_the_existing_verbs() -> None:
    """AC-1: the doc names the protocol trigger and the verbs it composes —
    ``harness checkpoint`` then a fresh session's ``harness start --resume`` — with
    no new sentinel verb."""
    doc = _doc()
    assert "context-rollover handoff" in doc.lower(), (
        "commands/harness.md no longer documents the proactive context-rollover "
        "handoff protocol (CAL-923 AC-1)."
    )
    for needle in ("harness checkpoint", "harness start", "--resume"):
        assert needle in doc, (
            f"the handoff protocol must compose the existing verb {needle!r} "
            "(CAL-923 AC-1: no new sentinel verb)."
        )


def test_handoff_doc_marker_matches_the_constant() -> None:
    """AC-1/AC-3 (doc↔code): the doc references the handoff marker by its constant's
    leading phrase, so a rename of ``HANDOFF_MARKER`` that misses the doc is caught.

    The backtick-quoted tail (```harness checkpoint```) is markdown-escaped in the
    doc, so we tie on the marker's backtick-free prefix — enough to bind the doc to
    the constant without asserting on escaping."""
    marker_prefix = HANDOFF_MARKER.split("`")[0].strip()
    assert marker_prefix, "HANDOFF_MARKER has no leading phrase to anchor the doc on."
    assert marker_prefix in _doc(), (
        f"commands/harness.md must reference the handoff marker phrase "
        f"{marker_prefix!r} (from HANDOFF_MARKER) so the documented format cannot "
        "drift from harness.reclaim_marker (CAL-923)."
    )


def test_distinction_from_reclamation_is_explicit() -> None:
    """AC-3: the doc makes the proactive-handoff vs death-reclamation distinction
    explicit — distinct Linear states (In Progress vs Todo + ``reclaimed``) and
    distinct resume readers — the property that keeps the two from colliding."""
    doc = _doc()
    for needle in (
        "In Progress",          # proactive keeps the ticket in-flight …
        "Todo",                 # … reclamation reverts it
        "reclaimed",            # the label only reclamation applies
        "fetch_handoff_branch", # the proactive reader
        "fetch_resume_branch",  # the death-keyed reader
    ):
        assert needle in doc, (
            f"the handoff/reclamation distinction must name {needle!r} in "
            "commands/harness.md (CAL-923 AC-3)."
        )
    # Both marker prefixes appear, so the doc contrasts the two comment forms.
    assert RECLAIM_MARKER.split("`")[0].strip() in doc
    assert HANDOFF_MARKER.split("`")[0].strip() in doc
