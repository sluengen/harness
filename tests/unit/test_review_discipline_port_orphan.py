"""CAL-665 / #459 — the Stage-2 **Port-time orphan** rule, as one tripwire.

From the 2026-06-13 code assessment. A dead ``card_factory`` (312 lines) entered
in the initial backend port and was never touched again — a class **no
per-change reviewer catches**, because no later change ever touches the orphan.
A whole module lifted from another repo that nothing in *this* repo imports is
dead on arrival, yet a per-change review only looks at what the change touched.
The rule is the port-time sibling of **Dead surface after a deletion**: grep the
source tree for a production importer, excluding the module and its tests.

**What this module asserts, after #459.** One tripwire over one rule-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*):

1. **Anchor** — the ``- **Port-time orphan**`` bullet exists inside
   ``### Stage 2``, and the assertion reads only that slice. **This is the whole
   defect #459 found here:** every assertion in the pre-conversion module
   searched the *entire* skill file, so ``production`` was satisfied by any of
   the fourteen neighbouring bullets and only ``dead on arrival`` was
   discriminating at all — the over-wide unit ``craft.md`` → *The text unit is
   part of the predicate* names.
2. **Term set** — ``lift``, ``production``, ``dead on arrival``: the trigger,
   the kind of caller that discharges it, and the verdict.
3. **Polarity** — the negation anchored to the *later* reviewer who will not
   catch this. That clause is why the check happens at port time rather than
   being left to per-change review, so an edit that dropped it would keep every
   term above while removing the rule's entire reason to exist here.
"""

from __future__ import annotations

import re

# The slicer lives in the module that exports it to this family rather than in a
# private copy per bullet (``craft.md`` → *A positive control must exercise the
# predicate, not re-implement it*); it carries its own missing-bullet assertion.
from tests.unit.test_review_discipline_context_currency import (
    _skill_text,
    _stage_two_bullet,
)

_BULLET_TITLE = "Port-time orphan"

#: The trigger, the caller that discharges it, and the verdict when there is none.
_TERMS = ("lift", "production", "dead on arrival")

#: The hides-per-change claim, with the negation **anchored to the reviewer or
#: change it governs**. A bare negation token would be satisfied by the grep
#: recipe's own exclusions; this only matches while the bullet still says the
#: class survives every later review, which is what makes port time the moment
#: to catch it.
_NO_LATER_REVIEWER = re.compile(
    r"\bno\b(?:\W+\w+){0,3}?\W+(?:later|future)\b", re.IGNORECASE
)


def _bullet() -> str:
    return _stage_two_bullet(_skill_text(), _BULLET_TITLE)


def test_the_port_orphan_rule_demands_a_production_importer_at_port_time() -> None:
    """A lifted module reached only by its own tests is dead on arrival."""
    bullet = _bullet().lower()

    missing = [t for t in _TERMS if t not in bullet]
    assert not missing, (
        f"the Port-time orphan bullet no longer states {missing}. Without the "
        f"lift trigger the rule has no moment; without a *production* importer "
        f"a passing unit test discharges it, which is precisely the evidence "
        f"the dead module already had (CAL-665)."
    )
    assert _NO_LATER_REVIEWER.search(bullet), (
        "the bullet no longer says the class escapes every later per-change "
        "review. That clause is the rule's direction — it is why the check is "
        "owed at the lift and not deferred — and an edit that drops it leaves a "
        "rule a reviewer can reasonably postpone forever (CAL-665, #459)."
    )
