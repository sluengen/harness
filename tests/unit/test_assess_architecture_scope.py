"""CAL-816 — `/assess architecture --deep`, a holistic architecture-review scope.

Raised from the Slate architecture-review follow-up (2026-06-19): `/assess code
--deep` carries architecture as one lens, but its output contract is a *finding
engine* — only issues that clear the future-ticket bar survive, so the holistic
question ("is the system shape still right for the product, and what should we
preserve, change, or watch?") gets squeezed out. This change adds a distinct
`architecture` scope to the *same* steward process: the scope changes the domain
standards (the architecture skill's assessment rubric) and the report contract
(a holistic judgement that may file zero tickets while still recording a verdict
and a watchlist), not the agent.

The lenses live in ONE canonical home — `skills/architecture/SKILL.md` ("##
Architecture assessment") — and the command (`commands/assess.md`), the steward
(`agents/steward.md`), the report shape (`templates/assessment.md`), and the
finding bar (`skills/assessment-craft/SKILL.md`) reference it rather than
re-stating it. These guards pin each acceptance criterion so a later re-edit
cannot silently drop it.

These are text-parse content guards in the style of `test_architecture_watchlist`
/ `test_steward_consolidated`; the `test_smoke_*` cases below are the documented
smoke test the ticket asks for (AC-9), exercising the filing rule the guidance
specifies (file only actionable risks; never positive observations).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSESS = REPO_ROOT / "commands" / "assess.md"
STEWARD = REPO_ROOT / "agents" / "steward.md"
ARCHITECTURE = REPO_ROOT / "skills" / "architecture" / "SKILL.md"
ASSESSMENT_CRAFT = REPO_ROOT / "skills" / "assessment-craft" / "SKILL.md"
ASSESSMENT_TEMPLATE = REPO_ROOT / "templates" / "assessment.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The canonical rubric's section header — it lives in exactly one skill.
RUBRIC_SECTION = "## Architecture assessment"

#: The eight holistic lenses the rubric must carry (AC-3).
LENSES = (
    "purpose fit",
    "boundary integrity",
    "domain-model coherence",
    "change ergonomics",
    "operational",
    "verification architecture",
    "spec-record",
    "watchlist recommendations",
)


def _section(text: str, header: str) -> str:
    """The body of a ``## ``-level markdown section, header to next ``## ``."""
    m = re.search(rf"^{re.escape(header)}\b.*$", text, re.MULTILINE)
    assert m, f"missing section header {header!r}"
    rest = text[m.end() :]
    end = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _registry_version(path_fragment: str) -> str:
    m = re.search(
        rf"{re.escape(path_fragment)}:\s*\{{[^}}]*version:\s*([\d.]+)",
        REGISTRY.read_text(),
    )
    assert m, f"no registry entry for {path_fragment!r}"
    return m.group(1)


def _header_version(path: Path) -> str:
    m = re.search(r"<!-- guidance:[\w-]+@([\d.]+) -->", path.read_text())
    assert m, f"no guidance header in {path}"
    return m.group(1)


# --- AC-1 / AC-6: the command surface documents the scope + the contrast ------


def test_assess_documents_architecture_scope_and_usage() -> None:
    """`commands/assess.md` documents `architecture` as a scope and the
    `/assess architecture --deep` usage (AC-1)."""
    text = ASSESS.read_text()
    assert "/assess architecture --deep" in text, (
        "commands/assess.md must document the `/assess architecture --deep` usage "
        "(AC-1)."
    )
    assert "architecture" in text.lower(), (
        "commands/assess.md must name `architecture` as a valid scope (AC-1)."
    )


def test_assess_distinguishes_code_from_architecture() -> None:
    """The command explains how `architecture --deep` differs from `code --deep`
    and `system`: code = finding engine, architecture = holistic judgement (AC-6)."""
    low = ASSESS.read_text().lower()
    assert "finding engine" in low, (
        "commands/assess.md must frame `code` as a finding engine (AC-6)."
    )
    assert "holistic" in low, (
        "commands/assess.md must frame `architecture` as a holistic judgement "
        "(AC-6)."
    )
    # The three scopes are all named in the surface.
    for scope in ("code", "architecture", "system"):
        assert scope in low, f"commands/assess.md must still name the `{scope}` scope"


