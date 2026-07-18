"""Promotion gate evidence + classification — CAL-1116, revised by CAL-1159.

CAL-1159 retired the in-verb gate *executor* (``run_promotion_gate``): the
``harness:dev`` image cannot run a target repo's toolchain, so the gate runs
host-side and is *reported* to the verb via ``--gate-exit`` / ``--gate-log``. What
remains here is the pure classifier — build bounded :class:`GateEvidence` from the
caller's report, and map a non-green result to a promotion status.
"""

from __future__ import annotations

from pathlib import Path

from harness.gate import GATE_OUTPUT_TAIL_LIMIT
from harness.promotion_gate import (
    GateEvidence,
    classify_gate_failure,
    evidence_from_report,
)

# --- evidence_from_report: build bounded evidence from the caller's report -----


def test_green_report_is_passed_and_launched(tmp_path: Path) -> None:
    """A zero exit code reported by the caller is ``passed`` and ``launched``, with
    the gate log's tail captured as evidence."""
    log = tmp_path / "gate.log"
    log.write_text("hello\n")
    evidence = evidence_from_report("verify", gate_exit=0, gate_log=log)
    assert evidence.passed
    assert evidence.launched
    assert evidence.exit_code == 0
    assert "hello" in evidence.evidence


def test_red_report_is_launched_but_not_passed(tmp_path: Path) -> None:
    """A non-zero reported exit code is ``launched`` (the caller ran it) but not
    ``passed``; the log tail is captured."""
    log = tmp_path / "gate.log"
    log.write_text("boom\n")
    evidence = evidence_from_report("verify", gate_exit=3, gate_log=log)
    assert not evidence.passed
    assert evidence.launched
    assert evidence.exit_code == 3
    assert "boom" in evidence.evidence


def test_missing_log_degrades_to_empty_evidence() -> None:
    """``--gate-log`` is optional and best-effort: an absent path degrades to an
    empty tail rather than failing — the exit code is the load-bearing half."""
    evidence = evidence_from_report("verify", gate_exit=0, gate_log=None)
    assert evidence.passed
    assert evidence.evidence == ""


def test_unreadable_log_degrades_to_empty_evidence(tmp_path: Path) -> None:
    """A ``--gate-log`` path that cannot be read degrades to an empty tail; a lost
    diagnostic must not turn a green gate into a refusal."""
    evidence = evidence_from_report(
        "verify", gate_exit=0, gate_log=tmp_path / "does-not-exist.log"
    )
    assert evidence.passed
    assert evidence.evidence == ""


# --- the evidence bound is measured --------------------------------------------


def test_evidence_is_bounded_to_the_tail_limit(tmp_path: Path) -> None:
    """A gate log longer than :data:`GATE_OUTPUT_TAIL_LIMIT` is truncated to exactly
    the limit — the bounded-evidence contract measured against its bound. The
    orchestrator never receives an unbounded log."""
    log = tmp_path / "gate.log"
    log.write_text("x" * (GATE_OUTPUT_TAIL_LIMIT * 3))
    evidence = evidence_from_report("verify", gate_exit=1, gate_log=log)
    assert not evidence.passed
    assert len(evidence.evidence) == GATE_OUTPUT_TAIL_LIMIT


def test_evidence_keeps_the_tail_not_the_head(tmp_path: Path) -> None:
    """The kept slice is the *tail* — the diagnostic last lines (a failing summary),
    not the first — mirroring the review gate's tail discipline."""
    log = tmp_path / "gate.log"
    log.write_text("x" * (GATE_OUTPUT_TAIL_LIMIT + 100) + "TAILMARK")
    evidence = evidence_from_report("verify", gate_exit=1, gate_log=log)
    assert evidence.evidence.endswith("TAILMARK")
    assert len(evidence.evidence) == GATE_OUTPUT_TAIL_LIMIT


# --- classification policy -----------------------------------------------------


def test_launched_red_gate_classifies_needs_ticket() -> None:
    """A gate that ran and failed is out of local repair authority in v1 — the
    promoted tree is red, a human-owned fix — so it classifies ``needs_ticket``."""
    evidence = GateEvidence(command="verify", exit_code=1, evidence="fail")
    assert classify_gate_failure(evidence) == "needs_ticket"


def test_unlaunchable_gate_classifies_blocked() -> None:
    """A gate that could not be executed at all (``exit_code=None``) is an
    infrastructure failure, not a code decision — it classifies ``blocked``."""
    evidence = GateEvidence(command="verify", exit_code=None, evidence="")
    assert classify_gate_failure(evidence) == "blocked"
