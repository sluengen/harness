"""#243 — ADR 0004 is amended to narrow its "guard, not generator" scope.

`scripts/build_design_tokens.py` (#242) generates `docs/index.html`'s `:root`
block from `design/03-tokens/tokens.json`, and `scripts/verify.sh` drift-checks
it (#243) — the generator ADR 0004 rejected for the page as a whole. This
guards that the ADR's amendment records the narrowing honestly: what changed,
the generated-vs-narrative line, that it narrows rather than reverses the
decision, and the accepted proposal it traces to.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "specs" / "decisions" / "0004-repo-guide-drift-guard.md"
PROPOSAL = REPO_ROOT / "specs" / "proposals" / "design-system-scaffold.md"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def test_amendment_section_present() -> None:
    """ADR 0004 carries an Amendment section naming #243."""
    text = _read(ADR)
    assert "## Amendment" in text, "ADR 0004 must carry an '## Amendment' section"
    assert "#243" in text, "the amendment must name the ticket that narrowed the ADR"


def test_amendment_states_generated_vs_narrative_line() -> None:
    """The amendment draws the mechanical-vs-narrative line the narrowing rests on."""
    text = _read(ADR)
    amendment = text[text.index("## Amendment") :]
    low = amendment.lower()
    assert "generat" in low, "amendment must describe what is now generated"
    assert "narrative" in low or "prose" in low, (
        "amendment must contrast generated content against narrative/prose content"
    )
    assert "mechanical" in low, (
        "amendment must name the token block as mechanical content, distinct from "
        "the narrative content the original decision reasoned about"
    )


def test_amendment_frames_as_narrowing_not_reversal() -> None:
    """The amendment says explicitly this narrows the decision, not overturns it."""
    text = _read(ADR)
    amendment = text[text.index("## Amendment") :].lower()
    assert "narrow" in amendment, (
        "amendment must state this narrows ADR 0004's scope rather than replacing it"
    )


def test_amendment_cites_the_accepted_proposal() -> None:
    """The amendment traces its source to the accepted proposal's decision block."""
    text = _read(ADR)
    amendment = text[text.index("## Amendment") :]
    assert "design-system-scaffold" in amendment, (
        "amendment must cite specs/proposals/design-system-scaffold.md as its source"
    )
    assert PROPOSAL.exists(), "the cited proposal must exist"


def test_guidance_catalog_guard_still_named_unchanged() -> None:
    """The amendment is explicit that the guidance-catalog guard is untouched."""
    text = _read(ADR)
    amendment = text[text.index("## Amendment") :]
    assert "check_landing_page_guidance.py" in amendment, (
        "amendment must confirm the existing guidance-catalog guard still runs"
    )
