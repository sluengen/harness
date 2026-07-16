"""Promotion gate execution + evidence capture — CAL-1116 (ADR 0003).

The pure mechanics of running the repo's verify gate inside a promotion worktree
and turning the result into bounded evidence + a policy classification. These are
the harness-owned deterministic facts an outer orchestrator reads back; the CLI
(:mod:`harness.cli.promote`) only maps them onto lifecycle state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import promotion_gate
from harness.gate import GATE_OUTPUT_TAIL_LIMIT
from harness.promotion_gate import (
    GateEvidence,
    classify_gate_failure,
    run_promotion_gate,
)


def test_green_gate_passes_with_bounded_evidence(tmp_path: Path) -> None:
    """A zero-exit command is ``passed`` and ``launched`` with its output captured."""
    evidence = run_promotion_gate(tmp_path, command="printf hello; exit 0")
    assert evidence.passed
    assert evidence.launched
    assert evidence.exit_code == 0
    assert "hello" in evidence.evidence


def test_red_gate_captures_stderr_and_is_not_passed(tmp_path: Path) -> None:
    """A non-zero command is ``launched`` but not ``passed``; stderr is captured."""
    evidence = run_promotion_gate(
        tmp_path, command="printf boom 1>&2; exit 3"
    )
    assert not evidence.passed
    assert evidence.launched
    assert evidence.exit_code == 3
    assert "boom" in evidence.evidence


def test_unknown_binary_is_a_launched_red_gate(tmp_path: Path) -> None:
    """A command that exits non-zero via the shell's not-found path is still
    *launched* (the shell ran and reported 127) — a red gate, not an infra
    failure. Distinguishes the shell-127 case from a genuine launch failure."""
    evidence = run_promotion_gate(tmp_path, command="definitely-not-a-real-binary-xyz")
    assert evidence.launched
    assert not evidence.passed


def test_launch_failure_maps_to_not_launched(tmp_path: Path) -> None:
    """A genuine launch failure — here an ``OSError`` from a non-existent working
    directory — is the real ``exit_code=None`` path: the gate could not run at all,
    so it is *not* launched (an infrastructure failure the caller maps to
    ``blocked``). This exercises run_promotion_gate's ``except OSError`` branch, not
    a hand-built ``GateEvidence``."""
    evidence = run_promotion_gate(tmp_path / "does-not-exist", command="true")
    assert not evidence.launched
    assert evidence.exit_code is None
    assert not evidence.passed


def test_timeout_maps_to_not_launched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate that exceeds :data:`PROMOTION_GATE_TIMEOUT_SECONDS` is killed and
    surfaced as ``exit_code=None`` (an infra failure → ``blocked``), with its
    partial output bounded — exercising the ``except TimeoutExpired`` branch."""

    def _raise_timeout(*args: object, **kwargs: object) -> None:
        # text=True gives str output; stderr=None exercises the None-stream path.
        raise subprocess.TimeoutExpired(
            cmd="verify", timeout=1.0, output="partial-out", stderr=None
        )

    monkeypatch.setattr(promotion_gate.subprocess, "run", _raise_timeout)
    evidence = run_promotion_gate(tmp_path, command="sleep 999")
    assert not evidence.launched
    assert evidence.exit_code is None
    assert "partial-out" in evidence.evidence


# --- AC-5: the evidence bound is measured --------------------------------------


def test_evidence_is_bounded_to_the_tail_limit(tmp_path: Path) -> None:
    """Gate output longer than :data:`GATE_OUTPUT_TAIL_LIMIT` is truncated to exactly
    the limit — the bounded-evidence contract (AC-4) measured against its bound
    (AC-5). The orchestrator never receives an unbounded log."""
    # Emit well over the limit, then fail so this is a captured red-gate tail.
    overflow = GATE_OUTPUT_TAIL_LIMIT * 3
    evidence = run_promotion_gate(
        tmp_path, command=f"printf 'x%.0s' $(seq 1 {overflow}); exit 1"
    )
    assert not evidence.passed
    assert len(evidence.evidence) == GATE_OUTPUT_TAIL_LIMIT


def test_evidence_keeps_the_tail_not_the_head(tmp_path: Path) -> None:
    """The kept slice is the *tail* — the diagnostic last lines (a failing summary),
    not the first — mirroring the review gate's tail discipline."""
    overflow = GATE_OUTPUT_TAIL_LIMIT + 100
    evidence = run_promotion_gate(
        tmp_path,
        command=f"printf 'x%.0s' $(seq 1 {overflow}); printf TAILMARK; exit 1",
    )
    assert evidence.evidence.endswith("TAILMARK")
    assert len(evidence.evidence) == GATE_OUTPUT_TAIL_LIMIT


# --- classification policy -----------------------------------------------------


def test_launched_red_gate_classifies_needs_ticket() -> None:
    """A gate that ran and failed is out of local repair authority in v1 — the
    promoted tree is red, a human-owned fix — so it classifies ``needs_ticket``."""
    evidence = GateEvidence(command="verify", exit_code=1, evidence="fail")
    assert classify_gate_failure(evidence) == "needs_ticket"


def test_unlaunchable_gate_classifies_blocked() -> None:
    """A gate that could not be executed at all is an infrastructure failure, not a
    code decision — it classifies ``blocked``."""
    evidence = GateEvidence(command="verify", exit_code=None, evidence="")
    assert classify_gate_failure(evidence) == "blocked"
