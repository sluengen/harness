"""#194, #208 / #459 — the Stage-2 **Partial hook/utility adoption** rule, as one tripwire.

Surfaced by nano-erp's ``/assess code`` pass. A call site imports a hook built to
replace a hand-rolled pattern — ``useResource`` replacing a hand-rolled
write-refusal/pending sequence — destructures only part of its return value and
reimplements the rest by hand, silently reopening the defect the unused part
existed to close. Nothing catches it: the file compiles (unused fields simply
are not destructured) and the tests pass (nothing exercises the missing state).
#208 then widened the trigger, because twice in one range the call site never
imported the hook at all: a screen that imports nothing has nothing to
destructure, so a trigger scoped to "a call site imports the hook…" never fires
for the worse case.

**What this module asserts, after #459.** One tripwire over one rule-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*):

1. **Anchor** — the ``- **Partial hook/utility adoption**`` bullet exists inside
   ``### Stage 2``, and the assertion reads only that slice.
2. **Term set** — ``hand-rolled``, ``reimplement``, ``sibling``: what the shared
   hook replaced, the defect, and the comparison that surfaces it.
3. **Polarity** — ``whether or not it is imported at all``, with the negation
   anchored to the import it governs. This is #208's entire content, and it is
   the direction: the check's applicability is **not** conditioned on the
   import. Re-narrowing the trigger to call sites that already import the hook
   keeps every term above and reverts the rule to the version that missed both
   recorded instances — the inversion-passes class ``craft.md`` → *Mutate the
   rule into its opposite, not only out of existence* names.

What went: ``hook``, ``destructures``/``contract``, ``data-fetching``/
``write-then-refetch`` and ``imported`` as separate literal pins, and
``test_partial_hook_adoption_rule_is_in_stage_two`` (a placement re-check the
slicer performs by construction). The bullet-ordering test went too — it asserted
``mirrors_idx < partial_idx < watchlist_idx``, which encodes no rule and is
invalidated by any correct insertion (``craft.md`` → *An ordinal reference into
an enumeration is invalidated by a correct insertion*).
"""

from __future__ import annotations

import re

from tests.unit._prose import diff_shape_checks_text, stage_two_bullet

_BULLET_TITLE = "Partial hook/utility adoption"

#: What the shared hook was built to replace, the defect, and the comparison
#: that makes it visible.
_TERMS = ("hand-rolled", "reimplement", "sibling")

#: #208's breadth claim, with the negation **anchored to the import it
#: governs**. A bare negation token would be satisfied by the "not
#: reimplementing the rest by hand" clause; this only matches while the check
#: still applies to a call site that never imported the hook at all.
_WHETHER_OR_NOT_IMPORTED = re.compile(
    r"\bwhether or not\b(?:\W+\w+){0,4}?\W+import\w*\b", re.IGNORECASE
)


def _bullet() -> str:
    return stage_two_bullet(diff_shape_checks_text(), _BULLET_TITLE)


def test_the_partial_adoption_rule_applies_whether_or_not_the_hook_is_imported() -> None:
    """The check fires on the shape of the flow, not on an existing import."""
    bullet = _bullet().lower()

    missing = [t for t in _TERMS if t not in bullet]
    assert not missing, (
        f"the Partial hook/utility adoption bullet no longer states {missing}. "
        f"The hand-rolled pattern is what the shared hook replaced, "
        f"reimplementing it beside the hook is the defect, and the sibling call "
        f"sites are the only place the gap is visible — a partial adoption "
        f"compiles and its tests pass (#194)."
    )
    assert _WHETHER_OR_NOT_IMPORTED.search(bullet), (
        "the bullet no longer states that the check applies whether or not the "
        "shared hook is imported at all. Re-narrowed to call sites that already "
        "import it, the rule reverts to the version that missed both recorded "
        "instances outright: a screen that imports nothing has nothing to "
        "destructure, so the trigger never fires for the worse case (#208, #459)."
    )
