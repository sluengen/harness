"""CAL-972 — ``review-discipline`` gates the as-built record on a behaviour change.

From the 2026-07-03 full-review assessment (SYSTEM-INSIGHT-1, Medium — a systemic
insight): shipped behaviour changes whose as-built records silently rot. The
per-change review updated the code but never the mapped feature spec / design
doc, so the canonical record drifted from what shipped — a class no single
per-change reviewer catches, because each reviewer looks at the code, not at
whether the record kept pace.

The accepted fix elevates the reviewer's *record reality on PASS* obligation into
a hard **as-built-record gate**: when the diff touches a user-facing surface, the
review must either fold the matching as-built-record update into the change or
record an explicit deferral naming the reason; a behaviour change with neither is
a FAIL. It reuses the *Architecture watchlist* trigger mechanism — compare the
changed paths to the surfaces the record documents — and is layer-aware: the
record is ``specs/features/`` where ``feature_specs`` is on, otherwise the design
doc / ``SPEC.md``.

This guard binds the gate into the guidance so a future re-edit cannot silently
drop it — a text-parse content guard in the style of
``test_review_discipline_port_orphan`` (CAL-665) and ``test_distributed_skill_cites``
(CAL-654): it reads the as-built guidance and asserts the rule is present, in the
right place, and surfaced by the command and the reviewer agent that operate it.

Acceptance criteria (CAL-972, harness-side deliverable):

* **AC-1** — ``review-discipline`` carries the as-built-record gate: the
  user-facing-surface trigger, the record-or-deferral requirement, and the FAIL
  consequence, layer-aware across ``feature_specs`` on/off. Proven by
  :func:`test_skill_states_asbuilt_record_gate` and :func:`test_gate_is_layer_aware`.
* **AC-1 (placement)** — the gate lives in the Reviewer-obligations section, with
  the record obligation it strengthens (not buried elsewhere). Proven by
  :func:`test_gate_is_in_reviewer_obligations`.
* **AC-1 (command + agent)** — ``commands/review.md`` and ``agents/reviewer.md``
  surface the gate, so neither can state the record step without it. Proven by
  :func:`test_command_surfaces_gate` and :func:`test_reviewer_agent_surfaces_gate`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"
_COMMAND = _REPO_ROOT / "commands" / "review.md"
_AGENT = _REPO_ROOT / "agents" / "reviewer.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _obligations_section() -> str:
    """The ``## Reviewer obligations`` section, where the record gate lives."""
    text = _text(_SKILL)
    start = text.find("## Reviewer obligations")
    assert start != -1, "review-discipline must have a Reviewer obligations section"
    end = text.find("## On a FAIL", start)
    assert end != -1, (
        "review-discipline must have an 'On a FAIL' section after obligations"
    )
    return text[start:end]


def test_skill_states_asbuilt_record_gate() -> None:
    """review-discipline names the gate: trigger, record-or-deferral, FAIL (AC-1)."""
    text = _text(_SKILL).lower()
    assert "as-built" in text, "the skill must name the as-built-record gate"
    assert "user-facing surface" in text, (
        "the gate's trigger is a diff touching a user-facing surface"
    )
    assert "deferral" in text, (
        "the gate must offer an explicit deferral as the alternative to updating "
        "the record"
    )


def test_gate_is_in_reviewer_obligations() -> None:
    """The gate strengthens the record obligation, in its own section (AC-1)."""
    section = _obligations_section().lower()
    assert "as-built" in section, (
        "the as-built-record gate must live with the record obligation it "
        "strengthens (the Reviewer obligations section)"
    )
    assert "user-facing surface" in section, "the trigger must sit in the gate"
    assert "deferral" in section, "the deferral escape must sit in the gate"
    assert "fail" in section, (
        "a behaviour change with neither a record update nor a deferral is a FAIL"
    )


def test_gate_is_layer_aware() -> None:
    """The as-built record form follows the ``feature_specs`` layer (AC-1)."""
    section = _obligations_section().lower()
    assert "specs/features" in section, (
        "the gate must name specs/features as the record where feature_specs is on"
    )
    assert "spec.md" in section or "design doc" in section, (
        "the gate must cover the feature_specs-off case (design doc / SPEC.md)"
    )


def test_command_surfaces_gate() -> None:
    """``commands/review.md`` surfaces the gate in its verdict step (AC-1)."""
    text = _text(_COMMAND).lower()
    assert "as-built" in text, "the review command must name the as-built record"
    assert "deferral" in text, (
        "the review command must surface the record-or-deferral gate, not just the "
        "unconditional record update"
    )


def test_reviewer_agent_surfaces_gate() -> None:
    """``agents/reviewer.md`` states the gate where it records reality (AC-1)."""
    text = _text(_AGENT).lower()
    assert "as-built" in text or "user-facing surface" in text, (
        "the reviewer agent must name the as-built-record gate at its record step"
    )
    assert "deferral" in text, (
        "the reviewer agent's record step must offer the deferral escape, so it "
        "cannot state the PASS-record obligation without its gate"
    )
