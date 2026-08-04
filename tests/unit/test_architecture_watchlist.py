"""CAL-815 — architecture watchlist triggers in build and review flow.

Raised from the architecture-review follow-up (2026-06-19): an opportunistic
"refactor when you touch a gravity well" instruction is unreliable in a fully
agentic system when the trigger lives only in conversational memory. This change
makes an optional, repo-local ``architecture_watchlist`` first-class: when the
planned or actual touched files intersect it, the change spec and the review must
carry a ``Watchlist trigger`` section that either includes a small
behavior-preserving seam extraction or records why extraction is deferred.

The mechanism has ONE canonical home — ``skills/architecture/SKILL.md`` — and the
CONTEXT shape (``templates/CONTEXT.template.md``), the builder (``spec-authoring``
+ ``templates/change.md``), the reviewer (``review-discipline``), and the steward
(``agents/steward.md``) reference it rather than re-stating it. These guards pin
each acceptance criterion so a later re-edit cannot silently drop it.

These are text-parse content guards in the style of ``test_over_engineering_lens``
/ ``test_review_discipline_port_orphan``; the ``test_smoke_*`` cases below are the
documented smoke test the ticket asks for (AC-7), exercising the trigger rule the
guidance specifies over the three required cases.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = REPO_ROOT / "skills" / "architecture" / "SKILL.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
REVIEW_DISCIPLINE = REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"
CONTEXT_TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"
CHANGE_TEMPLATE = REPO_ROOT / "templates" / "change.md"
STEWARD = REPO_ROOT / "agents" / "steward.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"

#: The canonical mechanism's section header — it lives in exactly one skill.
WATCHLIST_SECTION = "## Architecture watchlist"

#: The named section the change spec and the review must carry when a watchlisted
#: file is touched. Stable across the builder, reviewer, and template homes.
TRIGGER_SECTION = "Watchlist trigger"

#: The repo-local CONTEXT key carrying the gravity-well file list.
WATCHLIST_KEY = "architecture_watchlist"


def _section(text: str, header: str) -> str:
    """The body of a ``## ``-level markdown section, header to next ``## ``."""
    m = re.search(rf"^{re.escape(header)}\b.*$", text, re.MULTILINE)
    assert m, f"missing section header {header!r}"
    rest = text[m.end() :]
    end = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


# --- AC-1: the mechanism is documented, with one canonical home ---------------


def test_architecture_defines_the_watchlist_mechanism() -> None:
    """The ``architecture`` skill defines the trigger and the two outcomes (AC-1)."""
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()
    assert WATCHLIST_KEY in block, (
        "the Architecture watchlist section must name the repo-local "
        f"`{WATCHLIST_KEY}` contract (AC-1)."
    )
    assert TRIGGER_SECTION.lower() in block, (
        "the section must name the `Watchlist trigger` section the spec/review "
        "carry (AC-1)."
    )
    assert "seam" in block, (
        "the section must name outcome 1 — a behavior-preserving seam extraction "
        "(AC-1)."
    )
    assert "defer" in block, (
        "the section must name outcome 2 — an explicit deferral with a reason "
        "(AC-1)."
    )


def test_watchlist_section_lives_in_exactly_one_skill() -> None:
    """The mechanism has one canonical home — ``architecture`` — not many (lean/MECE)."""
    homes = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.glob("skills/*/SKILL.md")
        if WATCHLIST_SECTION in p.read_text()
    )
    assert homes == ["skills/architecture/SKILL.md"], (
        "the Architecture watchlist mechanism must have exactly one canonical "
        f"home (skills/architecture/SKILL.md); found in: {homes}."
    )


# --- #284: a repeated extraction arms a newly revealed gravity well -----------


def test_second_seam_extraction_adds_non_watchlisted_module_to_watchlist() -> None:
    """A second extraction makes the module a gravity well in the same change."""
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()
    required_tokens = (
        "second seam extraction",
        "non-watchlisted module",
        "descriptive comment",
    )
    missing = [token for token in required_tokens if token not in block]
    assert not missing, (
        "the Architecture watchlist section must require a second seam extraction "
        "to add the non-watchlisted module to CONTEXT.md's "
        "architecture_watchlist.files with its descriptive comment (#284); "
        f"missing: {missing}."
    )


# --- AC-5: the actual-diff comparison names the integration branch + fallback --


