"""#184 / #459 — the Stage-2 **CONTEXT.md currency** trigger, as one tripwire.

``CONTEXT.md`` is the first file every agent reads, so a stale entry there
mis-primes every later session — and the class is recurring, not incidental. In
nano-erp it carried three stale frontend claims (no test runner, backend-only, a
gate step omitting tests), each gone stale at an identifiable commit, none of
which pointed a reviewer at ``CONTEXT.md``. The fix was a *narrow, mechanically
checkable* trigger: the diff adding or removing a test runner, a gate step, a
workspace, or a top-level path is the moment the file can go stale, and that is
when the reviewer looks.

**What this module asserts, after #459.** One tripwire over one rule-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*):

1. **Anchor** — the ``- **CONTEXT.md currency**`` bullet exists inside
   ``### Stage 2``. The slice is the assertion window; nothing here reads the
   whole file.
2. **Term set** — the four diff conditions the trigger enumerates. They are the
   rule's substance rather than decoration: the bullet itself says *these four
   are the diff shapes that make the file stale*.
3. **Polarity** — two directional clauses inside the window. ``adds or removes``
   is bidirectional (a removal leaves ``CONTEXT.md`` as stale as an addition
   does), and the negation ``… it is not "read CONTEXT.md every time"`` is what
   keeps the trigger narrow. Without the second, a rewrite that widened the
   check to every review would pass every term above — the inversion-passes
   class ``craft.md`` → *Mutate the rule into its opposite, not only out of
   existence* names, and the reason #459 converted this module.

What went, and why: the severity grade, the ``stack`` / ``commands`` / ``layers``
block names and the *first file* rationale were positive-meaning pins — brittle
against a benign rewording and silent on an inversion. ``#459``'s policy hands
those to the review gate. A third test re-derived the ``### Stage 2`` →
``## Severity`` slice the bullet reader already performs, so it could only fail
where the slicer already fails.

**This module is the Stage-2 slicer's home.** ``_skill_text`` and
``_context_currency_bullet`` are imported by
``test_review_discipline_asbuilt_record_currency``, and ``_stage_two_bullet`` is
imported by the five sibling Stage-2 bullet guards, which each carried a private
copy of it before #459. One slicer, called by every assertion it protects
(``craft.md`` → *A positive control must exercise the predicate, not
re-implement it*).
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"

_BULLET_TITLE = "CONTEXT.md currency"

#: The four diff shapes the trigger enumerates. The bullet declares its own
#: cardinality ("these four are the diff shapes"), so the set is the rule.
_TRIGGER_CONDITIONS = ("test runner", "gate step", "workspace", "top-level path")

#: The trigger fires in **both** directions — a removal leaves ``CONTEXT.md`` as
#: stale as an addition does.
_BIDIRECTIONAL = "adds or removes"

#: The narrowness clause, with the negation **anchored to what it governs**. A
#: bare ``"not" in bullet`` over a 1,400-character paragraph is decoration: almost
#: any English paragraph satisfies it. This one only matches while the bullet
#: still refuses the "read `CONTEXT.md` every time" reading.
_NOT_EVERY_TIME = re.compile(r"\bnot\b(?:\W+\w+){0,4}?\W+every\s+time\b", re.IGNORECASE)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage_two(text: str) -> str:
    """The ``### Stage 2`` body, to the ``## Severity`` section that follows it."""
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _stage_two_bullet(text: str, title: str) -> str:
    """The Stage-2 ``- **<title>**`` bullet, sliced to the next bullet or heading.

    The window is the predicate: a bullet-wide term set read over the whole
    ``### Stage 2`` body would be satisfied by any of the fourteen neighbouring
    rules, which is the over-wide unit ``craft.md`` → *The text unit is part of
    the predicate* names. Anchoring on the **title** rather than on a
    neighbour's position also keeps the slice correct when a bullet is inserted
    (``craft.md`` → *An ordinal reference into an enumeration is invalidated by
    a correct insertion*).
    """
    stage_two = _stage_two(text)
    m = re.search(rf"^- \*\*{re.escape(title)}\*\*", stage_two, re.MULTILINE)
    assert m, (
        f"`skills/review-discipline/references/diff-shape-checks.md` Stage 2 has no "
        f"`- **{title}**` bullet — the anchor every assertion below reads is gone"
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def _context_currency_bullet(text: str) -> str:
    return _stage_two_bullet(text, _BULLET_TITLE)


def test_the_context_currency_trigger_stays_narrow_and_bidirectional() -> None:
    """The trigger names its four diff shapes, fires both ways, and is not "every time".

    Deleting or renaming the bullet fails in the slicer. Dropping a condition
    fails on the term set. Widening the rule to "read `CONTEXT.md` every time" —
    the drift the bullet exists to refuse, and the one an inverted rewrite
    produces — fails on the negation window, which no co-occurrence check can
    see.
    """
    bullet = _context_currency_bullet(_skill_text()).lower()

    missing = [c for c in _TRIGGER_CONDITIONS if c not in bullet]
    assert not missing, (
        f"the CONTEXT.md currency trigger no longer names {missing} as diff "
        f"condition(s) obliging a CONTEXT.md check. The four are the rule: a "
        f"trigger that drops one goes stale at exactly the commit it stopped "
        f"covering, and no later change re-touches the gap (#184)."
    )
    assert _BIDIRECTIONAL in bullet, (
        "the trigger no longer fires on a diff that **adds or removes** one of "
        "the named conditions. Scoped to additions only, a removed test runner "
        "leaves `CONTEXT.md` claiming one forever (#184)."
    )
    assert _NOT_EVERY_TIME.search(bullet), (
        "the bullet no longer refuses the 'read `CONTEXT.md` every time' "
        "reading. That refusal is the rule's direction, and it is the half a "
        "rewrite drops while keeping every term above — a widened check is "
        "ignored wholesale, which is strictly worse than four narrow ones "
        "(#184, #459)."
    )