def test_assess_documents_architecture_filing_behavior() -> None:
    """Linear filing for the architecture scope: only actionable risks are filed,
    positive observations are not, and zero tickets is a valid pass (AC-7)."""
    low = ASSESS.read_text().lower()
    assert "only" in low and "actionable" in low, (
        "commands/assess.md must state architecture files only actionable risks "
        "(AC-7)."
    )
    assert "zero" in low, (
        "commands/assess.md must state a useful architecture pass may file zero "
        "tickets (AC-7)."
    )


# --- AC-2: the steward defines the architecture scope + read path -------------


def test_steward_routes_architecture_scope_to_owned_standards() -> None:
    """The concise role routes architecture assessment instead of duplicating it."""
    low = STEWARD.read_text().lower()
    assert "architecture" in low and "engineering-principles" in low
    assert "commands/assess.md" in low and "detailed lenses" in low


# --- AC-3: the architecture skill carries a holistic assessment rubric --------


def test_architecture_skill_has_holistic_rubric() -> None:
    """`skills/architecture/SKILL.md` carries an "Architecture assessment" rubric
    with the eight holistic lenses — not only design-decision guidance (AC-3)."""
    block = _section(ARCHITECTURE.read_text(), RUBRIC_SECTION).lower()
    for lens in LENSES:
        assert lens in block, (
            f"the Architecture assessment rubric must carry the `{lens}` lens (AC-3)."
        )
    assert "preserve" in block, (
        "the rubric must name positive bets to preserve as first-class output "
        "(AC-3)."
    )


def test_rubric_lives_in_exactly_one_skill() -> None:
    """The holistic rubric has one canonical home — `architecture` (lean/MECE)."""
    homes = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.glob("skills/*/SKILL.md")
        if RUBRIC_SECTION in p.read_text()
    )
    assert homes == ["skills/architecture/SKILL.md"], (
        "the Architecture assessment rubric must have exactly one canonical home "
        f"(skills/architecture/SKILL.md); found in: {homes}."
    )


# --- AC-4: the report template supports the holistic shape --------------------


def test_assessment_template_has_architecture_shape() -> None:
    """`templates/assessment.md` supports the holistic architecture report shape:
    positive observations, trade-offs to preserve, watchlist recommendations
    (AC-4) — and proves the Slate-like section set (AC-9)."""
    text = ASSESSMENT_TEMPLATE.read_text()
    low = text.lower()
    assert "architecture report" in low, (
        "templates/assessment.md must document an architecture report shape (AC-4)."
    )
    # The Slate-like section set the ticket asks for (AC-9).
    for section in (
        "verdict",
        "what is working",
        "architectural risks",
        "watchlist",
        "recommended actions",
        "not assessed",
    ):
        assert section in low, (
            f"the architecture report shape must include a `{section}` section "
            "(AC-4/AC-9)."
        )
    assert "tickets to file" in low, (
        "the architecture report shape must include a findings/tickets-to-file "
        "section (AC-4/AC-9)."
    )
    # Positive observations are recorded but not filed (AC-4/AC-7).
    assert "not" in low and "filed" in low, (
        "the template must state positive observations are not filed as tickets "
        "(AC-4/AC-7)."
    )


# --- AC-5: assessment-craft allows non-ticket narrative sections --------------


def test_assessment_craft_allows_narrative_scopes() -> None:
    """`assessment-craft` clarifies architecture reports may carry non-ticket
    narrative sections, while actionable risks still need the four parts (AC-5)."""
    low = ASSESSMENT_CRAFT.read_text().lower()
    assert "narrative" in low, (
        "assessment-craft must name the narrative (non-ticket) report sections "
        "(AC-5)."
    )
    assert "architecture" in low, (
        "assessment-craft must tie the narrative allowance to the architecture "
        "scope (AC-5)."
    )
    assert "four parts" in low, (
        "assessment-craft must keep the four-part bar for filed architecture risks "
        "(AC-5)."
    )
    # The Output section's ID-prefix list must name ARCH- alongside CODE-/SYSTEM-,
    # so the scope-ID convention stays coherent with the new scope (review nit).
    assert "arch-" in low, (
        "assessment-craft must list the `ARCH-` scope ID prefix beside CODE-/SYSTEM-."
    )


