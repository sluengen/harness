"""``code-quality`` Part C: how a tripped size limit may be answered.

Part C's *A file over the hard limit is an auditable choice, not silent drift*
establishes the enforcement ordering (linter → walker → steward) and the
``size:`` marker contract. Every one of its rules governs a file that **is**
over the limit; none of them reaches a file shaved to just under one.

That gap has a predictable exploit, because a line-count gate is cheapest to
satisfy by removing declarations: merging two named units is always cheaper
than separating three concerns. In a consuming repo a 459-line route component
tripped a mechanized crowded-threshold guard, and the next commit brought it to
exactly 450 by deleting a named component and inlining its body into its
caller — gate green, three mixed concerns unchanged, one fewer named unit than
before. The rule traded away to satisfy Part C's was Part B's *Compose, don't
inline*, in the same skill, and nothing said that was the wrong move.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) three sentence-pins over one
answer paragraph — and the exact-phrase paragraph selector that found it —
collapse into one tripwire over the subsection:

* the subsection **exists inside Part C**;
* the terms the rule cannot be stated without: the quantifier ``exactly two``,
  the ``size:`` exemption, the ``concern`` the split is by, and the *Compose,
  don't inline* rule it trades against;
* the **polarity** — *never answered* by reducing the count in place. That is the
  only assertion here that reads a direction: flipping ``never`` to
  ``sometimes`` turns the rule into permission for the exploit it forbids while
  leaving every term above intact. Occurrence it cites (``code-quality`` Part C,
  *A new guard cites the occurrence it prevents*): measured on the review that
  wrote this rule, deleting it and adding one ordinary sentence in its place —
  "a reviewer comparing the walker's report against the linter's diff will reach
  the same finding twice" — left a section-scoped ``diff``/``finding`` assertion
  green, which is why those two words are no longer asserted at all.

The Part B target's existence stays as its own assertion: the rule names
*Compose, don't inline* in prose, so pointer-and-target is **structural
correspondence**, which ADR 0016 exempts.

**Acknowledged limit.** A sentence *added* inside the subsection that blesses the
shave outright ("where neither is convenient, deleting lines until the file fits
is an acceptable third answer") leaves every anchor here intact and is not
detectable by any substring predicate. This guard pins that the rule is stated
and stated the right way round; that it is not contradicted two sentences later
is reviewer judgment — the same presence-mechanized / substance-judged line Part
C draws for the ``size:`` marker itself.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### A file over the hard limit is an auditable choice, not silent drift"

# Part B's composition rule, cited verbatim so a rename there breaks this guard
# rather than leaving it pointing at a heading that no longer exists.
_PART_B_RULE = "### Compose, don't inline"

#: Polarity, not vocabulary. Flipping ``never`` to ``sometimes`` inverts the rule
#: into permission for the exact exploit it forbids while leaving every other
#: anchor in this module intact.
_NEVER_ANSWERED = re.compile(r"\bnever\b(?:\W+\w+){0,2}?\W+answered\b", re.IGNORECASE)


def _size_section() -> str:
    """The Part C size subsection — its heading to the next ``###``.

    Sliced from ``## Part C`` so placement rides on the anchor rather than on a
    separate assertion.
    """
    text = _SKILL.read_text(encoding="utf-8")
    part_c = text.find("## Part C")
    assert part_c != -1, "code-quality must have a '## Part C' verification section"
    rest_of_part_c = text[part_c:]
    start = rest_of_part_c.find(_HEADING)
    assert start != -1, (
        f"code-quality's Part C must carry the size subsection {_HEADING!r}; the "
        "size-limit response rule has no home without it"
    )
    rest = rest_of_part_c[start + len(_HEADING) :]
    end = rest.find("\n### ")
    section = rest if end == -1 else rest[:end]
    assert section.strip(), "the size subsection must not be empty"
    return section


def test_the_size_limit_response_rule_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the polarity (#459)."""
    lower = _size_section().lower()

    assert "exactly two" in lower, (
        "the subsection must say a tripped limit is answered in *exactly two* "
        "ways — an open-ended list of answers is not a rule, and the third answer "
        "it leaves room for is the one this rule exists to forbid"
    )
    assert "concern" in lower, (
        "it must say the split is *by concern*; splitting a file anywhere to get "
        "under a number is the same trade this rule forbids"
    )
    assert "size:" in lower, (
        "it must name recording the `size:` exemption as the second legitimate "
        "answer, alongside splitting — naming only the split leaves the honest "
        "move for a file that should stay long unstated"
    )
    assert _NEVER_ANSWERED.search(lower), (
        "the rule must state that a size limit is *never answered* by reducing "
        "the count in place, with the negation anchored to the verb it governs. "
        "A subsection that merely discusses reducing the count in place carries "
        "the same words and the opposite rule"
    )
    assert _PART_B_RULE.removeprefix("### ").lower() in lower, (
        f"the rule must tie the prohibition to Part B's {_PART_B_RULE!r} — that "
        "is the rule being traded away to satisfy this one, and naming it is "
        "what makes the trade visible"
    )


def test_the_cited_part_b_rule_still_exists() -> None:
    """Structural correspondence: the rule cites *Compose, don't inline* by name."""
    core = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
    assert _PART_B_RULE in core.read_text(encoding="utf-8"), (
        f"Part B must still carry {_PART_B_RULE!r}; the size-limit response rule "
        "cites it by name, and a cite whose target is gone points nowhere"
    )
