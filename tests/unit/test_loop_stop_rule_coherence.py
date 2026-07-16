"""CAL-906 (AC-5) — one coherent review→fix stop rule across the loop's docs.

Before this ticket the stop rule contradicted itself: ``agents/reviewer.md`` said
"A second consecutive FAIL stops the loop", while ``commands/harness.md`` said the
fix→review loop should "repeat until the verdict is ``pass`` or ``defer``"
(unbounded). The breaker code enforces a hard 6-cycle ceiling; the prose must say
the *same* thing in one voice. This guard turns "no surviving contradiction" into
a structural gate so the two cannot drift back apart.
"""

from __future__ import annotations

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
