"""#285 — feature specs cannot hand-list a code-owned set without a guard.

**What this module asserts, after #459.** One tripwire over one rule-home —
``skills/spec-authoring/SKILL.md`` → ``## Feature spec`` — plus the
version/registry correspondence, which is structural and untouched. The tripwire
is the negation anchored to the verb it governs (a record *must not* enumerate a
set the code owns) together with the sanctioned alternative (name the owning
module, or pair the list with a guard that **derives** it). Whether the prose
argues the rule well is the review gate's, per ADR 0016.

Craft class this conversion answers (``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*): the deleted
``test_feature_spec_rule_prevents_hand_listed_code_owned_sets`` pinned three
sentence fragments verbatim, and the deleted
``test_feature_spec_guard_tokens_were_absent_before_this_change`` asserted that
three example nouns from the pre-change tree were present — a non-vacuity
control that, once the rule shipped, became identical in effect to the home
assertion it was guarding and could only ever fail together with it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The rule's direction, anchored to the verb it governs. A paragraph merely
#: containing a negation and the word "enumerate" somewhere states nothing; what
#: the rule says is that enumerating is the thing an as-built record may not do.
_MUST_NOT_ENUMERATE = re.compile(
    r"\b(?:must not|never|not|cannot|may not)\b(?:\W+\w+){0,4}?\W+enumerat\w+",
    re.IGNORECASE,
)


def _feature_spec_section() -> str:
    """The ``## Feature spec`` section, bounded by the next top-level heading.

    Matched as a whole heading rather than split on a substring, so a renamed
    section fails with a named assertion instead of an ``IndexError`` from the
    split that missed.
    """
    text = SKILL.read_text()
    m = re.search(r"^##\s+Feature spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Feature spec' section"
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_the_code_owned_set_rule_has_a_home() -> None:
    """The Feature spec section forbids hand-listing a set the code owns.

    Three conjuncts, in one section. The negation carries the direction; ``owns``
    is what scopes the ban to sets the code is the authority on rather than to
    every list a spec may contain; and ``guard``/``derive`` is the sanctioned
    escape, without which the rule bans the useful list instead of pricing it.
    """
    section = _feature_spec_section()
    assert _MUST_NOT_ENUMERATE.search(section), (
        "spec-authoring's '## Feature spec' section no longer states that an "
        "as-built record must *not* enumerate a code-owned set. Term "
        "co-occurrence has no direction — without the negation beside the verb, "
        "a section inviting the enumeration would read the same to this guard."
    )
    lower = section.lower()
    assert "owns" in lower, (
        "the ban must be scoped to a set the *code* owns; unscoped, it forbids "
        "every list an as-built record legitimately carries"
    )
    assert "guard" in lower and re.search(r"\bderiv\w+", lower), (
        "the rule must offer the sanctioned form — pair the list with a guard "
        "that derives the set from the code — or a spec author routes around a "
        "prohibition that leaves the reader nothing"
    )


def test_spec_authoring_version_agrees_with_the_registry() -> None:
    """The skill's stamp and its registry entry move together.

    This pinned both to the literal ``0.10.1`` until #321 — the version #285
    happened to land at. That literal was not the invariant: a *correct* later
    edit to the skill, which must bump both, failed this test, and the only way
    to pass was to retype the new version here, re-arming the trap for the next
    edit. What is durable is the **agreement**: a stamp that drifts from the
    registry entry is how a consuming repo pulls a file whose version says it
    already has it.
    """
    header = re.search(r"guidance:spec-authoring@([\d.]+)", SKILL.read_text())
    entry = re.search(
        r"skills/spec-authoring/SKILL\.md:\s*\{[^}]*version:\s*([\d.]+)",
        REGISTRY.read_text(),
    )
    assert header and entry
    assert header.group(1) == entry.group(1)