def test_architecture_documents_diff_comparison_and_fallback() -> None:
    """The mechanism explains comparing the diff against the integration branch,
    with a safe fallback when the base branch is unknown (AC-5)."""
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()
    assert "integration branch" in block, (
        "the mechanism must explain comparing the actual diff against the repo's "
        "integration branch from CONTEXT.md (AC-5)."
    )
    assert "fallback" in block or "fall back" in block, (
        "the mechanism must give a safe fallback for when the base branch is "
        "unknown (AC-5)."
    )


# --- #251 (CODE-INSIGHT-2): design is named as the earlier, mechanized carrier -


def test_architecture_names_design_stage_as_watchlist_trigger_carrier() -> None:
    """The design stage — not just review — is named as a mechanized carrier of
    the ``Watchlist trigger`` section: conditional, and confirmed (not just
    remembered) at review (#251, CODE-INSIGHT-2)."""
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()
    assert "design" in block, (
        "the section must name a design stage as an earlier, mechanized carrier "
        "of the Watchlist trigger section, not review alone (#251)."
    )
    assert "conditional" in block, (
        "the section must state the Watchlist trigger section is conditional — "
        "present only when the touched set intersects the watchlist (#251)."
    )
    assert "confirm" in block, (
        "the section must state that review confirms the record rather than "
        "being the only place it could be remembered (#251)."
    )
    assert "harness/cli/" not in block, (
        "the paragraph must stay capability-shaped — no concrete "
        "`harness/cli/...` path in universal guidance (#251)."
    )


# --- AC-6: repo-owned, preserved across updates, and a no-op when absent -------


def test_architecture_documents_noop_and_preservation() -> None:
    """Missing watchlist is a no-op, and the watchlist is repo-owned/preserved (AC-6)."""
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()
    assert "no-op" in block, (
        "the mechanism must state that a missing `architecture_watchlist` is a "
        "no-op for repos that do not opt in (AC-6)."
    )
    assert "repo-owned" in block or "preserve" in block, (
        "the mechanism must state the watchlist is repo-owned and preserved across "
        "guidance updates (AC-6)."
    )
    assert "update-guidance" in block, (
        "the mechanism must point at `/update-guidance` never overwriting "
        "CONTEXT.md as the preservation guarantee (AC-6)."
    )


def test_update_guidance_never_touches_context() -> None:
    """The preservation guarantee AC-6 rests on still holds in update-guidance."""
    text = UPDATE_GUIDANCE.read_text().lower()
    assert "never touch" in text and "context.md" in text, (
        "/update-guidance must still state it never touches CONTEXT.md — the "
        "guarantee that preserves repo-specific watchlist entries (AC-6)."
    )


# --- AC-1 shape: the CONTEXT template documents the optional block -------------


def test_context_template_documents_optional_watchlist_shape() -> None:
    """The CONTEXT template carries an optional `architecture_watchlist` block (AC-1)."""
    text = CONTEXT_TEMPLATE.read_text()
    assert WATCHLIST_KEY in text, (
        f"templates/CONTEXT.template.md must document the `{WATCHLIST_KEY}` shape "
        "(AC-1)."
    )
    # the block carries a `files:` list and is marked optional / no-op when absent.
    low = text.lower()
    assert "files" in low, "the watchlist block must show a `files:` list (AC-1)."
    assert "optional" in low or "no-op" in low, (
        "the watchlist block must be marked optional (omit it and the trigger is a "
        "no-op) (AC-1/AC-6)."
    )


# --- AC-2: the builder requires a Watchlist trigger section --------------------


def test_spec_authoring_requires_watchlist_trigger_section() -> None:
    """`spec-authoring` requires the change spec carry a Watchlist trigger section
    when the planned diff intersects the watchlist, and points at architecture (AC-2)."""
    text = SPEC_AUTHORING.read_text()
    assert TRIGGER_SECTION in text, (
        "spec-authoring must require a `Watchlist trigger` change-spec section "
        "(AC-2)."
    )
    assert WATCHLIST_KEY in text, (
        "spec-authoring must key the requirement off `architecture_watchlist` "
        "(AC-2)."
    )
    assert "architecture" in text, (
        "spec-authoring must reference the `architecture` mechanism rather than "
        "re-stating it (AC-2)."
    )


def test_change_template_has_watchlist_trigger_section() -> None:
    """`templates/change.md` makes the Watchlist trigger section first-class (AC-2)."""
    assert TRIGGER_SECTION in CHANGE_TEMPLATE.read_text(), (
        "templates/change.md must include a (conditional) `Watchlist trigger` "
        "section so the builder records the outcome (AC-2)."
    )


