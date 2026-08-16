"""``spec-driven-development``: the as-built record cannot arrive late.

A missing join between two shipped tickets is invisible from inside either
ticket. In one consuming repo, one ticket built the receiving end of a share
flow and another built the list — each met every criterion — but no record
described the *flow*, so the missing link went unseen until an assessment wrote
the record six tickets late. The as-built record is where a gap between tickets
becomes visible, and it cannot do that job retroactively.

The rule lives at the reviewer's record step (step 8): when a surface's as-built
record does not exist yet, the first ticket touching that surface creates it,
and a surface is not permitted to accumulate more than one shipped ticket
without one. It is worded layer-aware, so it holds for a ``feature_specs``-on
repo (a feature spec in ``specs/features/``) and a ``feature_specs``-off one
(the design doc / ``SPEC.md``).

**What this module asserts, after #459.** One tripwire over one rule-home:
numbered step 8 of ``skills/spec-driven-development/SKILL.md``, sliced to the
step and read for a small term set plus **two negations, each anchored to the
noun it governs** — the record that does *not* exist yet, and the surface that
is *not* permitted to accumulate a second shipped ticket. Anchoring is the
point: the four functions this replaced were term co-occurrence, and term
co-occurrence has no direction, so a step 8 that permitted the accumulation
passed them all (ADR 0016).

Craft class this conversion answers (``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Three of the deleted
functions pinned the same rule into three further homes —
``skills/review-discipline/SKILL.md``, ``agents/reviewer.md`` and
``commands/review.md`` — by whole-file containment of phrases like
``"second shipped ticket"``. That is one rule pinned in four places by its
bytes: it made every rewording a four-file edit, while none of the three
propagation checks could tell whether the phrase sat in the reviewer's record
step or in an unrelated paragraph of the same file. Whether the operating
surfaces still carry the rule where a reviewer meets it is a placement question
about *those* files, and it belongs to a tripwire anchored in them, not to a
substring search run from here.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "spec-driven-development" / "SKILL.md"

#: The trigger's direction, anchored to the noun it governs: the gate fires on a
#: surface whose record does **not** exist. A bare negation over a paragraph this
#: long would be decoration.
_NO_RECORD_YET = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,3}?\W+exists?\b", re.IGNORECASE
)
#: The consequence's direction, likewise anchored. This is the half that makes
#: the rule a gate rather than an encouragement — without it, step 8 says a
#: record is nice to have and the surface accumulates tickets anyway.
_MAY_NOT_ACCUMULATE = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,3}?\W+accumulat\w+", re.IGNORECASE
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _record_step() -> str:
    """The reviewer's record-reality step, bounded by the next numbered step.

    Anchored on the step's **title**, not its ordinal, and bounded by whatever
    numbered step follows rather than by "9.". The ordinal form this replaced
    (``text.find("8. **On PASS")`` up to ``"9. **Ship and close"``) is the class
    ``craft.md`` → *An ordinal reference into an enumeration is invalidated by a
    correct insertion* names: a step inserted anywhere earlier in the flow
    renumbers both ends and the slice silently stops resolving, or resolves to
    the wrong step.
    """
    text = _skill_text()
    m = re.search(r"^\d+\.\s+\*\*On PASS\b.*$", text, re.MULTILINE)
    assert m, (
        "spec-driven-development must have a numbered 'On PASS, the reviewer "
        "records reality' step — the gate's canonical home"
    )
    rest = text[m.start() :]
    nxt = re.search(r"^\d+\.\s+\*\*", rest[m.end() - m.start() :], re.MULTILINE)
    return rest if nxt is None else rest[: (m.end() - m.start()) + nxt.start()]


def test_the_asbuilt_record_gate_has_a_home() -> None:
    """Step 8 states the creation gate, its cap, and both record forms.

    Five conjuncts over the step, two of them negations. ``first ticket`` is who
    creates the record; the two negations carry the trigger and the cap; and the
    two record forms are what makes the rule layer-aware, so a repo with the
    ``feature_specs`` layer off is not told to create a file its process has no
    home for.
    """
    step = _record_step()
    lower = step.lower()

    assert _NO_RECORD_YET.search(step), (
        "step 8 no longer states the gate's trigger — a surface whose as-built "
        "record does *not* exist yet. Without the negation beside the verb, a "
        "step describing what to do when the record already exists satisfies "
        "every term this guard reads."
    )
    assert "first ticket" in lower, (
        "step 8 must say the first ticket touching the surface creates the "
        "record; without a named owner the obligation lands on nobody"
    )
    assert _MAY_NOT_ACCUMULATE.search(step), (
        "step 8 no longer caps a surface at one shipped ticket without an "
        "as-built record. That clause is the whole gate: drop it and the rule "
        "becomes a preference, which is the state the defect shipped under."
    )
    assert "specs/features" in lower, (
        "the gate must name specs/features/ for the feature_specs-on case"
    )
    assert "design doc" in lower or "spec.md" in lower, (
        "the gate must name the design doc / SPEC.md for the feature_specs-off "
        "case, or the rule is unfollowable in a repo with the layer off"
    )
