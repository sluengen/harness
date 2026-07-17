"""CAL-1161 — ``engineering-principles`` carries the test-isolation principle.

*Source:* the ``form`` repo's accepted proposal
``specs/proposals/per-run-test-database.md`` (2026-07-17).

A consumer repo's backend suite was pointed at its shared dev database: the
documented test command destroyed dev data on every run, and the posture
accreted two ticket-numbered cleanup workarounds for the residue it left
behind. The lesson generalises past that repo — a suite that mutates state
outliving the run eventually destroys something that mattered — but the
guidance set stated no principle against it, so each repo rediscovers it the
expensive way.

This guard pins the principle into the skill that *owns* principles.
``test_skill_boundary_dedup`` AC-1b fixes that boundary: ``engineering-principles``
owns, operational skills reference. The nearest neighbour elsewhere —
``test-driven-development``'s "test real behaviour, not mocks" — is a distinct
rule (real-vs-mock, not isolation), so nothing is duplicated and no
cross-reference is owed.

Scoped to "The principles" so prose elsewhere in the file (the reviewer
section, a trade-off aside) cannot satisfy the assertion.

Acceptance criteria (this ticket):

* **AC-1** — the principle is stated in "The principles": the suite provisions
  and disposes its own instance, real infrastructure stays the right call, and
  the isolation is structural rather than remembered. Proven by
  :func:`test_principles_carry_test_isolation`.
* **AC-2** — the assertion is section-scoped, so a mention outside the
  principles list cannot satisfy it. Proven by
  :func:`test_isolation_principle_is_scoped_to_the_principles_list`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "engineering-principles" / "SKILL.md"
_HEADING = "The principles"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _principles_section() -> str:
    """The body of "The principles", bounded by the next same-or-higher heading.

    Mirrors ``test_skill_boundary_dedup._section`` — scoping the assertion to one
    subsection is what stops a cross-reference in a different part of the file
    from satisfying it.
    """
    lines = _skill_text().splitlines()
    start: int | None = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"(#+)\s+(.*)$", line)
        if m and m.group(2).strip() == _HEADING:
            start, level = i + 1, len(m.group(1))
            break
    assert start is not None, f"section heading not found: {_HEADING!r}"
    body: list[str] = []
    for line in lines[start:]:
        m = re.match(r"(#+)\s+", line)
        if (m and len(m.group(1)) <= level) or line.strip() == "---":
            break
        body.append(line)
    return "\n".join(body)


def test_principles_carry_test_isolation() -> None:
    """The principles state that a suite owns the state it mutates (AC-1)."""
    section = _principles_section()
    lower = section.lower()

    assert "tests own the state they mutate" in lower, (
        "engineering-principles must state the test-isolation principle in "
        "'The principles' (CAL-1161 AC-1)"
    )
    # The constraint itself: never borrow state that outlives the run.
    assert "outlives the run" in lower, (
        "the principle must name the constraint — the suite must not mutate "
        "state that outlives the run (CAL-1161 AC-1)"
    )
    # The suite provisions and disposes its own instance.
    assert "teardown" in lower, (
        "the principle must say the suite disposes of its instance at teardown "
        "(CAL-1161 AC-1)"
    )
    # Isolation does NOT mean mocking — real infrastructure stays the right call.
    assert "real infrastructure" in lower, (
        "the principle must keep real infrastructure the right call — owning the "
        "instance is the point, not mocking it (CAL-1161 AC-1)"
    )
    # The fix is structural, not a rule people must remember.
    assert "structural" in lower, (
        "the principle must state the isolation is structural rather than a rule "
        "everyone must remember (CAL-1161 AC-1)"
    )


def test_isolation_principle_is_scoped_to_the_principles_list() -> None:
    """The guard reads the principles list, not the whole file (AC-2)."""
    section = _principles_section()
    full = _skill_text()

    # The section is a proper, non-empty subset of the file — otherwise the
    # scoping above is decoration and AC-1 could be satisfied from anywhere.
    assert section, "the principles section must not be empty"
    assert len(section) < len(full), (
        "the principles section must be a strict subset of the skill — if it "
        "spans the whole file the scoping proves nothing (CAL-1161 AC-2)"
    )
    # A sibling section's content must fall outside it.
    assert "## How the reviewer uses this" not in section, (
        "the principles section must stop at the next top-level heading "
        "(CAL-1161 AC-2)"
    )
