"""Promotion gate evidence + classification — CAL-1116, revised by CAL-1159.

Where :mod:`harness.promotion` owns the git half of promotion, this owns the
**gate** half: turn the caller's gate result into *bounded* evidence and classify
a failure so an outer orchestrator can branch without ever seeing an unbounded
log.

CAL-1116 originally had the verb **execute** the gate itself, inside the
promotion worktree. CAL-1159 retired that: the ``harness:dev`` image is built
``--no-dev`` and cannot run this repo's ``verify:`` toolchain (no ruff/mypy/pytest),
so an in-container gate returned green having run zero checks and the promotion
success path was unreachable through the production wrapper. The gate now runs
**where the toolchain already lives** — the orchestrating session, host-side, in
the worktree — and hands the verb its result via ``--gate-exit``/``--gate-log``,
exactly as the build ``review`` gate does (:mod:`harness.gate`, "evidence, not
execution"). This module is therefore the *classifier*, not the *executor*: it
builds :class:`GateEvidence` from the supplied report and maps a non-green result
to a promotion status. Gate *config* (whether the repo defines a gate at all) is
still read from ``CONTEXT.md`` through the one seam :mod:`harness.gate` owns
(:func:`~harness.gate.load_gate_command`); the evidence tail is bounded by the
same :data:`~harness.gate.GATE_OUTPUT_TAIL_LIMIT` the review gate uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness.gate import read_gate_log_tail

__all__ = [
    "GateEvidence",
    "classify_gate_failure",
    "evidence_from_report",
]


@dataclass(frozen=True)
class GateEvidence:
    """The bounded, machine-readable result of one gate run the caller reported.

    ``exit_code`` is the verify command's exit status. It is ``None`` only for a
    gate that could not be run to completion at all (an *infrastructure* failure) —
    a distinction the caller draws on their side; a supplied ``--gate-exit`` always
    carries a real status, so ``None`` is the degenerate case a hand-built evidence
    can still express. ``evidence`` is the bounded tail of the caller's gate log,
    capped at :data:`~harness.gate.GATE_OUTPUT_TAIL_LIMIT`, so the outer
    orchestrator never receives an unbounded log.
    """

    command: str
    exit_code: int | None
    evidence: str

    @property
    def launched(self) -> bool:
        """Whether the gate ran to completion (``exit_code`` is a real status)."""
        return self.exit_code is not None

    @property
    def passed(self) -> bool:
        """Whether the gate ran and was green."""
        return self.exit_code == 0


def evidence_from_report(
    command: str, *, gate_exit: int, gate_log: Path | None
) -> GateEvidence:
    """Build bounded :class:`GateEvidence` from the caller's reported gate result.

    ``gate_exit`` is the exit status the orchestrator's host-side gate run
    returned (the load-bearing half of the evidence); ``gate_log`` is the optional
    path to its captured output, read tail-bounded and best-effort — an absent or
    unreadable log degrades to an empty tail rather than failing, mirroring
    ``review``'s :func:`~harness.gate.read_gate_log_tail`. ``command`` is the
    repo's ``verify:`` string, carried only for the record.
    """
    return GateEvidence(
        command=command,
        exit_code=gate_exit,
        evidence=read_gate_log_tail(gate_log),
    )


def classify_gate_failure(evidence: GateEvidence) -> str:
    """Classify a *non-green* gate result into a promotion status.

    Call only when ``evidence`` is not ``passed``. The policy is deterministic —
    it keys on whether the gate ran, not on parsing its output:

    * ``blocked`` — the gate could not be executed (``exit_code is None``): an
      infrastructure failure, not a code decision.
    * ``needs_ticket`` — the gate ran and failed: the promoted tree is red, which
      in v1 is a human-owned fix (``agent_may_fix`` is reserved for small merge
      *conflicts*, not gate failures — ADR 0003, conservatively narrowed).
    """
    if not evidence.launched:
        return "blocked"
    return "needs_ticket"
