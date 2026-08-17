"""``code-quality`` Part C: an over-limit file carries a justification or a ticket.

From the 2026-06-13 code assessment (CODE-INSIGHT-002). Two over-limit files
(plus two cohesive ones declined) showed the 500-line hard limit was treated as
advisory: none of them carried the justifying comment ``code-quality`` already
called for, so the steward re-found the same files each assessment cycle.

The rule added to the verification gate: a file over the hard limit must carry a
one-line ``# size: <reason>`` justification or a tracking ticket, else the
reviewer rejects it.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) the two functions collapse into
one — AC-2's "the rule is in Part C" was a strict subset of AC-1's whole-file
search, since both looked for the same ``# size:`` marker:

* the size subsection **exists inside Part C**, which is the placement claim;
* the terms the rule cannot be stated without: the concrete ``# size:`` marker
  form and the ``ticket`` alternative;
* the **rejection anchored to what is missing** — *rejects an over-limit file
  that has neither*. That is the polarity: a subsection carrying ``reject`` and
  ``neither`` in unrelated sentences describes a review step and imposes no bar.
  Occurrence it cites (``code-quality`` Part C, *A new guard cites the occurrence
  it prevents*): the rule exists because an unenforced convention read exactly
  like an enforced one from the guard's side — three bare substring checks over
  the whole file stayed green through the entire period the limit was advisory.

This module measures no file's length. Converting silent drift into an auditable
choice **on the source tree** is the walker's job
(``test_source_file_size_justification.py``), which enforces the ``# size:``
marker across the tracked index.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### A file over the hard limit is an auditable choice, not silent drift"

#: The rejection **anchored to the omission it answers**. Eight words is the gap
#: the legitimate spellings keep ("rejects an over-limit file that has neither");
#: further off, the rejection governs some other absence in the subsection.
_REJECTS_WHEN_NEITHER = re.compile(
    r"\breject\w*\b(?:\W+\w+){0,8}?\W+neither\b"
    r"|\bneither\b(?:\W+\w+){0,8}?\W+reject\w*\b",
    re.IGNORECASE,
)


def _size_section() -> str:
    """The Part C size subsection — its heading to the next ``###``.

    Sliced from ``## Part C``: the placement claim is carried by where the anchor
    is looked for, rather than by the separate whole-file assertion it replaces.
    """
    text = _SKILL.read_text(encoding="utf-8")
    part_c = text.find("## Part C")
    assert part_c != -1, "code-quality must have a Part C verification section"
    rest_of_part_c = text[part_c:]
    start = rest_of_part_c.find(_HEADING)
    assert start != -1, (
        f"code-quality's Part C must carry the size subsection {_HEADING!r} — the "
        "over-limit justification rule has no home without it"
    )
    rest = rest_of_part_c[start + len(_HEADING) :]
    end = rest.find("\n### ")
    section = rest if end == -1 else rest[:end]
    assert section.strip(), "the size subsection must not be empty"
    return section


def test_the_size_justification_rule_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the rejection (#459)."""
    section = _size_section()
    lower = section.lower()

    assert "# size:" in section, (
        "the rule must name the concrete `# size: <reason>` justification form "
        "for an over-limit file — a rule with no named marker cannot be checked "
        "by the walker that enforces it"
    )
    assert "ticket" in lower, (
        "the rule must accept a tracking ticket as the alternative to a `# size:` "
        "comment"
    )
    assert _REJECTS_WHEN_NEITHER.search(lower), (
        "the rule must state that the reviewer *rejects* an over-limit file that "
        "has neither, with the rejection anchored to the omission it answers. "
        "Without it the subsection describes a convention, which is precisely the "
        "advisory reading that let the steward re-find the same files every cycle"
    )
