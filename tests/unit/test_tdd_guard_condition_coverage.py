"""#203 — RED gains a rule: cover each of a guard's trigger conditions.

Surfaced by an ``/assess code`` steward pass (2026-07-17, pass 3,
CODE-INSIGHT-1) against a consuming repo: a multi-condition guard
(``checkRoundTrip``) had two independent trigger paths — refuse-vs-diverge —
but its call site's test suite only ever exercised one. Deleting the other
path's check left the suite green: 422 assertions, all satisfied by the
untested path alone. The guard *as a whole* was covered; one of its
conditions was not, and that untested half is exactly what let a real defect
through unseen.

``test-driven-development``'s RED section already has a sibling rule for the
same failure shape in a different guise — "Cover the active loop, not just
its exit" (a loop's live-state path going untested behind a green suite).
This ticket adds the guard-conditions analogue immediately beside it: a
multi-condition guard needs one test per condition, each proven by deleting
that condition in turn and confirming a *named* assertion goes red for it.

Acceptance criteria (this ticket):

* **AC-1** — the skill states the rule: a guard with several independent
  trigger conditions needs one test per condition, proven by deleting each
  condition in turn and confirming a named assertion goes red for it; a
  condition whose deletion leaves the suite green is untested regardless of
  how many assertions surround it. Proven by
  :func:`test_skill_has_guard_condition_coverage_rule`.
* **AC-2** — the rule sits in the RED section, immediately after "Cover the
  active loop, not just its exit" and before the "Verify RED" heading.
  Proven by :func:`test_rule_sits_after_active_loop_bullet_in_red_section`.
* **AC-3** — the skill's version header is bumped and matches its
  ``registry.yaml`` entry (registry two-place self-version: header +
  ``files:`` row). Proven by :func:`test_version_bumped_and_matches_registry`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "test-driven-development" / "SKILL.md"
_REGISTRY = _REPO_ROOT / "registry.yaml"

_PRIOR_VERSION = "0.4.0"
_NEW_VERSION = "0.5.0"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _red_section(text: str) -> str:
    """The RED body: between its heading and the "Verify RED" heading."""
    start = text.index("### RED")
    end = text.index("### Verify RED", start)
    return text[start:end]


def _guard_condition_bullet(text: str) -> str:
    """The new bullet, sliced to its own paragraph within the RED section."""
    red = _red_section(text)
    m = re.search(
        r"^\*\*Cover each of a guard's.*?conditions.*?\*\*", red, re.MULTILINE
    )
    assert m, (
        "test-driven-development RED has no bullet naming coverage of each "
        "of a guard's trigger conditions (#203 AC-1)."
    )
    rest = red[m.start() :]
    nxt = re.search(r"\n\n", rest)
    return rest[: nxt.start()] if nxt else rest


def test_skill_has_guard_condition_coverage_rule() -> None:
    """The skill states the guard-conditions rule (AC-1)."""
    bullet = _guard_condition_bullet(_skill_text()).lower()
    # Names the failure shape: several independent trigger conditions...
    assert "independent" in bullet and "condition" in bullet, (
        "the rule must describe a guard with several independent trigger "
        "conditions"
    )
    # ...needs one test per condition...
    assert "one test per condition" in bullet, (
        "the rule must require one test per condition"
    )
    # ...proven by deleting each condition and confirming a named red...
    assert "delete each condition" in bullet, (
        "the rule must direct deleting each condition in turn to prove "
        "coverage"
    )
    assert "named" in bullet and "red" in bullet, (
        "the rule must require a named assertion going red for the deleted "
        "condition"
    )
    # ...and a deletion that stays green means that condition is untested.
    assert "green" in bullet and "untested" in bullet, (
        "the rule must state that a condition whose deletion leaves the "
        "suite green is untested"
    )


def test_rule_sits_after_active_loop_bullet_in_red_section() -> None:
    """The rule sits immediately after the active-loop bullet (AC-2)."""
    red = _red_section(_skill_text())
    active_loop_idx = red.index("**Cover the active loop, not just its exit.**")
    guard_idx = red.index("**Cover each of a guard's")
    assert active_loop_idx < guard_idx, (
        "the guard-conditions rule must come after the active-loop rule in "
        "RED"
    )
    between = red[active_loop_idx:guard_idx]
    assert between.count("\n\n") <= 1, (
        "the guard-conditions rule must sit immediately after the "
        "active-loop bullet (no other bullet between them)"
    )


def test_version_bumped_and_matches_registry() -> None:
    """The header is bumped past 0.4.0 and matches the registry row (AC-3)."""
    text = _skill_text()
    header_m = re.search(
        r"^<!-- guidance:test-driven-development@([\d.]+) -->", text, re.MULTILINE
    )
    assert header_m, "test-driven-development/SKILL.md must carry its version header"
    header_version = header_m.group(1)
    assert header_version != _PRIOR_VERSION, (
        f"the header version must be bumped past {_PRIOR_VERSION} for this "
        "ticket's content addition"
    )

    registry_text = _REGISTRY.read_text(encoding="utf-8")
    row_m = re.search(
        r"skills/test-driven-development/SKILL\.md:\s*\{[^}]*version:\s*([\d.]+)",
        registry_text,
    )
    assert row_m, "registry.yaml must carry a test-driven-development row"
    assert row_m.group(1) == header_version, (
        "registry.yaml's test-driven-development version must match the "
        "SKILL.md header (registry two-place self-version)"
    )
