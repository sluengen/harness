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

**What this module asserts (#459).** Two things, and neither is meaning.
*Negative space:* the lookup section stays a **pointer** and does not absorb
the scaffold contract's own layer vocabulary — that sweep and the control
that proves its predicate has teeth are unchanged. *One tripwire:* the lookup
section names the scaffold contract and the ``CONTEXT.md`` key, with the
no-hardcode negation bound to the sentence that mentions hardcoding. The five
sentence-pins that stood here before (each arm of the trigger, the set-the-key
instruction, the ``"not a licence to hardcode"`` literal, the Token-discipline
re-read) were one rule-home pinned five ways: brittle to a rewording that
preserved the rule and silent on an edit that inverted it (``code-quality``
Part C → *A guard over prose owns structure and negative space, never
meaning*; ``craft.md`` → *Mutate the rule into its opposite, not only out of
existence*). The anti-vacuity floor folds into the tripwire — a term set over
an empty slice fails on the terms.
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

LOOKUP = "Before any visual change — two-stage lookup"


def _lookup_section() -> str:
    return _section(SKILL.read_text(encoding="utf-8"), LOOKUP)


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


def test_lookup_section_routes_to_the_scaffold_contract() -> None:
    """Tripwire — the lookup section routes a repo with no system to the
    scaffold contract, and keeps the discipline that routing does not relax.

    Terms: ``templates/design-system.md`` (where to go) and
    ``paths.design_system`` (the ``CONTEXT.md`` key to read and set). Polarity:
    the sentence that mentions hardcoding carries the negation — a missing
    system is a gap to fill, *not* a licence to hardcode. That binding is what
    a term co-occurrence cannot do: the same two names appear just as happily
    in a paragraph that told an agent to hand-author values until a system
    exists.
    """
    sec = _lookup_section()
    for term in ("templates/design-system.md", "paths.design_system"):
        assert term in sec, (
            f"the two-stage lookup section must name {term!r} as part of the "
            "no-system-yet route."
        )
    hardcode = [s for s in _sentences(sec) if re.search(r"hardcod", s, re.I)]
    assert hardcode, (
        "the lookup section must state what a missing system does *not* licence "
        "— without it, routing ships with no discipline attached."
    )
    assert any(_NEGATION.search(s) for s in hardcode), (
        "the hardcoding clause must carry its negation inside the lookup "
        "section: a missing system is a gap to fill, not a licence to hardcode."
    )


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
