"""``engineering-principles`` carries the test-isolation principle.

*Source:* the ``form`` repo's accepted proposal
``specs/proposals/per-run-test-database.md`` (2026-07-17).

A consumer repo's backend suite was pointed at its shared dev database: the
documented test command destroyed dev data on every run, and the posture
accreted two ticket-numbered cleanup workarounds for the residue it left behind.
The lesson generalises past that repo — a suite that mutates state outliving the
run eventually destroys something that mattered — but the guidance set stated no
principle against it, so each repo rediscovers it the expensive way.

The principle's home is the skill that *owns* principles.
``test_skill_boundary_dedup`` AC-1b fixes that boundary:
``engineering-principles`` owns, operational skills reference. The nearest
neighbour elsewhere — ``test-driven-development``'s "test real behaviour, not
mocks" — is a distinct rule (real-vs-mock, not isolation), so nothing is
duplicated and no cross-reference is owed.

**What this module asserts, after #459.** One tripwire over one rule-home: the
``**Tests own the state they mutate.**`` bullet inside ``The principles``. It
reads a small term set the principle cannot be stated without, plus the negation
anchored to the verb it governs — the suite *never borrows* state that outlives
the run.

**What went, and why.** The scoping test (the section is a non-empty proper
subset of the file, and a sibling heading falls outside it) was a control over a
section-wide slicer. The tripwire below anchors on the principle's own bullet
inside that section, so the control's claim is now a precondition of the slice
rather than a separate assertion — it cannot fail alone. And the ``never
borrows`` polarity, which the deleted assertions never read, is now the clause
that carries the rule's direction: five term containments over a paragraph are
satisfied just as well by a paragraph saying a shared instance is fine (ADR
0016).

Craft class this conversion answers: ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "engineering-principles" / "SKILL.md"
_HEADING = "The principles"
_PRINCIPLE_MARKER = "**Tests own the state they mutate"

#: The principle's direction, anchored to the verb it governs. "Provisions its
#: own instance" is an instruction; "never borrows state that outlives the run"
#: is the rule, and it is the half a rewrite drops while keeping the vocabulary.
_NEVER_BORROWS = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,3}?\W+borrow\w*\b", re.IGNORECASE
)


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


def _isolation_principle() -> str:
    """The principle's own bullet, sliced from its bolded marker in the section.

    Two levels of anchoring, and both are load-bearing. The section boundary
    stops the reviewer section or a trade-off aside from satisfying the terms;
    the bullet boundary stops a *sibling principle* from doing so, since
    ``teardown`` and ``structural`` are words a neighbouring principle could
    acquire without this one existing at all.
    """
    section = _principles_section()
    start = section.find(_PRINCIPLE_MARKER)
    assert start != -1, (
        "engineering-principles must state the test-isolation principle as a "
        f"bullet of {_HEADING!r} — a suite that borrows shared state is a defect "
        "every repo otherwise rediscovers by destroying something"
    )
    rest = section[start:]
    end = rest.find("\n\n")
    return rest if end == -1 else rest[:end]


def test_the_test_isolation_principle_has_a_home() -> None:
    """The principles state that a suite owns the state it mutates.

    Three conjuncts and the negation. ``outlives the run`` is the boundary the
    rule draws — without it the principle is about tidiness rather than about
    what survives; ``teardown`` is the disposal half, so provisioning an
    instance and abandoning it does not satisfy the rule; and ``real
    infrastructure`` is what keeps the principle from being read as "mock it",
    which is a different rule that lives in a different skill.
    """
    bullet = _isolation_principle()
    lower = bullet.lower()

    for term, why in (
        ("outlives the run", "the boundary the principle draws is state that "
                             "survives the suite, not state in general"),
        ("teardown", "the suite disposes of its instance; provisioning one and "
                     "leaving it is the residue the workarounds cleaned up"),
        ("real infrastructure", "isolation is not mocking — owning the instance "
                                "is the point, and the real-vs-mock rule is a "
                                "different one in a different skill"),
    ):
        assert term in lower, (
            f"the test-isolation principle no longer names {term!r} — {why}"
        )

    assert _NEVER_BORROWS.search(bullet), (
        "the principle no longer states that the suite *never borrows* state "
        "that outlives the run. Every term above is reused verbatim by a "
        "principle saying a shared instance is acceptable when the team is "
        "careful; the negation beside the verb is the only thing that tells the "
        "two apart."
    )
