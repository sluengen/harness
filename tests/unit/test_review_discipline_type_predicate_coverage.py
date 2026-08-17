"""#181 / #459 — the Stage-2 **Type predicate coverage** rule, as one tripwire.

TypeScript takes ``value is T`` on faith — it cannot check a user-defined type
predicate against the type it asserts. In the nano-erp assessment,
``isMeResponse`` validated four of six required fields and nothing (compiler,
reviewer, tests) caught it; it was the highest-severity finding in that pass and
had survived two prior reviews. The failure mode is entirely mechanical —
enumerate the asserted type's required fields and check the guard covers each
one — so it belongs in the review checklist.

**What this module asserts, after #459.** One tripwire over one rule-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*):

1. **Anchor** — the ``- **Type predicate coverage**`` bullet exists inside
   ``### Stage 2``, and the assertion reads only that slice.
2. **Term set** — ``type predicate``, ``required fields``, ``subset``: the
   subject, the enumeration it is checked against, and the defect shape. The
   rule cannot be stated without all three.
3. **Polarity** — ``a defect, not a nit``, with the negation anchored to the
   noun it governs. This is the load-bearing half: the whole point of the rule
   is the *grade*, and a rewrite that downgraded a subset-validating predicate
   to a nit would keep every term above while inverting the rule. That
   inversion is what ``craft.md`` → *Mutate the rule into its opposite, not only
   out of existence* names, and it is the occurrence #459 converted this module
   to close.

What went: ``value is t`` and ``false assurance`` were exact-phrase pins that
break on a benign rewording while proving nothing about direction, and
``test_type_predicate_rule_is_in_stage_two`` re-derived the very slice the
bullet reader performs — a strict subset of the slicer, so it could only fail
where the slicer already fails.
"""

from __future__ import annotations

import re

from tests.unit._prose import diff_shape_checks_text, stage_two_bullet

_BULLET_TITLE = "Type predicate coverage"

#: The subject, the enumeration it is measured against, and the defect shape.
_TERMS = ("type predicate", "required fields", "subset")

#: The grade, with the negation **anchored to the noun it governs**. A bare
#: negation token anywhere in the paragraph would be satisfied by the sentence
#: that describes the defect; this only matches while the bullet still refuses
#: to call a subset-validating predicate a nit. Reversing the pair — "a nit, not
#: a defect" — puts ``nit`` before ``not`` and no longer matches.
_NOT_A_NIT = re.compile(r"\bnot\b(?:\W+\w+){0,2}?\W+nit\b", re.IGNORECASE)


def _bullet() -> str:
    return stage_two_bullet(diff_shape_checks_text(), _BULLET_TITLE)


def test_the_type_predicate_rule_grades_a_subset_as_a_defect() -> None:
    """A predicate validating a subset of `T`'s required fields is a defect, not a nit."""
    bullet = _bullet().lower()

    missing = [t for t in _TERMS if t not in bullet]
    assert not missing, (
        f"the Type predicate coverage bullet no longer states {missing}. The rule "
        f"is the enumeration — every required field of the asserted type, checked "
        f"against the guard — and a rule missing the subject or the measure is a "
        f"reminder, not a check (#181)."
    )
    assert _NOT_A_NIT.search(bullet), (
        "the bullet no longer grades a subset-validating predicate a defect "
        "rather than a nit. The grade is the rule: `value is T` compiles either "
        "way, so a predicate demoted to a nit is one a reviewer waves through "
        "at exactly the boundary it was added to protect (#181, #459)."
    )
