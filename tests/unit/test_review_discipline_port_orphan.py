"""CAL-665 — ``review-discipline`` catches lifted-but-unwired modules at port time.

From the 2026-06-13 code assessment (CODE-INSIGHT-001). CODE-001 (a dead
``card_factory``, 312 lines) entered in the initial backend port (2026-05-24)
and was never touched again — a class **no per-change reviewer catches**,
because no later change ever touches the orphan. A whole module lifted from
another repo that nothing in *this* repo imports is dead on arrival, yet the
per-change review only looks at what the change touched.

The accepted fix (CAL-665 decision, 2026-06-14) adds a rule to
``review-discipline``: when lifting a module from another repo, confirm
production code in this repo imports it before the lift lands. It is the
port-time sibling of the existing **Dead surface after a deletion** rule — same
"grep the source tree for a production caller, excluding the module and tests"
technique, applied at the moment a module arrives rather than when a subsystem
is retired.

This guard binds that rule into the skill so a future re-edit cannot silently
drop it. It is a text-parse content guard in the style of
``test_distributed_skill_cites`` (CAL-654) and ``test_retired_spec_cites``
(CAL-633): it reads the as-built guidance and asserts the rule is present.

Acceptance criteria (this ticket):

* **AC-1** — ``review-discipline`` carries a rule that a module lifted/ported
  from another repo must be imported by *production* code in this repo before
  the lift lands. Proven by :func:`test_review_discipline_has_port_orphan_rule`.
* **AC-2** — the rule lives in the Stage 2 quality checks (where the sibling
  deletion-orphan rule lives), not buried elsewhere. Proven by
  :func:`test_port_orphan_rule_is_in_stage_two`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_review_discipline_has_port_orphan_rule() -> None:
    """The skill states the port-time orphan rule (AC-1)."""
    text = _skill_text().lower()
    # The rule is about a module *lifted/ported from another repo*...
    assert "lift" in text or "port" in text, (
        "review-discipline must name the lift/port-from-another-repo case"
    )
    # ...that must be reached by *production* code, not just its own test.
    assert "production" in text, (
        "the port-orphan rule must require a *production* importer/caller, "
        "not merely a passing test"
    )
    # ...and the consequence when it is not (the assessment's phrasing).
    assert "dead on arrival" in text, (
        "review-discipline must state that an unimported lifted module is "
        "dead on arrival (CAL-665 / CODE-INSIGHT-001)"
    )


def test_port_orphan_rule_is_in_stage_two() -> None:
    """The rule sits in Stage 2 quality, beside the deletion-orphan rule (AC-2)."""
    text = _skill_text()
    stage_two_start = text.find("### Stage 2")
    assert stage_two_start != -1, "review-discipline must have a Stage 2 section"
    severity_start = text.find("## Severity")
    assert severity_start != -1, "review-discipline must have a Severity section"
    stage_two = text[stage_two_start:severity_start].lower()
    assert "dead on arrival" in stage_two, (
        "the port-orphan rule must live in the Stage 2 quality checks, "
        "alongside the existing dead-surface-after-deletion rule"
    )
