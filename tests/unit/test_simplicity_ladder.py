"""``engineering-principles`` carries the simplicity decision ladder's scope guard.

Spawned from ``specs/proposals/borrow-from-ponytail.md`` (accepted 2026-06-15,
Option C). The proposal folds a "stop at the first rung that holds" decision
ladder into ``engineering-principles`` — the ordered *procedure* that
operationalises the simplicity *values* the skill already states.

The load-bearing constraint — the reason the plugin itself was *not* installed —
is the scope guard: the ladder governs *what to build*, never *whether to test*
or *what the spec requires*. A "build less" ladder with no such clause is one
short step from "test less", and the two iron laws it must not touch live in
other skills, so the guard has to name them.

**What this module asserts, after #459.** One tripwire over one rule-home: the
``**Scope guard`` paragraph inside ``## Before you write it``. It reads the two
skills the clause cannot cross-reference without naming, plus the negation
anchored to the verb it governs — the ladder *never licenses* skipping the
failing test.

**What went, and why.** Eleven token pins over the same section, of which the
loop asserting ``f"{n}." in section`` for 1..6 was the clearest case: any
ordered list of six items satisfies it, including a ladder whose rungs had been
replaced with unrelated text, so it measured the presence of numerals rather
than of a ladder. The rung vocabulary (``need``, ``standard library``,
``native``, ``dependency``, ``one line``, ``minimum``) and the
``reflex``/``research project`` pins went with it: they are the ladder's content,
and whether the content is right is what the review gate reads. Per ADR 0016 a
positive-meaning pin is brittle and vacuous at once — it broke on a rewording
that preserved the ladder exactly, and passed on one that gutted it.

Craft class this conversion answers: ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "engineering-principles" / "SKILL.md"
_LADDER_HEADING = "## Before you write it"

#: The guard's direction, anchored to the verb it governs. The clause is the
#: whole reason the ladder is safe to distribute: it *never licenses* the
#: shortcut. A bare negation over the paragraph would be decoration — the
#: paragraph is prose, and prose carries negations.
_NEVER_LICENSES = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,3}?\W+licen[cs]\w+", re.IGNORECASE
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _ladder_section() -> str:
    """The decision-ladder subsection, isolated from the rest of the skill."""
    text = _skill_text()
    start = text.find(_LADDER_HEADING)
    assert start != -1, (
        "engineering-principles must carry a decision-ladder subsection "
        f"('{_LADDER_HEADING}')"
    )
    rest = text[start + len(_LADDER_HEADING) :]
    end = rest.find("\n## ")  # bounded by the next top-level section
    return rest if end == -1 else rest[:end]


def _scope_guard_paragraph() -> str:
    """The scope guard's own paragraph inside the ladder section.

    The window is the paragraph, not the section: ``test-driven-development``
    and ``review-discipline`` are named across ``engineering-principles`` for
    unrelated reasons, so a section-wide conjunction is satisfied by a section
    whose scope guard was deleted — the over-wide unit ``craft.md`` → *The text
    unit is part of the predicate* names.
    """
    section = _ladder_section()
    marker = "**Scope guard"
    start = section.find(marker)
    assert start != -1, (
        "the decision ladder must carry an explicit `Scope guard` paragraph — "
        "a 'build less' procedure distributed without one is one reading away "
        "from 'test less'"
    )
    rest = section[start:]
    end = rest.find("\n\n")
    return rest if end == -1 else rest[:end]


def test_the_ladder_scope_guard_has_a_home() -> None:
    """The scope guard names both iron-law skills and refuses to override them.

    Two conjuncts and the negation. The cross-references are conjuncts because
    the rules the ladder must not touch live in *other* skills: a scope guard
    that gestures at "the tests" without naming
    ``test-driven-development``/``review-discipline`` leaves a reader who
    followed the ladder here with nothing to go back to.
    """
    paragraph = _scope_guard_paragraph()
    lower = paragraph.lower()

    for skill in ("test-driven-development", "review-discipline"):
        assert skill in lower, (
            f"the scope guard no longer cross-references `{skill}` — the iron "
            f"law it must not override lives there, not in this file"
        )
    assert _NEVER_LICENSES.search(paragraph), (
        "the scope guard no longer states that the ladder *never licenses* "
        "skipping the failing test or trimming a criterion. Naming the two "
        "skills carries no direction on its own: a paragraph citing both while "
        "permitting the shortcut reads the same to an unanchored guard, which "
        "is the inversion-passes class ADR 0016 closes."
    )
