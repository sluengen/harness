"""``code-quality`` Part C: a linter enforces the file-size limit where it can.

The Part C size rule requires an over-limit file to carry a ``size:``
justification, and the presence/substance amendment mechanized *presence* as a
tree-walking repo test. What neither said is which mechanism to reach for first:
where the repo's linter already implements a file-length rule (``max-lines`` in
ESLint or oxlint), turning that rule on beats writing a bespoke walker — it runs
with the rest of lint on every commit, and its escape hatch (an inline disable
carrying the ``size:`` reason) has a property the walker cannot offer: an unused
disable is itself reported, so a file that shrinks back under the limit cannot
silently keep its exemption.

In nano-erp a 725-line file (44% over the hard limit) passed both a review and a
green gate, and a repo-wide grep for the ``// size:`` marker returned zero
matches — the rule was enforced only by the weekly advisory pass. The steward is
the backstop where no linter and no walker can run, not the primary.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) three functions that
co-occurrence-tested the whole of Part C collapse into one tripwire, narrowed
from ``## Part C`` to the size subsection that actually owns this rule:

* the subsection **exists inside Part C**, and the ordering rule is read from
  that slice rather than from the rest of the file;
* a term set the rule cannot be stated without (``linter``, ``max-lines``,
  ``disable``, ``unused``);
* the **ordering, anchored** — *the backstop **only** where neither mechanism can
  run*. That quantifier is the rule: a section calling the steward the backstop
  without it describes the same three mechanisms and licenses the advisory pass
  as primary, which is the arrangement that let a 44%-over file ship green.
  Occurrence it cites (``code-quality`` Part C, *A new guard cites the occurrence
  it prevents*): the predecessor asserted ``"backstop" in lower`` over the whole
  of Part C, which survives every reordering of the three mechanisms.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### A file over the hard limit is an auditable choice, not silent drift"

#: The steward's place in the ordering, **anchored to the quantifier that makes
#: it last**. Three words is the gap the legitimate spellings keep ("the backstop
#: only where...", "the backstop, but only where..."); further off, the *only*
#: is qualifying something else in the paragraph.
_BACKSTOP_ONLY = re.compile(r"\bbackstop\b(?:\W+\w+){0,3}?\W+only\b", re.IGNORECASE)


def _size_section() -> str:
    """The Part C size subsection — its heading to the next ``###``.

    Sliced from ``## Part C`` so placement rides on the anchor. Scoped to the
    subsection rather than to the whole of Part C: ``linter``, ``disable`` and
    ``backstop`` are ordinary vocabulary in a part about verification gates, so a
    Part-C-wide search is satisfied by prose that is not this rule.
    """
    text = _SKILL.read_text(encoding="utf-8")
    part_c = text.find("## Part C")
    assert part_c != -1, "code-quality must have a '## Part C' verification section"
    rest_of_part_c = text[part_c:]
    start = rest_of_part_c.find(_HEADING)
    assert start != -1, (
        f"code-quality's Part C must carry the size subsection {_HEADING!r}; the "
        "linter-first enforcement ordering has no home without it"
    )
    rest = rest_of_part_c[start + len(_HEADING) :]
    end = rest.find("\n### ")
    section = rest if end == -1 else rest[:end]
    assert section.strip(), "the size subsection must not be empty"
    return section


def test_the_enforcement_ordering_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the ordering (#459)."""
    lower = _size_section().lower()

    assert "linter" in lower, (
        "the size subsection must name the linter as the mechanism that enforces "
        "the file-size limit where it can"
    )
    assert "max-lines" in lower, (
        "it must name the concrete rule (`max-lines`) so an adopting repo can "
        "turn it on without guessing"
    )
    assert "disable" in lower, (
        "it must state the linter escape hatch is an inline rule-disable, so an "
        "over-limit file is still an auditable choice"
    )
    assert "unused" in lower, (
        "it must state that an *unused* disable is itself reported — the property "
        "that stops a file which shrank back from silently keeping its exemption"
    )
    assert _BACKSTOP_ONLY.search(lower), (
        "the steward must be the backstop *only* where neither mechanism can "
        "run, with the quantifier anchored to the word it bounds. Naming the "
        "steward a backstop without it leaves the three mechanisms in any order, "
        "and the order it permits is the advisory weekly pass as primary — how a "
        "file 44% over the hard limit passed a review and a green gate"
    )
