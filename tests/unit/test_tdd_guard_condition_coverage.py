"""RED carries a rule: cover each of a guard's trigger conditions.

Surfaced by an ``/assess code`` steward pass (2026-07-17, pass 3) against a
consuming repo: a multi-condition guard had two independent trigger paths —
refuse-vs-diverge — but its call site's suite only ever exercised one. Deleting
the other path's check left the suite green: 422 assertions, all satisfied by
the untested path alone. The guard *as a whole* was covered; one of its
conditions was not, and that untested half is exactly what let a real defect
through unseen.

**What this module asserts, after #459.** One tripwire over one rule-home — the
``**Cover each of a guard's … conditions**`` bullet of
``skills/test-driven-development/SKILL.md`` → ``### RED``, sliced to its own
paragraph — plus the structural agreement between the skill's stamp and its
registry row. The tripwire reads a small term set the rule cannot be stated
without, plus its polarity: a condition whose deletion leaves the suite
**green** is **untested**, asserted as an adjacency rather than as two free
tokens, because ``green`` and ``untested`` both have neighbours in RED and
either alone carries no direction.

Two things went with the conversion, and both were inert rather than merely
redundant:

* ``_PRIOR_VERSION = "0.4.0"`` and its ``header != _PRIOR_VERSION`` assertion —
  a frozen shipped version. It was live for one commit; every version the tree
  can now hold satisfies it, so it can no longer fail for any edit. The
  agreement half is what is durable and it is kept.
* the paragraph-adjacency pin (``between.count("\\n\\n") <= 1``), which asserted
  that no other bullet sits between this one and the active-loop bullet. A
  correct insertion into RED invalidates it while nothing about this rule
  changes — the ordinal-invalidated-by-insertion class ``craft.md`` names — and
  the ordering it encodes has no functional consequence for a reader.

Craft class this conversion answers: ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*. The eight-term
containment check this replaced had no anchored polarity, so a bullet stating
the opposite — that one test over a multi-condition guard suffices — reused its
vocabulary and passed (ADR 0016).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "test-driven-development" / "SKILL.md"
_REGISTRY = REPO_ROOT / "registry.yaml"

#: The rule's direction, as an adjacency rather than two free tokens: a
#: deletion that leaves the suite green means the condition is untested. Either
#: word alone appears elsewhere in RED and neither carries a direction on its
#: own; it is the binding between them that states the rule.
_GREEN_MEANS_UNTESTED = re.compile(
    r"\bgreen\b(?:\W+\w+){0,6}?\W+untested\b|\buntested\b(?:\W+\w+){0,6}?\W+green\b",
    re.IGNORECASE,
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _red_section(text: str) -> str:
    """The RED body: between its heading and the "Verify RED" heading."""
    start = text.index("### RED")
    end = text.index("### Verify RED", start)
    return text[start:end]


def _guard_condition_bullet(text: str) -> str:
    """The bullet, sliced to its own paragraph within the RED section."""
    red = _red_section(text)
    m = re.search(
        r"^\*\*Cover each of a guard's.*?conditions.*?\*\*", red, re.MULTILINE
    )
    assert m, (
        "test-driven-development RED has no bullet naming coverage of each "
        "of a guard's trigger conditions."
    )
    rest = red[m.start() :]
    nxt = re.search(r"\n\n", rest)
    return rest[: nxt.start()] if nxt else rest


def test_the_guard_condition_rule_has_a_home() -> None:
    """RED's guard-conditions bullet states the rule, with its direction.

    Three conjuncts and the polarity. ``independent`` is what makes the subject
    a multi-condition guard rather than any guard at all; ``condition`` is what
    the coverage is counted in, and a rule counted in tests instead is the
    posture that shipped the defect; ``delete`` is the proof procedure, without
    which the rule asks for tests and offers no way to tell whether they cover
    anything. The adjacency then carries the direction the terms cannot.
    """
    bullet = _guard_condition_bullet(_skill_text()).lower()

    for term, why in (
        ("independent", "the subject is a guard with several *independent* "
                        "trigger conditions, not any guard"),
        ("condition", "coverage is counted per condition; counted per guard, "
                      "the rule is the state the defect shipped under"),
        ("delet", "the rule must name its proof — delete each condition in turn "
                  "and watch a named assertion go red for it"),
    ):
        assert term in bullet, (
            f"RED's guard-conditions bullet no longer names {term!r} — {why}"
        )

    assert _GREEN_MEANS_UNTESTED.search(bullet), (
        "the bullet no longer states that a condition whose deletion leaves the "
        "suite green is *untested*. That binding is the rule's whole direction: "
        "a bullet saying a green suite after the deletion is reassuring reuses "
        "both words and reads the same to an unanchored guard."
    )


def test_version_matches_registry() -> None:
    """The skill's stamp and its registry row move together."""
    text = _skill_text()
    header_m = re.search(
        r"^<!-- guidance:test-driven-development@([\d.]+) -->", text, re.MULTILINE
    )
    assert header_m, "test-driven-development/SKILL.md must carry its version header"
    header_version = header_m.group(1)

    registry_text = _REGISTRY.read_text(encoding="utf-8")
    row_m = re.search(
        r"skills/test-driven-development/SKILL\.md:\s*\{[^}]*version:\s*([\d.]+)",
        registry_text,
    )
    assert row_m, "registry.yaml must carry a test-driven-development row"
    assert row_m.group(1) == header_version, (
        "registry.yaml's test-driven-development version must match the "
        "SKILL.md header (registry two-place self-version)"
    )
