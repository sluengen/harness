"""#204 — a placeholder/stub returning fabricated data must be flag-gated.

*Origin:* form repo, Linear CAL-1130 (``/assess code`` steward pass
2026-07-17, CODE-INSIGHT-1; report ``assessments/2026-07-17-code-review.md``).
Decision made 2026-07-24: adopt as drafted. Two instances one day apart in
the originating repo — a share-card stub and an OCR stub — both wired to
live, ungated surfaces, both filed after the fact rather than caught at
merge. The originating repo owns a gating mechanism (feature-visibility
flags) but had no rule mandating its use for incomplete features.

These are text-parse content guards in the style of
``test_code_quality_security_contract_predicate.py`` (#183) and
``test_mirrors_admission_third_strike.py`` (CAL-800): they read the as-built
guidance and assert the rule is present, so a later re-edit cannot silently
drop it.

Acceptance criteria (#204, per the ticket's "Proposed edit" / "Next step"):

* **AC-1** — ``code-quality`` Part A (Scope) states that a function
  returning hardcoded/faked/placeholder data in place of real logic must
  not be reachable from a user-facing control unless gated behind an
  off-by-default feature flag. Proven by
  :func:`test_code_quality_states_placeholder_gating_rule` and
  :func:`test_placeholder_rule_lives_in_part_a`.
* **AC-2** — the rule is mirrored into ``review-discipline`` Stage 2, so a
  reviewer catches an ungated stub the same way a builder is told to avoid
  shipping one. Proven by
  :func:`test_review_discipline_mirrors_placeholder_gating_rule` and
  :func:`test_placeholder_bullet_is_in_stage_two`.
* **AC-3** — both files' ``guidance:`` header versions and their
  ``registry.yaml`` entries are bumped consistently. Proven by
  :func:`test_code_quality_header_matches_registry` and
  :func:`test_review_discipline_header_matches_registry`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
_REVIEW_DISCIPLINE = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"
_REGISTRY = _REPO_ROOT / "registry.yaml"

_HEADER_RE = re.compile(r"<!--\s*guidance:[\w-]+@([\d.]+)\s*-->")


def _header_version(path: Path) -> str:
    m = _HEADER_RE.search(path.read_text())
    assert m, f"{path} must carry a guidance: header"
    return m.group(1)


def _registry_version(rel_path: str) -> str:
    text = _REGISTRY.read_text()
    m = re.search(
        rf"^\s*{re.escape(rel_path)}:.*?version:\s*([\d.]+)", text, re.MULTILINE
    )
    assert m, f"{rel_path} must have a registry.yaml files: entry"
    return m.group(1)


def _part_a_section() -> str:
    text = _CODE_QUALITY.read_text()
    m = re.search(r"^## Part A\b", text, re.MULTILINE)
    assert m, "code-quality must have a 'Part A — Scope' section."
    rest = text[m.end() :]
    nxt = re.search(r"^## Part B\b", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _stage_two() -> str:
    text = _REVIEW_DISCIPLINE.read_text()
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _placeholder_bullet() -> str:
    """The Stage 2 bullet for the placeholder/stub gating rule."""
    stage_two = _stage_two()
    m = re.search(r"^- \*\*[^\n]*(?:laceholder|stub)[^\n]*$", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet naming the placeholder/stub "
        "gating rule (#204 AC-2)."
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


# --- AC-1: code-quality Part A states the rule ---------------------------


def test_code_quality_states_placeholder_gating_rule() -> None:
    """AC-1: the rule names the stub shape and the off-by-default flag gate."""
    section = _part_a_section().lower()
    assert "hardcoded" in section or "faked" in section or "placeholder" in section, (
        "code-quality Part A must describe a hardcoded/faked/placeholder-data "
        "stub (#204 AC-1)."
    )
    assert "off-by-default" in section and "feature flag" in section, (
        "the rule must require gating behind an off-by-default feature flag "
        "(#204 AC-1)."
    )
    assert "user-facing control" in section, (
        "the rule must name a user-facing control as what must not reach an "
        "ungated stub (#204 AC-1)."
    )


def test_placeholder_rule_lives_in_part_a() -> None:
    """AC-1 (placement): the rule sits in Part A — Scope, not Part B/C."""
    section = _part_a_section().lower()
    assert "off-by-default" in section, (
        "the placeholder/stub gating rule must live in 'Part A — Scope' "
        "(#204 AC-1 placement)."
    )
    # Sanity check: Part A must still contain a sibling subsection.
    assert "smallest working solution" in section


# --- AC-2: review-discipline mirrors the rule in Stage 2 ------------------


def test_review_discipline_mirrors_placeholder_gating_rule() -> None:
    """AC-2: the Stage 2 bullet states the same rule for reviewers."""
    bullet = _placeholder_bullet().lower()
    assert "hardcoded" in bullet or "faked" in bullet or "placeholder" in bullet, (
        f"the placeholder bullet must describe the stub shape; got: {bullet!r} "
        "(#204 AC-2)."
    )
    assert "off-by-default" in bullet and "feature flag" in bullet, (
        f"the placeholder bullet must require the off-by-default feature flag "
        f"gate; got: {bullet!r} (#204 AC-2)."
    )


def test_placeholder_bullet_is_in_stage_two() -> None:
    """AC-2: the placeholder/stub finding lives in Stage 2, beside the other
    structural/quality checks."""
    stage_two = _stage_two().lower()
    assert "off-by-default" in stage_two, (
        "the placeholder/stub gating rule must live in the Stage 2 quality "
        "checks (#204 AC-2)."
    )


# --- AC-3: header + registry version parity -------------------------------


def test_code_quality_header_matches_registry() -> None:
    assert _header_version(_CODE_QUALITY) == _registry_version(
        "skills/code-quality/SKILL.md"
    ), "code-quality's guidance: header must match its registry.yaml version (#204 AC-3)."


def test_review_discipline_header_matches_registry() -> None:
    assert _header_version(_REVIEW_DISCIPLINE) == _registry_version(
        "skills/review-discipline/SKILL.md"
    ), (
        "review-discipline's guidance: header must match its registry.yaml "
        "version (#204 AC-3)."
    )
