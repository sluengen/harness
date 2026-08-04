"""CAL-906 (AC-5) — one coherent review→fix stop rule across the loop's docs.

Before this ticket the stop rule contradicted itself: ``agents/reviewer.md`` said
"A second consecutive FAIL stops the loop", while ``commands/harness.md`` said the
fix→review loop should "repeat until the verdict is ``pass`` or ``defer``"
(unbounded). The breaker code enforces a hard 6-cycle ceiling; the prose must say
the *same* thing in one voice. This guard turns "no surviving contradiction" into
a structural gate so the two cannot drift back apart.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REVIEWER = _REPO_ROOT / "agents" / "reviewer.md"
_HARNESS_CMD = _REPO_ROOT / "commands" / "harness.md"

#: The retired rule that must not survive anywhere in the loop's docs.
_CONTRADICTION = "consecutive fail"


def test_reviewer_drops_the_second_consecutive_fail_rule() -> None:
    """The old "2nd consecutive FAIL → escalate" rule is gone from reviewer.md."""
    body = _REVIEWER.read_text().lower()
    assert _CONTRADICTION not in body, (
        "agents/reviewer.md still carries the retired 'consecutive FAIL' stop rule; "
        "it must express the unified 6-cycle ceiling instead (CAL-906)."
    )


def test_reviewer_states_the_unified_ceiling_rule() -> None:
    """reviewer.md expresses the unified rule: a bounded ceiling that escalates."""
    body = _REVIEWER.read_text().lower()
    assert "6" in body and "escalate" in body, (
        "agents/reviewer.md must state the 6-cycle ceiling and that it escalates."
    )
    assert "unconditional" in body, (
        "agents/reviewer.md must state cycles 1–3 are unconditional."
    )


def test_routine_expresses_the_same_bounded_rule() -> None:
    """commands/harness.md bounds the fix→review loop with the same ceiling."""
    body = _HARNESS_CMD.read_text().lower()
    assert _CONTRADICTION not in body, (
        "commands/harness.md must not carry the retired 'consecutive FAIL' rule."
    )
    assert "6" in body and "cycle" in body, (
        "commands/harness.md must bound the fix→review loop by the 6-cycle ceiling, "
        "not describe it as unbounded."
    )


# --- #299: the stop rule names the mode the wall clock bounds -----------------
#
# ADR 0011 scoped `loop.wall_clock_budget_minutes` to unattended runs, but the
# `fail`-verdict stop rule here still described it as "the same single value
# `reclaim --stale` uses as its staleness threshold (#260), so the two cannot
# drift" — unqualified. That is the document an orchestrating session reads while
# deciding whether an exit-4 refusal is legitimate: told the clock is universal,
# an attended session reads its own refusal as proof the mode was ignored, and a
# later editor reads the sentence as licence to "fix" the mode split back out.
#
# The unit is a sentence **within a line**, not a sentence over the whole file.
# Markdown paragraphs are single lines here, so this keeps a fenced comment as
# its own subject instead of letting it merge into neighbouring prose and inherit
# a qualifier it does not carry.

#: The knob whose scope must travel with every mention of it.
_SCOPED_KNOB = "wall_clock_budget_minutes"

#: The mode it bounds, since ADR 0011.
_MODE = "unattended"

#: Sentence boundary: a terminator followed by an opener. Matches the splitter
#: `test_review_discipline_watchlist_entry_currency` uses, so lower-case
#: continuations like `loop.wall_clock_budget_minutes` do not split a sentence.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*(])")


def _sentences_naming(text: str, needle: str) -> list[str]:
    """Every sentence, line by line, that names ``needle``."""
    return [
        sentence.strip()
        for line in text.splitlines()
        for sentence in _SENTENCE_BREAK.split(line.strip())
        if needle in sentence
    ]


def test_the_scan_finds_the_knob_at_all() -> None:
    """Floor: the subject set is non-empty, so the rule below is not vacuous.

    A rename of the knob — or a rewrite that stops naming it — would silently
    empty the subject and leave the scope rule passing over nothing. That is the
    same empty-subject shape `test_attendance_declaration`'s docstring records
    for its own predecessor.
    """
    found = _sentences_naming(_HARNESS_CMD.read_text(encoding="utf-8"), _SCOPED_KNOB)
    assert found, (
        f"commands/harness.md must name `{_SCOPED_KNOB}` somewhere — it is the "
        "budget the stop rule and the reclaim pre-flight both rest on. If the "
        "knob was renamed, rename it here rather than deleting this guard."
    )


def test_the_scope_predicate_can_fail() -> None:
    """Positive control: an unqualified mention is judged failing.

    The sample is one Markdown paragraph — one *line* — whose qualifier sits in a
    neighbouring sentence rather than in the sentence that states the budget.
    That is what pins the unit at a sentence: a line-level predicate would find
    ``unattended`` elsewhere in the paragraph and certify the mention, which is
    the pre-ADR-0011 shape this guard exists to catch. A sample with the word
    nowhere would pass under either unit and prove nothing about the choice.
    """
    unqualified = (
        "An unattended run has no operator watching its spend. "
        "A per-run wall-clock budget trips the same way, `reason=wall_clock_budget` "
        "— its length is `loop.wall_clock_budget_minutes`, the same single value "
        "`reclaim --stale` uses as its staleness threshold (#260)."
    )
    assert _MODE in unqualified, (
        "the sample must contain the qualifier somewhere in the line, or it does "
        "not distinguish a sentence-level unit from a line-level one"
    )

    found = _sentences_naming(unqualified, _SCOPED_KNOB)
    assert found and all(_MODE not in sentence for sentence in found), (
        "the predicate must reject a mention that states the budget without "
        "naming the mode *in the same sentence*; otherwise it certifies the "
        "pre-ADR-0011 wording it exists to catch"
    )


def test_every_wall_clock_mention_names_the_mode_it_bounds() -> None:
    """The session-facing contract carries ADR 0011's scope wherever it states it."""
    text = _HARNESS_CMD.read_text(encoding="utf-8")
    unqualified = [
        sentence
        for sentence in _sentences_naming(text, _SCOPED_KNOB)
        if _MODE not in sentence
    ]

    assert not unqualified, (
        "every sentence in commands/harness.md naming "
        f"`{_SCOPED_KNOB}` must also name the mode it bounds "
        f"({_MODE!r}) — ADR 0011 scoped the clock, and this is the document the "
        "orchestrating session reads when deciding whether a breaker refusal is "
        "legitimate. Unqualified: " + "; ".join(repr(s) for s in unqualified)
    )
