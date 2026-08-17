"""CAL-823 / #459 — the Stage-2 **Misplaced pure helper** rule, as one tripwire.

CAL-796 added the check: in a repo whose CONTEXT designates a home for testable
client logic (e.g. a ``lib/`` under a coverage ratchet), a *pure* function
declared inline in a view/screen that a **second** view also needs belongs in
that home before approval, not copied screen-to-screen. The class hides
per-change because each ticket touches one screen, so it is caught at the moment
of reuse.

**What this module asserts, after #459.** One tripwire over one rule-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*):

1. **Anchor** — the ``- **Misplaced pure helper**`` bullet exists inside
   ``### Stage 2``, and the assertion reads only that slice.
2. **Term set** — ``pure``, ``second``, ``before approval``: what the helper
   must be, when the rule fires, and the deadline. ``second`` is the one that
   makes it this rule rather than a general extract-early instruction.
3. **Polarity** — ``not copied screen-to-screen``, with the negation anchored to
   the verb it governs. The rule is a *refusal*: the sanctioned outcome is a
   move, and an edit that kept every term above while permitting the copy would
   invert it silently — ``craft.md`` → *Mutate the rule into its opposite, not
   only out of existence*.

What went: ``inline``, ``screen``, ``lib/`` and ``moment of reuse`` were
positive-meaning pins that break on a benign rewording without measuring
direction, and ``test_misplaced_helper_rule_is_in_stage_two`` re-checked the
placement the bullet slicer already enforces by construction.
"""

from __future__ import annotations

import re

from tests.unit._prose import diff_shape_checks_text, stage_two_bullet

_BULLET_TITLE = "Misplaced pure helper"

#: What the helper must be, the reuse signal that fires the rule, and the
#: deadline the move is owed by.
_TERMS = ("pure", "second", "before approval")

#: The refusal, with the negation **anchored to the verb it governs**. A bare
#: negation token would be satisfied by the purity definition ("no hooks, no
#: JSX/render") sitting three clauses earlier; this only matches while the
#: bullet still rejects the copy as the outcome.
_NOT_COPIED = re.compile(r"\bnot\b(?:\W+\w+){0,2}?\W+copied\b", re.IGNORECASE)


def _bullet() -> str:
    return stage_two_bullet(diff_shape_checks_text(), _BULLET_TITLE)


def test_the_misplaced_helper_rule_moves_the_second_copy_before_approval() -> None:
    """A pure helper a second screen needs moves to its home rather than being copied."""
    bullet = _bullet().lower()

    missing = [t for t in _TERMS if t not in bullet]
    assert not missing, (
        f"the Misplaced pure helper bullet no longer states {missing}. `second` "
        f"is the trigger — the class hides because each ticket touches one "
        f"screen, so the moment of reuse is the only moment both copies are "
        f"visible — and `before approval` is what stops the answer being "
        f"'someone will extract it later' (CAL-796/CAL-823)."
    )
    assert _NOT_COPIED.search(bullet), (
        "the bullet no longer refuses the screen-to-screen copy. The refusal is "
        "the rule: a version that names the designated home while tolerating "
        "the copy reads as advice, and advice is what the check replaced "
        "(CAL-823, #459)."
    )
