"""design-system routes to the scaffold contract when no system exists yet.

*Source:* #239 creates ``templates/design-system.md`` (the scaffold contract);
this closes the loop by making ``skills/design-system/SKILL.md`` route to it
when ``paths.design_system`` is unset or dangling — the state every repo
starts in.

``_section`` is the same helper as ``test_design_system_composition.py``
(same file, same technique — duplicated rather than imported, since no test
module here imports another): an assertion scoped to one Markdown section
cannot be satisfied by a mention elsewhere in the file. That scoping is
load-bearing here — "licence to hardcode" already exists in Token
discipline, so a whole-file assertion would be green before this fallback
paragraph exists.
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

LOOKUP = "Before any visual change — two-stage lookup"


def _lookup_section() -> str:
    return _section(SKILL.read_text(encoding="utf-8"), LOOKUP)


def test_fallback_routes_to_the_scaffold_contract() -> None:
    """AC-1 — names the template and the key, states the unset trigger."""
    sec = _lookup_section()
    assert "templates/design-system.md" in sec, (
        "the lookup section must name templates/design-system.md as the "
        "fallback when there is no system yet."
    )
    assert "paths.design_system" in sec, (
        "the lookup section must name the CONTEXT.md key to read and set."
    )
    assert re.search(r"unset|not set", sec), (
        "the lookup section must state the unset trigger for the fallback."
    )


def test_fallback_trigger_covers_both_arms() -> None:
    """AC-1 — the trigger is unset *or* nothing at the named location, not
    just one of the two — a dangling path is the same state as unset."""
    sec = _lookup_section()
    assert re.search(r"nothing at|does not exist|no system at", sec), (
        "the fallback must also fire when paths.design_system names a "
        "location with nothing at it, not only when the key is unset."
    )


def test_fallback_instructs_setting_the_key() -> None:
    """AC-1 — the agent is told to set the key after standing the system
    up, not merely to read it."""
    sec = _lookup_section()
    assert re.search(r"set\s+.{0,40}paths\.design_system", sec), (
        "the fallback must instruct setting paths.design_system to where "
        "the scaffold landed, not just reading it."
    )


def test_fallback_carries_its_own_no_hardcode_clause() -> None:
    """AC-3 — the fallback restates the no-hardcode discipline inline, so a
    future trim of the paragraph cannot leave routing without discipline."""
    sec = _lookup_section()
    assert "not a licence to hardcode" in sec, (
        "the fallback paragraph must restate that a missing system is a "
        "gap to fill, not a licence to hardcode, inside the lookup section."
    )


def test_token_discipline_rule_undamaged() -> None:
    """AC-3 — the existing Token discipline rule is untouched: a
    'consolidating' edit that moves the rule into the new paragraph must
    not silently pass."""
    sec = _section(SKILL.read_text(encoding="utf-8"), "Token discipline")
    assert "never raw values" in sec
    assert "not a licence to hardcode" in sec


SCAFFOLD_TERMS = ("00-brand", "07-flows", "tokens.json", "archetype")


def _scope_creep_hits(section: str) -> list[str]:
    """The out-of-scope predicate: which scaffold-contract terms, if any,
    leak into a lookup-section body. Shared by the real guard and its teeth
    test, so the teeth test proves the *predicate* catches a leak — not just
    that a hand-built string happens to contain the term."""
    return [term for term in SCAFFOLD_TERMS if term in section]


def test_fallback_does_not_copy_in_scaffold_rules() -> None:
    """Out-of-scope guard — the lookup section stays a pointer; none of the
    scaffold contract's own layer/rule vocabulary leaks into it."""
    hits = _scope_creep_hits(_lookup_section())
    assert hits == [], (
        f"the lookup section must not absorb scaffold-contract rules "
        f"({hits} found) — #239 owns those, this skill only routes."
    )


def test_lookup_section_guard_has_teeth() -> None:
    """The out-of-scope guard is not green by construction: re-running the
    same predicate against a section with scaffold vocabulary injected must
    report the leak, proving the guard would actually catch it."""
    tampered = _lookup_section() + "\nUse tokens.json and the 00-brand layer directly."
    hits = _scope_creep_hits(tampered)
    assert hits == ["00-brand", "tokens.json"], hits


def test_lookup_section_is_non_empty() -> None:
    """Anti-vacuity — the parsed section is not empty, so the assertions
    above are not vacuously true against a blank string."""
    assert _lookup_section().strip(), "the two-stage lookup section parsed empty"
