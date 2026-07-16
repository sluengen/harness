"""Promotion gate execution + evidence capture — CAL-1116 (ADR 0003).

Where :mod:`harness.promotion` owns the git half of promotion, this owns the
**gate** half: run the repo's configured verify command inside the promotion
worktree, capture *bounded* evidence, and classify a failure so an outer
orchestrator can branch without ever seeing an unbounded log.

Unlike the build ``review`` gate — which the orchestrator runs host-side and
merely *reports* to the verb (:mod:`harness.gate`, "evidence, not execution") —
promotion **executes** the gate itself. The design difference is deliberate: the
promotion loop is the local always-on steward (ADR 0001), running where the
repo's toolchain already lives, so gate execution is deterministic harness work
the merge+classify step owns rather than a step the orchestrator brokers (ADR
0003 / the accepted ``local-promotion-steward`` proposal). Gate *config* is still
read from ``CONTEXT.md`` through the one seam :mod:`harness.gate` already owns
(:func:`~harness.gate.load_gate_command`), and the evidence is bounded by the
same :data:`~harness.gate.GATE_OUTPUT_TAIL_LIMIT` the review gate uses — this
module adds only the executor and the failure policy.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.gate import GATE_OUTPUT_TAIL_LIMIT

__all__ = [
    "PROMOTION_GATE_TIMEOUT_SECONDS",
    "GateEvidence",
    "classify_gate_failure",
    "run_promotion_gate",
]

#: Wall-clock ceiling for a single promotion gate run. A gate that has not
#: finished by here is killed and surfaced as an infrastructure failure
#: (``exit_code=None`` → ``blocked``) rather than hanging the promotion — the same
#: shape as the review engine's ``engine_timeout_seconds``. Deliberately generous
#: (30 min) because a full verify (lint → typecheck → test → smoke) is slower than
#: a single review subprocess.
PROMOTION_GATE_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class GateEvidence:
    """The bounded, machine-readable result of one promotion gate run.

    ``exit_code`` is the verify command's exit status, or ``None`` when the gate
    could not be run to completion at all (a launch error or a timeout) — an
    *infrastructure* failure distinct from a command that ran and returned
    non-zero. ``evidence`` is the tail of combined stdout+stderr, capped at
    :data:`~harness.gate.GATE_OUTPUT_TAIL_LIMIT`, so the outer orchestrator never
    receives an unbounded log (AC-4).
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


def run_promotion_gate(worktree: Path, *, command: str) -> GateEvidence:
    """Execute ``command`` in ``worktree`` and return bounded :class:`GateEvidence`.

    The command is the repo's own ``verify:`` string from ``CONTEXT.md`` (a
    trusted, in-repo source), run through the shell so a compound gate
    (``ruff && mypy && pytest``) works verbatim. A launch error or a timeout maps
    to ``exit_code=None`` (an infrastructure failure the caller classifies
    ``blocked``); otherwise the real exit status is recorded. Output is always
    tail-bounded before it leaves this function.
    """
    try:
        result = subprocess.run(  # noqa: S602 — the gate is the repo's own trusted verify: command
            command,
            shell=True,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=PROMOTION_GATE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        # ``text=True`` gives str (or None) streams; join whatever partial output
        # the killed gate produced (``str(...)`` keeps this total for the checker).
        partial = str(exc.stdout or "") + str(exc.stderr or "")
        return GateEvidence(command=command, exit_code=None, evidence=_tail(partial))
    except OSError as exc:
        return GateEvidence(
            command=command, exit_code=None, evidence=_tail(str(exc))
        )
    combined = (result.stdout or "") + (result.stderr or "")
    return GateEvidence(
        command=command, exit_code=result.returncode, evidence=_tail(combined)
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


def _tail(text: str) -> str:
    """The last :data:`~harness.gate.GATE_OUTPUT_TAIL_LIMIT` characters of ``text``."""
    return text[-GATE_OUTPUT_TAIL_LIMIT:]