# --- AC-3: the reviewer flags an unhandled watchlisted file -------------------


def _review_watchlist_bullet(text: str) -> str:
    """The Stage-2 ``- **Architecture watchlist**`` bullet, to the next bullet/heading."""
    m = re.search(r"^- \*\*Architecture watchlist\*\*", text, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no '- **Architecture watchlist**' check "
        "(CAL-815 AC-3)."
    )
    rest = text[m.end() :]
    end = re.search(r"^(?:- \*\*|## |### )", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def test_review_discipline_flags_unhandled_watchlist_file() -> None:
    """The reviewer compares the actual diff against the watchlist and treats an
    unhandled watchlisted file (no seam, no deferral) as a finding (AC-3)."""
    block = _review_watchlist_bullet(REVIEW_DISCIPLINE.read_text()).lower()
    assert WATCHLIST_KEY in block, (
        "the review check must key off `architecture_watchlist` (AC-3)."
    )
    assert "diff" in block, (
        "the review check must compare the *actual diff* against the watchlist "
        "(AC-3)."
    )
    assert "seam" in block and "defer" in block, (
        "the review check must require either a seam extraction or a recorded "
        "deferral, and flag a watchlisted file that has neither (AC-3)."
    )
    assert "finding" in block or "medium" in block, (
        "an unhandled watchlisted file must be stated as a review finding (AC-3)."
    )


# --- the steward proposes/refreshes watchlist entries -------------------------


def test_steward_proposes_watchlist_entries() -> None:
    """The steward's architecture-drift lens proposes/refreshes watchlist entries
    when it identifies a recurring gravity well."""
    assert WATCHLIST_KEY in STEWARD.read_text(), (
        "agents/steward.md must teach the architecture-drift lens to propose a "
        "`architecture_watchlist` entry on a recurring gravity well."
    )


# --- AC-4: changes are generic — no Slate-specific paths ----------------------

SURFACE = (
    ARCHITECTURE,
    SPEC_AUTHORING,
    REVIEW_DISCIPLINE,
    CONTEXT_TEMPLATE,
    CHANGE_TEMPLATE,
    STEWARD,
)
#: Slate-specific dogfood references that must not leak into universal guidance.
FORBIDDEN = ("slate", "passport", "0e5cd59", "mobile/lib")


def test_surface_changes_are_generic() -> None:
    """The command/skill/template changes name no Slate-specific paths (AC-4)."""
    for path in SURFACE:
        low = path.read_text().lower()
        leaked = [tok for tok in FORBIDDEN if tok in low]
        assert not leaked, (
            f"{path.relative_to(REPO_ROOT)} leaks Slate-specific reference(s) "
            f"{leaked} — the watchlist guidance must be generic (AC-4)."
        )


# --- AC-7: documented smoke test of the trigger over the three cases -----------


def _watchlist_triggers(watchlist_files: list[str], changed: list[str]) -> list[str]:
    """The trigger rule the guidance specifies, as an executable spec.

    A changed file fires the trigger when it matches any glob in the repo's
    ``architecture_watchlist.files``. An absent or empty watchlist never fires —
    the no-opt-in no-op (AC-6). This mirrors what an agent does by hand when it
    compares the planned/actual touched files against the watchlist; it is a test
    fixture, not production code (the mechanism is agent-followed prose, so a live
    helper nothing calls would be a port-time orphan).
    """
    return [
        c for c in changed if any(fnmatch.fnmatch(c, pat) for pat in watchlist_files)
    ]


def test_smoke_no_watchlist_is_a_noop() -> None:
    """Case 1 — a repo that does not opt in: the trigger never fires (AC-7/AC-6)."""
    assert _watchlist_triggers([], ["app/Big.tsx", "src/core.py"]) == []


def test_smoke_watchlist_with_no_intersection_does_not_fire() -> None:
    """Case 2 — watchlist present, the diff misses it: no trigger (AC-7)."""
    assert (
        _watchlist_triggers(
            ["app/screens/Big.tsx", "src/orchestrator/*.py"],
            ["src/util.py", "README.md"],
        )
        == []
    )


def test_smoke_intersecting_diff_fires() -> None:
    """Case 3 — watchlist present, the diff touches it: the trigger fires (AC-7)."""
    fired = _watchlist_triggers(
        ["app/screens/*.tsx", "src/orchestrator.py"],
        ["src/orchestrator.py", "README.md", "app/screens/Detail.tsx"],
    )
    assert fired == ["src/orchestrator.py", "app/screens/Detail.tsx"]
