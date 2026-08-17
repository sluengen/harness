"""CAL-1155 — ``review-discipline`` Stage 1: check the ticket's *current* criteria.

From proposal ``size-criterion-process`` (accepted 2026-07-17). The reviewer's
side of the renegotiation rule: Stage 1 checks the acceptance criteria as they
stand on the ticket *now*, and flags any amendment in the review report. A
criterion renegotiated only in a commit body or PR description — never amended on
the tracker issue — is a Stage 1 FAIL even when the engineering call is right,
because the canonical record (the ticket) is then wrong.

**What this module asserts, after #459.** One tripwire, over the numbered Stage 1
item that carries the rule — not over the whole Stage 1 section.

Occurrence the anchoring cites (``code-quality`` Part C), and it is the reason
ADR 0016 names this module by name: the pre-#459 form was two functions of term
co-occurrence over the **whole Stage 1 section**, and *both passed if the rule was
inverted*. ``current`` and ``criteria`` are the section's own subject matter;
``renegotiat`` and ``commit body`` survive any sentence *about* renegotiation,
including one permitting it; and ``FAIL`` was satisfied by the section's closing
line — *"If Stage 1 fails, stop. … Issue a FAIL."* — which has nothing to do with
this rule. So a Stage 1 rewritten to say a commit-body renegotiation is
acceptable left every assertion green. Scoping the read to the one numbered item
is what ties the verdict to the clause it belongs to. The ``craft.md`` class is
*A guard over prose owns structure and negative space, never meaning*.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"

#: The term the rule is *about*, used to select its item out of the numbered list.
#: Selecting by subject rather than by ordinal is deliberate: an ordinal into an
#: enumeration is invalidated by a correct insertion.
_RULE_TERM = "renegotiat"

#: The consequence, **anchored to the clause it governs**. ``FAIL`` alone is not
#: polarity here — Stage 1 ends by telling the reviewer to issue one — so it has
#: to be read next to the renegotiation it condemns.
_COMMIT_BODY_IS_A_FAIL = re.compile(
    r"commit body\b(?:\W+\w+){0,20}?\W+FAIL\b", re.DOTALL
)

#: …and the verdict is **not** negated. The window above proves ``commit body``
#: and ``FAIL`` sit in one clause; it says nothing about which way that clause
#: points, because a legitimate negation already lives inside it (*never amended
#: on the ticket*). So the polarity is asserted as an **absence** at the verdict
#: itself: no negation within a few words *before* ``FAIL``. Inserting one word —
#: *is **not** a Stage 1 FAIL* — inverts the rule while leaving the containment
#: window, the term set and ``never amended`` all intact, and the presence half
#: alone reads green on it (``craft.md`` → *The negation window assumes a false
#: converse*; measured under review of #459).
_VERDICT_NOT_A_FAIL = re.compile(
    r"\b(?:not|never|no|nor|neither)\b(?:\W+\w+){0,3}?\W+FAIL\b", re.IGNORECASE
)

#: The other half of the same clause: the amendment belongs on the ticket. A rule
#: that names the commit body without saying where the amendment *should* have
#: gone leaves the reviewer nothing to check against.
_NEVER_AMENDED = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,3}?\W+amend\w*\b", re.IGNORECASE
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage1_section() -> str:
    """The '### Stage 1' section — up to the next '### Stage 2' heading."""
    text = _skill_text()
    start = text.find("### Stage 1")
    assert start != -1, "review-discipline must have a '### Stage 1' section"
    end = text.find("### Stage 2", start)
    assert end != -1, "review-discipline must have a '### Stage 2' heading after it"
    return text[start:end]


def _criteria_currency_item() -> str:
    """The one numbered Stage 1 item stating the criteria-currency rule.

    Returns ``""`` when no item — or more than one — carries the subject, so an
    ambiguous window fails the tripwire rather than being silently widened to the
    section, which is what the pre-#459 form read.
    """
    items = [
        line.strip()
        for line in _stage1_section().splitlines()
        if re.match(r"^\d+\. ", line.strip()) and _RULE_TERM in line
    ]
    return items[0] if len(items) == 1 else ""


def test_stage1_checks_the_current_criteria_and_fails_a_commit_body_renegotiation() -> None:
    """The one tripwire: the rule, read from the item that states it (AC-1/AC-2).

    Four parts:

    * **anchor** — exactly one numbered Stage 1 item names renegotiation. Both
      halves of the rule live in that item; split across two, the verdict stops
      being attached to the clause it belongs to.
    * **terms** — ``current`` and ``criteria`` (review against the ticket as it
      stands now, not a remembered earlier version) and ``report`` (the amendment
      is surfaced, not silently accepted).
    * **polarity, part one** — ``FAIL`` anchored to ``commit body``, *and* the
      verdict not negated at the point it is stated. Read over the whole section
      the token is free: Stage 1's closing line issues a FAIL for an unrelated
      reason. Read as containment alone it is still free of direction, because
      the clause carries its own legitimate negation — which is why the
      absence half is a separate assertion with its own exclusive killer
      (``craft.md`` → *Every prose obligation needs a pair with separate
      exclusive killers*).
    * **polarity, part two** — a negation anchored to ``amend``: the criterion was
      never amended where it counts. That is what makes the commit body *only* a
      commit body.
    """
    item = _criteria_currency_item()
    assert item, (
        "review-discipline's Stage 1 does not carry exactly one numbered item "
        f"naming {_RULE_TERM!r}. The criteria-currency rule and its verdict are one "
        "clause — with none, the rule is gone; with two, the reviewer reads "
        "whichever it reaches first (CAL-1155)."
    )
    lowered = item.lower()

    missing = [term for term in ("current", "criteria", "report") if term not in lowered]
    assert not missing, (
        f"the Stage 1 criteria-currency item no longer states {missing}. The review "
        "runs against the acceptance criteria *as they stand on the ticket now*, "
        "and any amendment is surfaced in the review report (AC-1)."
    )

    assert _COMMIT_BODY_IS_A_FAIL.search(item), (
        "the Stage 1 criteria-currency item no longer makes a commit-body-only "
        "renegotiation a FAIL. This is the assertion the pre-#459 guard could not "
        "make: `FAIL` read anywhere in Stage 1 is satisfied by the section's own "
        "closing line, so the rule could be inverted — a renegotiation buried in a "
        "commit body accepted as sound — with nothing going red (AC-2)."
    )
    assert not _VERDICT_NOT_A_FAIL.search(item), (
        "the Stage 1 criteria-currency item negates its own verdict — a "
        "commit-body-only renegotiation is written as *not* a FAIL. The "
        "containment window above cannot see this: `commit body` and `FAIL` are "
        "still one clause, and the clause's legitimate negation (*never amended "
        "on the ticket*) sits between them, so presence alone reads green on the "
        "one-word inversion (#459 review)."
    )
    assert _NEVER_AMENDED.search(item), (
        "the item no longer says the criterion was never amended on the ticket. "
        "Without it the rule condemns writing in a commit body rather than "
        "*failing to amend the canonical record*, which is the thing that makes a "
        "Done ticket a false record (AC-2)."
    )
