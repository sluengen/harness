"""Does a recorded ``review`` pass certify a given tree? — the one answer.

``close`` asks this to decide whether to merge (:func:`harness.cli.close._evaluate_gate`),
and ``reclaim --stale`` asks it to decide whether a stranded run is *closable*
rather than stale (:mod:`harness.cli.reclaim_closable`, #255). Two callers, one
question, so it has one implementation.

Why a shared home rather than a second query. ``code-quality`` Part B extracts a
sync-critical rule on the **second** copy, and the failure mode here is the
sharper argument: a sweep that reports *closable* for a run ``close`` will refuse
leaves the ticket neither reclaimed nor closed — wedged in exactly the state both
paths exist to prevent. The precedent is already in the tree twice —
:mod:`harness.cli._abandon` gave ``cancel`` and ``reclaim`` one ledger
transaction, and :func:`harness.cli._git.worktree_toplevel_matches` moved to a
shared home in its own words, *a second copy of a check whose failure mode is
the feature silently stops working is worse than a shared one*.

The split of responsibility is deliberate: this module answers **what the ledger
says** and nothing else. It resolves no HEAD, reads no worktree, and owns no
refusal message — ``close`` keeps its :data:`~harness.cli.close.RefusalReason`
strings (its user-facing contract) and maps this verdict onto them. So the
extraction moved a query, not a trust decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from harness.events.payloads import (
    REVIEW_GATE_RAN_PATH,
    REVIEW_GATE_REASON_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    REVIEW_VERDICT_PATH,
)
from harness.gate import GATE_NOT_CONFIGURED_REASON
from harness.state import store

__all__ = [
    "CertificationVerdict",
    "HeadCertification",
    "certify_head",
    "has_gate_evidence",
]

#: Why a tree is (or is not) certified by a recorded review. ``close`` maps the
#: three negatives straight onto its own refusal reasons, which is why they carry
#: those names — but the names are this module's contract, not an import from
#: ``close`` (importing them back would recreate the cycle the split removes).
CertificationVerdict = Literal[
    "certified",
    "no_passing_review",
    "stale_review",
    "no_gate_evidence",
]


@dataclass(frozen=True)
class HeadCertification:
    """The ledger's verdict on ``head_sha``, plus the evidence behind it.

    ``pass_shas`` is every SHA the run has a recorded ``pass`` for. It is carried
    out because ``close``'s ``stale_review`` message names them, so leaving it
    behind would force the caller into a second query to write its own error.
    """

    verdict: CertificationVerdict
    pass_shas: frozenset[str]

    @property
    def certified(self) -> bool:
        """True iff the tree may be merged as far as the *ledger* is concerned."""
        return self.verdict == "certified"


def has_gate_evidence(gate_ran: Any, gate_reason: Any) -> bool:
    """Whether a pass row shows its verify gate was accounted for.

    Two shapes qualify. A gate that **ran** green (``gate_ran`` true — a red gate
    never gets an event at all, so a recorded run is a passing one). Or a repo
    that defines **no** gate (``gate_reason='not_configured'``): the harness
    cannot gate what a repo does not define, so it allows the close and the
    ledger records the absence honestly rather than implying a gate ran.
    Tightening that is a separate decision — it would strand every repo without a
    ``verify:``.

    ``gate_ran`` arrives from SQLite's ``json_extract`` as ``1`` / ``0`` / ``None``.
    """
    if gate_ran == 1:
        return True
    return bool(gate_reason == GATE_NOT_CONFIGURED_REASON)


async def certify_head(
    db_path: Path, run_id: str, head_sha: str
) -> HeadCertification:
    """Does ``run_id`` hold a gate-evidenced ``pass`` bound to ``head_sha``?

    Three ways to fail, in the order that reports the *root* cause rather than a
    symptom: no pass at all (``no_passing_review``), a pass but only for another
    SHA (``stale_review``), or a pass covering this SHA that cannot show the
    repo's gate ran (``no_gate_evidence``, the CAL-1082 backstop — a pass written
    by an older harness carries no ``gate_ran`` key at all, so ``json_extract``
    yields NULL and it is refused rather than trusted, keeping the check
    fail-safe with no ledger migration).
    """
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            # The json paths are the single-sourced payload-key constants
            # (CAL-1012), passed as bound parameters — SQLite accepts a bound
            # json_extract path, so the gate holds no raw ``$.<key>`` literal.
            "SELECT json_extract(data_json, ?), json_extract(data_json, ?), "
            "json_extract(data_json, ?) "
            "FROM events WHERE run_id = ? AND event_type = 'review' "
            "AND json_extract(data_json, ?) = 'pass'",
            (
                REVIEW_REVIEWED_SHA_PATH,
                REVIEW_GATE_RAN_PATH,
                REVIEW_GATE_REASON_PATH,
                run_id,
                REVIEW_VERDICT_PATH,
            ),
        ) as cur,
    ):
        rows = await cur.fetchall()

    pass_shas = frozenset(str(r[0]) for r in rows if r[0] is not None)
    if not pass_shas:
        return HeadCertification("no_passing_review", pass_shas)
    if head_sha not in pass_shas:
        return HeadCertification("stale_review", pass_shas)
    if not any(
        has_gate_evidence(gate_ran, gate_reason)
        for sha, gate_ran, gate_reason in rows
        if str(sha) == head_sha
    ):
        return HeadCertification("no_gate_evidence", pass_shas)
    return HeadCertification("certified", pass_shas)
