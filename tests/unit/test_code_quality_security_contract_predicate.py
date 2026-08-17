"""``code-quality`` Part C: a security-contract test asserts the predicate, not the name.

*Source:* nano-erp assessment ``assessments/2026-07-22-code.md``, systemic
insight CODE-INSIGHT-1. The tenancy gate the whole repo leans on
(``test/catalog_security.test.ts``) verified a policy *called* ``tenant_fence``
exists — it never read ``qual``/``with_check``, so ``tenant_fence ... using
(true)`` passed. Asserting a control exists by name proves only that someone
typed the right string; the predicate it evaluates to is what a defect actually
changes.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) four functions — two of which
asserted the *identical* literal heading — collapse into one tripwire:

* the subsection **exists inside Part C**, located by a heading prefix rather
  than by its full text. The prefix stops at ``asserts the predicate``, so the
  contrastive half of the heading stays *inside the reading window* and can be
  asserted rather than assumed. Pinning the whole heading string as the anchor
  would have made the polarity below tautological — the defect the old
  ``"security-contract test asserts the predicate, not the name" in low`` pair
  had twice over;
* a term set the rule cannot be stated without (``by name``, the concrete
  ``USING``/``WITH CHECK`` predicate, ``negative fixture``);
* the **negation anchored to what is being excluded** — *not the name*. A
  heading reworded to "asserts the predicate **and** the name" still resolves the
  anchor and fails here, which is the inversion no substring pin could see.
  Occurrence it cites (``code-quality`` Part C, *A new guard cites the occurrence
  it prevents*): the rule this file guards is itself about a test that asserted a
  control by name and never read what it evaluated to.

The SKILL.md → references link stays as its own assertion: it is **structural
correspondence** (a pointer and its target), which ADR 0016 exempts.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

#: The anchor, deliberately a *prefix* of the heading: everything after
#: ``predicate`` is content this module reads rather than content it assumes.
_HEADING = re.compile(r"^###\s+A security-contract test asserts the predicate\b", re.MULTILINE)

#: The exclusion **anchored to what is excluded**. "not the name" is the whole
#: rule; a window carrying a negation somewhere and the word *name* somewhere is
#: satisfied by any paragraph about naming.
_NOT_THE_NAME = re.compile(r"\b(?:not|never|no)\b(?:\W+\w+){0,2}?\W+the name\b", re.IGNORECASE)


def _code_quality_text() -> str:
    return CODE_QUALITY.read_text()


def _section() -> str:
    """The subsection's span, from its own heading to the next ``###``.

    Sliced from ``## Part C`` so placement is carried by the anchor rather than
    by a separate assertion, and started *at* the heading rather than after it so
    the heading's contrastive clause is inside the reading window.
    """
    text = _code_quality_text()
    part_c = re.search(r"^##\s+Part C\b", text, re.MULTILINE)
    assert part_c, "code-quality must have a 'Part C — Verification' section."
    rest_of_part_c = text[part_c.start() :]
    m = _HEADING.search(rest_of_part_c)
    assert m, (
        "code-quality's Part C must carry the security-contract subsection — a "
        "heading beginning 'A security-contract test asserts the predicate'"
    )
    rest = rest_of_part_c[m.start() :]
    nxt = re.search(r"^###\s", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_the_security_contract_rule_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the exclusion (#459)."""
    low = _section().lower()

    assert _NOT_THE_NAME.search(low), (
        "the rule must say the test asserts the predicate and *not* the name, "
        "with the negation anchored to what it excludes. A subsection that asks "
        "for the predicate alongside the name is the rule inverted, and it "
        "carries every other term below unchanged"
    )
    assert "by name" in low, (
        "the rule must call out that asserting a control exists 'by name' proves "
        "only that someone typed the right string"
    )
    assert "using" in low and "with check" in low, (
        "the rule must name the concrete predicate a security-contract test "
        "should assert, e.g. an RLS policy's USING/WITH CHECK expression"
    )
    assert "negative fixture" in low, (
        "the rule must require pairing the assertion with a negative fixture "
        "whose control is present but wrong, and watching the test fail — "
        "without it the assertion is never proven able to fail"
    )


def test_specialized_reference_is_linked_from_the_hot_skill() -> None:
    """Structural correspondence: the conditional reference has a live pointer."""
    core = (REPO_ROOT / "skills" / "code-quality" / "SKILL.md").read_text()
    assert "references/specialized-verification.md" in core, (
        "the hot code-quality skill must link the conditional verification reference"
    )