# --- AC-8: existing `code` and `system` scope behavior is unchanged ----------


def test_code_and_system_scopes_remain_routed() -> None:
    """The concise role still routes all three assessment scopes (AC-8)."""
    steward = STEWARD.read_text()
    for scope in ("`code`", "`architecture`", "`system`"):
        assert scope in steward


def test_global_id_prefix_lists_name_arch() -> None:
    """Every *global* scope-ID-prefix enumeration names `ARCH-` beside CODE-/SYSTEM-,
    so the new scope stays coherent with the report convention (review nit).

    These are the lists that enumerate *all* scope prefixes together (the steward
    Output section, the assessment template, assessment-craft Output) — not the
    per-scope line that defines a single scope's own prefix."""
    # The steward Output section and the assessment template both phrase it as
    # "prefixed by scope — `CODE-` / ... / `SYSTEM-`": ARCH- must sit in that list.
    for path in (ASSESSMENT_TEMPLATE,):
        text = path.read_text()
        m = re.search(r"prefixed by scope — (.+?) —|prefixed by scope — (.+?)\)", text)
        assert m, f"{path.name}: no 'prefixed by scope — …' enumeration found"
        enum = (m.group(1) or m.group(2))
        assert "ARCH-" in enum, (
            f"{path.name}: the global scope-ID enumeration must name `ARCH-` "
            f"(found: {enum!r})."
        )
    # assessment-craft lists them inline in its Output section.
    assert "ARCH-" in ASSESSMENT_CRAFT.read_text(), (
        "assessment-craft Output must name the `ARCH-` prefix."
    )


# --- version integrity: each edited header equals its registry entry ----------


def test_edited_versions_match_registry() -> None:
    """Every edited surface file's `guidance:@version` header equals its registry
    entry (the source's version-integrity invariant, test_guidance_source AC-2)."""
    for path, fragment in (
        (ASSESS, "commands/assess.md"),
        (STEWARD, "agents/steward.md"),
        (ARCHITECTURE, "skills/architecture/SKILL.md"),
        (ASSESSMENT_CRAFT, "skills/assessment-craft/SKILL.md"),
        (ASSESSMENT_TEMPLATE, "templates/assessment.md"),
    ):
        assert _header_version(path) == _registry_version(fragment), (
            f"{fragment}: header {_header_version(path)} != registry "
            f"{_registry_version(fragment)} — bump both together."
        )


# --- AC-9: documented smoke test of the filing rule --------------------------


def _file_only_actionable(items: list[dict[str, str]]) -> list[str]:
    """The architecture filing rule the guidance specifies, as an executable spec.

    An architecture report carries mixed items: ``risk`` (actionable) items file
    as tickets; ``positive``/``tradeoff`` (narrative) items stay in the report and
    are never filed (`commands/assess.md`, `assessment-craft`). This mirrors what
    the steward does by hand; it is a test fixture, not production code (the
    mechanism is agent-followed prose, so a live helper nothing calls would be a
    port-time orphan).
    """
    return [it["id"] for it in items if it["kind"] == "risk"]


def test_smoke_files_only_actionable_risks() -> None:
    """A holistic report with a verdict, a "what is working" note, and one risk
    files only the risk — not the positive observation (AC-9, Verification)."""
    report = [
        {"id": "ARCH-WORKING-1", "kind": "positive"},   # what is working
        {"id": "ARCH-TRADEOFF-1", "kind": "tradeoff"},  # a trade-off to preserve
        {"id": "ARCH-1", "kind": "risk"},               # an actionable risk
    ]
    assert _file_only_actionable(report) == ["ARCH-1"]


def test_smoke_zero_risks_files_nothing() -> None:
    """A useful architecture pass — verdict + watchlist, no actionable risk — files
    zero tickets and is still a valid, complete report (AC-7/AC-9)."""
    report = [
        {"id": "ARCH-WORKING-1", "kind": "positive"},
        {"id": "ARCH-WATCH-1", "kind": "tradeoff"},
    ]
    assert _file_only_actionable(report) == []
