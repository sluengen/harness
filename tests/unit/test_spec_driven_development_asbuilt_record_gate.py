"""#182 — ``spec-driven-development`` requires the as-built record before a
surface accumulates a second ticket.

A missing join between two shipped tickets is invisible from inside either
ticket. In nano-erp, ERP-114 built the receiving end of the quote share flow
and ERP-109 built the list — each met every criterion — but no record
described the *flow* (operator sends a quote, customer opens a link), so the
missing share link (CODE-2) went unseen until an assessment wrote the record
six tickets late. The as-built record is where a gap between tickets becomes
visible, and it cannot do that job retroactively (nano-erp assessment
``assessments/2026-07-22-code.md``, systemic insight CODE-INSIGHT-3, nano-erp
ERP-139).

The fix lives in the reviewer's record step (step 8) of
``spec-driven-development``: when a surface's as-built record does not exist
yet, the first ticket touching that surface creates it, and a surface is not
permitted to accumulate more than one shipped ticket without one. Worded
layer-aware (per ``skills/spec-driven-development/SKILL.md``'s existing
"Layer note") so it holds for both a ``feature_specs``-on repo (the record is
a feature spec in ``specs/features/``) and a ``feature_specs``-off repo (the
design doc / ``SPEC.md``).

Acceptance criteria (#182):

* **AC-1** — the skill states the gate: no as-built record yet → the first
  ticket touching that surface creates it; a surface may not accumulate a
  second shipped ticket without one. Proven by
  :func:`test_skill_states_asbuilt_record_creation_gate`.
* **AC-2** — the gate lives at the reviewer's record step (step 8, "the
  reviewer records reality"), not buried elsewhere. Proven by
  :func:`test_gate_is_at_record_step`.
* **AC-3** — the gate is layer-aware: it names ``specs/features/`` for the
  ``feature_specs``-on case and the design doc / ``SPEC.md`` for the
  ``feature_specs``-off case. Proven by :func:`test_gate_is_layer_aware`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "spec-driven-development" / "SKILL.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _record_step() -> str:
    """The numbered step 8 record-reality bullet, up through step 9."""
    text = _skill_text()
    start = text.find("8. **On PASS")
    assert start != -1, (
        "spec-driven-development must have a numbered step 8 'On PASS, the "
        "reviewer records reality' bullet"
    )
    end = text.find("9. **Ship and close", start)
    assert end != -1, "spec-driven-development must have a step 9 after step 8"
    return text[start:end]


def test_skill_states_asbuilt_record_creation_gate() -> None:
    """The skill states the gate: first-ticket-creates-it, one-shipped-ticket
    cap without a record (AC-1)."""
    section = _record_step().lower()
    assert "does not exist yet" in section, (
        "the gate must trigger on a surface with no as-built record yet"
    )
    assert "first ticket" in section, (
        "the gate must say the first ticket touching the surface creates the "
        "record"
    )
    assert "more than one shipped ticket" in section, (
        "the gate must cap a surface at one shipped ticket without an "
        "as-built record"
    )
    assert "cannot do that job retroactively" in section, (
        "the gate must state why the record can't be written after the fact"
    )


def test_gate_is_at_record_step() -> None:
    """The gate sits at step 8, the reviewer's record-reality step, not
    elsewhere in the skill (AC-2)."""
    section = _record_step()
    assert "does not exist yet" in section.lower(), (
        "the as-built-record-creation gate must live inside step 8, the "
        "reviewer's record-reality step"
    )


def test_gate_is_layer_aware() -> None:
    """The gate names both the feature_specs-on and feature_specs-off record
    forms (AC-3)."""
    section = _record_step().lower()
    assert "specs/features" in section, (
        "the gate must name specs/features/ for the feature_specs-on case"
    )
    assert "design doc" in section or "spec.md" in section, (
        "the gate must name the design doc / SPEC.md for the "
        "feature_specs-off case"
    )
