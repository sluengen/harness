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
"Primitives over bespoke markup" section. This guard pins their substance so a
future edit cannot silently drop the anti-drift prose (the same pattern that
pins the dedup state in ``test_skill_boundary_dedup``).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "design-system" / "SKILL.md"


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


def test_composition_chrome_rule_present() -> None:
    """CAL-771 — the section flags composition chrome a value scan can't catch
    and applies the rule of three across files (grep first; extract at 3+)."""
    sec = _primitives_section()
    assert "composition" in sec.lower(), (
        "design-system 'Primitives over bespoke markup' must name the "
        "composition layer (sheet/header/card chrome) — CAL-771."
    )
    assert re.search(r"value scan|raw-value scan", sec), (
        "must say the duplication is invisible to a raw-value scan (every value "
        "is already a token) — CAL-771."
    )
    assert "three or more files" in sec, (
        "must extend the rule of three to compositions across three or more "
        "files, not just raw values — CAL-771."
    )


def test_finish_adoption_rule_present() -> None:
    """CAL-789 — extracting a primitive obliges migrating every callsite, or an
    explicit file:line follow-up of the un-migrated ones."""
    sec = _primitives_section()
    assert "partial adoption" in sec, (
        "design-system must name partial-adoption drift after an extraction "
        "— CAL-789."
    )
    assert re.search(r"every (one|callsite)", sec, re.I), (
        "must require migrating every callsite the primitive replaces — CAL-789."
    )
    assert "file:line" in sec, (
        "must require an explicit follow-up listing un-migrated callsites by "
        "file:line — CAL-789."
    )
