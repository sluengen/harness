"""CAL-771 / CAL-789 — design-system flags composition chrome and finishes adoption.

*Source:* ``/assess code`` mobile assessments, insights CODE-INSIGHT-001 (CAL-771)
and CODE-INSIGHT-1 (CAL-789).

Two drift classes pass every automated gate yet still fork the design:

* **CAL-771 — composition chrome.** A sheet header, card shell, or list row is a
  *composition* of token rules; every value is already a token, so a raw-value
  scan sees nothing wrong even when the same composition is reimplemented inline
  across many files. The duplication lives at the composition layer, invisible
  to a value scan.
* **CAL-789 — partial adoption.** A primitive extracted from N inline copies but
  adopted at only a subset of callsites leaves the inline copies as a maintained
  second source of truth — drift the value scan cannot see.

Both fixes are guidance edits to the universal ``design-system`` skill, in its
"Primitives over bespoke markup" section.

**What this module asserts (#459).** One tripwire over one rule-home. Both
drift classes live in the same section, so two sentence-pin functions over one
already-scoped slice were one guard written twice (``code-quality`` Part C →
*A guard over prose owns structure and negative space, never meaning*; ADR
0016 → *one tripwire per rule-home, not per sentence*). Polarity **does**
exist here, contrary to the triage note that produced this conversion: the
whole point of both classes is that the value scan **cannot** see the
duplication, so the negation is bound to ``scan`` rather than left loose over
the paragraph.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "design-system" / "SKILL.md"

_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def _section(text: str, heading: str) -> str:
    """The body of the Markdown section whose heading text equals ``heading``,
    up to the next heading of the same-or-higher level, a horizontal rule, or
    EOF — so an assertion is scoped to one section and a mention elsewhere in
    the file cannot satisfy it."""
    lines = text.splitlines()
    start: int | None = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"(#+)\s+(.*)$", line)
        if m and m.group(2).strip() == heading:
            start, level = i + 1, len(m.group(1))
            break
    assert start is not None, f"section heading not found: {heading!r}"
    body: list[str] = []
    for line in lines[start:]:
        m = re.match(r"(#+)\s+", line)
        if (m and len(m.group(1)) <= level) or line.strip() == "---":
            break
        body.append(line)
    return "\n".join(body)


def _primitives_section() -> str:
    return _section(SKILL.read_text(), "Primitives over bespoke markup")


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of this module's #459
    mutation table surfaced exactly that: an inverted clause survived on a
    negation belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


def test_primitives_section_flags_the_drift_a_value_scan_misses() -> None:
    """Tripwire — the section names both drift classes and their remedies.

    Terms the two rules cannot be stated without: ``composition`` and ``value
    scan`` (CAL-771's class and why a gate misses it), ``three or more files``
    (the extraction threshold), ``partial adoption`` and ``file:line``
    (CAL-789's class and the follow-up it demands). Polarity: a sentence
    naming the scan carries a negation — the duplication is what the scan
    *cannot* see. A section that claimed the value scan already catches
    composition drift would name every term above and mean the opposite.
    """
    sec = _primitives_section()
    lowered = sec.lower()
    for term in (
        "composition",
        "value scan",
        "three or more files",
        "partial adoption",
        "file:line",
    ):
        assert term in lowered, (
            "design-system's 'Primitives over bespoke markup' must state the "
            f"composition/adoption drift rules in terms of {term!r} "
            "(CAL-771 / CAL-789)."
        )
    scan_sentences = [s for s in _sentences(lowered) if "scan" in s]
    assert scan_sentences, "no sentence in the section names the scan."
    assert any(_NEGATION.search(s) for s in scan_sentences), (
        "the section must say what the value scan does *not* see — that "
        "negation is the whole reason both rules exist, and without it the "
        "term set reads identically on prose claiming the scan covers this "
        "(CAL-771 / CAL-789)."
    )
