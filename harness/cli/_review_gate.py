"""What, in the ledger, certifies a given tree — and what kind of evidence is it?

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
transaction, and :func:`harness._git.worktree_toplevel_matches` moved to a
shared home in its own words, *a second copy of a check whose failure mode is
the feature silently stops working is worse than a shared one*.

The split of responsibility is deliberate: this module answers **what the ledger
says** and nothing else. It resolves no HEAD, reads no worktree, and owns no
refusal message — ``close`` keeps its :data:`~harness.cli.close.RefusalReason`
strings (its user-facing contract) and maps this verdict onto them. So the
extraction moved a query, not a trust decision.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from harness.events.payloads import (
    CERTIFY_CERTIFIED_SHA_PATH,
    CERTIFY_GATE_RAN_PATH,
    CERTIFY_GATE_REASON_PATH,
    REVIEW_GATE_RAN_PATH,
    REVIEW_GATE_REASON_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    REVIEW_VERDICT_PATH,
)
from harness.gate import GATE_NOT_CONFIGURED_REASON
from harness.state import store

__all__ = [
    "CertificationVerdict",
    "EvidenceKind",
    "HeadCertification",
    "certify_head",
    "has_gate_evidence",
]

#: What kind of evidence certified the tree (#353). Returned rather than
#: re-derived, so ``close`` and ``reclaim`` report it without a second query —
#: which is what keeps the gate query in one place.
EvidenceKind = Literal["review", "trivial_certification"]

#: Why a tree is (or is not) certified. ``close`` maps the three negatives
#: straight onto its own refusal reasons, which is why they carry those names —
#: but the names are this module's contract, not an import from ``close``
#: (importing them back would recreate the cycle the split removes).
#:
#: **Unchanged by #353, deliberately.** ``close``'s five ``RefusalReason``
#: members are a locked public contract, and the ticket confines ``close`` to
#: *mapping* this verdict. So the two negatives widen in meaning to cover either
#: evidence kind and the messages — which are not contract — say which. The
#: conscious trade: a ``trivial`` run that never certified is refused
#: ``no_passing_review``, a slightly odd tag for a run that never intended a
#: review. The message explains it; the tag stays stable.
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
    #: SHAs the run holds a recorded trivial certification for (#353). Defaulted,
    #: so every existing construction site is untouched.
    certified_shas: frozenset[str] = frozenset()
    #: Set **iff** ``verdict == "certified"``, and ``None`` on every negative, so
    #: a caller cannot read an evidence kind out of a refusal.
    evidence_kind: EvidenceKind | None = None

    @property
    def certified(self) -> bool:
        """True iff the tree may be merged as far as the *ledger* is concerned."""
        return self.verdict == "certified"

    @property
    def evidenced_shas(self) -> frozenset[str]:
        """Every SHA the run holds qualifying evidence for, of either kind.

        What ``close``'s ``stale_review`` message names: a run certified at an
        older SHA is stale for the same reason a reviewed one is, and reporting
        only the reviewed half would tell an operator their certification did not
        exist.
        """
        return self.pass_shas | self.certified_shas


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


#: One projection, used twice: the SHA a row binds to, plus the two gate-evidence
#: fields. The certify shape names all three identically to the review shape (the
#: cross-assertion in ``payloads`` enforces the gate pair), so the query text is
#: shared and only the bound paths and the event type differ. A second, separately
#: written SELECT is how the two kinds would start disagreeing.
_EVIDENCE_SELECT = (
    # The json paths are the single-sourced payload-key constants (CAL-1012),
    # passed as bound parameters — SQLite accepts a bound json_extract path, so
    # the gate holds no raw ``$.<key>`` literal.
    "SELECT json_extract(data_json, ?), json_extract(data_json, ?), "
    "json_extract(data_json, ?) FROM events WHERE run_id = ? "
)

_PASS_ROWS = _EVIDENCE_SELECT + "AND event_type = 'review' AND json_extract(data_json, ?) = 'pass'"
_CERTIFY_ROWS = (
    _EVIDENCE_SELECT + "AND event_type = 'certify' AND json_extract(data_json, ?) IS NOT NULL"
)


def _covers(rows: Sequence[Sequence[Any]], head_sha: str) -> bool:
    """Whether any row binds to ``head_sha`` **and** shows its gate ran.

    One helper for both kinds, calling the one :func:`has_gate_evidence`. The
    trivial path's entire safety argument is the verify gate, and a second copy
    of that rule is how the two kinds start disagreeing about what green means.
    """
    return any(
        has_gate_evidence(gate_ran, gate_reason)
        for sha, gate_ran, gate_reason in rows
        if str(sha) == head_sha
    )


async def certify_head(
    db_path: Path, run_id: str, head_sha: str
) -> HeadCertification:
    """Does ``run_id`` hold gate-evidenced evidence bound to ``head_sha``, and of what kind?

    Two kinds qualify, and they are **disjoint claims about the same tree**: a
    ``review`` event with ``verdict='pass'``, or a ``certify`` event whose
    ``certified_sha`` matches (#353). Both must satisfy the identical
    :func:`has_gate_evidence` — one function applied to the one gate-evidence
    contract both payloads record.

    A review is **preferred** where both exist: it is the stronger claim, and the
    preference keeps every run that has one behaving byte-identically to before.

    Three ways to fail, in the order that reports the *root* cause rather than a
    symptom: no evidence of either kind at all (``no_passing_review``), evidence
    but only for another SHA (``stale_review``), or evidence covering this SHA
    that cannot show the repo's gate ran (``no_gate_evidence``, the CAL-1082
    backstop — a pass written by an older harness carries no ``gate_ran`` key at
    all, so ``json_extract`` yields NULL and it is refused rather than trusted,
    keeping the check fail-safe with no ledger migration; a ``certify`` row
    written by a future harness that dropped the field is refused the same way).

    The certify query requires ``certified_sha`` to be non-NULL, so a row that
    cannot name the tree it covers can never match however else it is written —
    the same enforcement-by-absence that keeps the review refusal shape (which
    carries no ``verdict``) out of the review half.
    """
    async with store.connect(db_path) as conn:
        async with conn.execute(
            _PASS_ROWS,
            (
                REVIEW_REVIEWED_SHA_PATH,
                REVIEW_GATE_RAN_PATH,
                REVIEW_GATE_REASON_PATH,
                run_id,
                REVIEW_VERDICT_PATH,
            ),
        ) as cur:
            pass_rows = list(await cur.fetchall())
        async with conn.execute(
            _CERTIFY_ROWS,
            (
                CERTIFY_CERTIFIED_SHA_PATH,
                CERTIFY_GATE_RAN_PATH,
                CERTIFY_GATE_REASON_PATH,
                run_id,
                CERTIFY_CERTIFIED_SHA_PATH,
            ),
        ) as cur:
            certify_rows = list(await cur.fetchall())

    pass_shas = frozenset(str(r[0]) for r in pass_rows if r[0] is not None)
    certified_shas = frozenset(str(r[0]) for r in certify_rows if r[0] is not None)

    if head_sha in pass_shas and _covers(pass_rows, head_sha):
        return HeadCertification("certified", pass_shas, certified_shas, "review")
    if head_sha in certified_shas and _covers(certify_rows, head_sha):
        return HeadCertification(
            "certified", pass_shas, certified_shas, "trivial_certification"
        )
    evidenced = pass_shas | certified_shas
    if not evidenced:
        return HeadCertification("no_passing_review", pass_shas, certified_shas)
    if head_sha not in evidenced:
        return HeadCertification("stale_review", pass_shas, certified_shas)
    return HeadCertification("no_gate_evidence", pass_shas, certified_shas)
