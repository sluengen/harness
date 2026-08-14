"""#353 — the shared gate predicate now accepts two kinds of evidence.

``certify_head`` answers one question for two callers (``close`` and
``reclaim --stale``), and after this change it answers it over two disjoint
claims about the same tree: a gate-evidenced ``review`` pass, or a gate-evidenced
trivial certification. The matrix below drives **``certify_head`` itself** over
both kinds and all four conditions, because the failure mode this module exists
to prevent is the two kinds drifting into two opinions about what qualifies.

The floors matter as much as the matrix. A ``@parametrize`` set that lost its
``trivial_certification`` rows would report ``skipped``, not a failure, so one
floor derives the covered kinds from :data:`~harness.cli._review_gate.EvidenceKind`
and asserts both are exercised. And a query that read a literal ``$.certified_sha``
alongside the imported constant would pass every behavioural row here, so the
vacuity guard repoints the constant and asserts the certification half stops
matching.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args
from unittest.mock import patch

import pytest

from harness.cli import _review_gate
from harness.cli._review_gate import EvidenceKind, certify_head
from harness.events.payloads import CertifyEventData, ReviewEventData
from harness.state import store
from tests._asyncutil import run_sync

RUN_ID = "01GATERUN00000000000000000"
HEAD = "a" * 40
OTHER = "b" * 40
BASE = "c" * 40


def _db(tmp_path: Path) -> Path:
    db_path = tmp_path / "harness.db"
    run_sync(store.init_db(db_path))

    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, started_at) "
                "VALUES (?, '', 0, 'open', '{}', '{}', '2026-08-15T00:00:00Z')",
                (RUN_ID,),
            )
            await conn.commit()

    run_sync(_insert())
    return db_path


def _emit(db_path: Path, event_type: str, data: dict[str, Any]) -> None:
    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                "VALUES (?, ?, '2026-08-15T00:00:01Z', ?)",
                (RUN_ID, event_type, json.dumps(data)),
            )
            await conn.commit()

    run_sync(_insert())


def _seed_review(db_path: Path, *, sha: str, gate_ran: bool) -> None:
    """A passing ``review`` row, built through the production model.

    Through the model rather than a dict literal so a field rename breaks this
    fixture exactly as it breaks the verb — a fixture keeping a retired key alive
    is how a passing test becomes a lie.
    """
    _emit(
        db_path,
        "review",
        ReviewEventData(
            run_id=RUN_ID,
            verdict="pass",
            issues=[],
            reviewed_sha=sha,
            engine="claude",
            created_at="2026-08-15T00:00:01Z",
            gate_ran=gate_ran,
            design_context=False,
            convergence_check_required=False,
        ).model_dump(exclude_none=True),
    )


def _seed_certification(db_path: Path, *, sha: str, gate_ran: bool) -> None:
    _emit(
        db_path,
        "certify",
        CertifyEventData(
            run_id=RUN_ID,
            certified_sha=sha,
            base_sha=BASE,
            assurance="trivial",
            classifier_version=1,
            eligible_paths=["docs/a.md"],
            allowlist=["docs/**"],
            gate_ran=gate_ran,
            created_at="2026-08-15T00:00:01Z",
        ).model_dump(exclude_none=True),
    )


_SEEDERS = {"review": _seed_review, "trivial_certification": _seed_certification}

#: ``(id, kind, condition, expected_verdict, expected_kind)``.
_MATRIX: list[tuple[str, str, str, str, str | None]] = [
    ("review-absent", "review", "absent", "no_passing_review", None),
    ("review-at-head-gated", "review", "at_head_with_gate", "certified", "review"),
    ("review-at-head-ungated", "review", "at_head_without_gate", "no_gate_evidence", None),
    ("review-elsewhere", "review", "at_another_sha", "stale_review", None),
    ("certify-absent", "trivial_certification", "absent", "no_passing_review", None),
    (
        "certify-at-head-gated",
        "trivial_certification",
        "at_head_with_gate",
        "certified",
        "trivial_certification",
    ),
    (
        "certify-at-head-ungated",
        "trivial_certification",
        "at_head_without_gate",
        "no_gate_evidence",
        None,
    ),
    (
        "certify-elsewhere",
        "trivial_certification",
        "at_another_sha",
        "stale_review",
        None,
    ),
]


@pytest.mark.parametrize(
    ("kind", "condition", "verdict", "evidence_kind"),
    [(k, c, v, e) for _, k, c, v, e in _MATRIX],
    ids=[name for name, _, _, _, _ in _MATRIX],
)
def test_the_gate_treats_both_evidence_kinds_alike(
    tmp_path: Path, kind: str, condition: str, verdict: str, evidence_kind: str | None
) -> None:
    """Missing, ungated and stale evidence are refused whichever kind it is."""
    db_path = _db(tmp_path)
    if condition == "at_head_with_gate":
        _SEEDERS[kind](db_path, sha=HEAD, gate_ran=True)
    elif condition == "at_head_without_gate":
        _SEEDERS[kind](db_path, sha=HEAD, gate_ran=False)
    elif condition == "at_another_sha":
        _SEEDERS[kind](db_path, sha=OTHER, gate_ran=True)

    certification = run_sync(certify_head(db_path, RUN_ID, HEAD))

    assert certification.verdict == verdict
    assert certification.evidence_kind == evidence_kind


def test_the_evidence_matrix_covers_both_kinds() -> None:
    """Floor outside the parametrization, derived from the production Literal.

    A thinned matrix reads as ``skipped`` rather than as a failure, and a third
    evidence kind added later must not arrive unswept.
    """
    covered = {kind for _, kind, _, _, _ in _MATRIX}
    assert covered == set(get_args(EvidenceKind))
    conditions = {condition for _, _, condition, _, _ in _MATRIX}
    assert conditions == {"absent", "at_head_with_gate", "at_head_without_gate", "at_another_sha"}


def test_a_review_pass_is_preferred_when_both_kinds_cover_head(tmp_path: Path) -> None:
    """The stronger claim wins, so a run holding one behaves exactly as before."""
    db_path = _db(tmp_path)
    _seed_certification(db_path, sha=HEAD, gate_ran=True)
    _seed_review(db_path, sha=HEAD, gate_ran=True)

    certification = run_sync(certify_head(db_path, RUN_ID, HEAD))

    assert certification.verdict == "certified"
    assert certification.evidence_kind == "review"


def test_a_stale_certification_is_reported_among_the_evidenced_shas(
    tmp_path: Path,
) -> None:
    """``evidenced_shas`` spans both kinds, which is what ``close``'s message names.

    Reporting only ``pass_shas`` would tell an operator whose certification is
    one commit behind that no evidence exists at all.
    """
    db_path = _db(tmp_path)
    _seed_certification(db_path, sha=OTHER, gate_ran=True)

    certification = run_sync(certify_head(db_path, RUN_ID, HEAD))

    assert certification.verdict == "stale_review"
    assert certification.evidenced_shas == frozenset({OTHER})
    assert certification.pass_shas == frozenset()


def test_a_certification_row_without_its_binding_sha_never_matches(
    tmp_path: Path,
) -> None:
    """A row that cannot name the tree it covers cannot open a gate.

    The enforcement is by absence — the query requires the binding datum to be
    non-NULL — so a row written by a future harness that dropped the field is
    refused rather than trusted, with no ledger migration.
    """
    db_path = _db(tmp_path)
    _emit(
        db_path,
        "certify",
        {"run_id": RUN_ID, "gate_ran": True, "assurance": "trivial"},
    )

    certification = run_sync(certify_head(db_path, RUN_ID, HEAD))

    assert certification.verdict == "no_passing_review"


def test_the_gate_reads_the_certification_sha_through_the_payload_constant(
    tmp_path: Path,
) -> None:
    """The vacuity guard: repoint the constant, and the half must stop matching.

    A source grep proves only that the constant is *imported*. This proves the
    query's real input is that constant rather than a ``$.certified_sha`` literal
    spelled alongside it — the shape ``test_reclaim_closable`` already pins for
    the review half.
    """
    db_path = _db(tmp_path)
    _seed_certification(db_path, sha=HEAD, gate_ran=True)
    assert run_sync(certify_head(db_path, RUN_ID, HEAD)).certified

    with patch.object(_review_gate, "CERTIFY_CERTIFIED_SHA_PATH", "$.not_the_sha"):
        assert not run_sync(certify_head(db_path, RUN_ID, HEAD)).certified


def test_the_gate_reads_the_certification_gate_evidence_through_its_constant(
    tmp_path: Path,
) -> None:
    """The same proof for the evidence half, which is the safety-critical one."""
    db_path = _db(tmp_path)
    _seed_certification(db_path, sha=HEAD, gate_ran=True)

    with patch.object(_review_gate, "CERTIFY_GATE_RAN_PATH", "$.not_the_gate"):
        certification = run_sync(certify_head(db_path, RUN_ID, HEAD))

    assert certification.verdict == "no_gate_evidence"


def test_an_evidence_kind_is_never_read_out_of_a_refusal(tmp_path: Path) -> None:
    """``evidence_kind`` is set iff the verdict is ``certified``."""
    db_path = _db(tmp_path)
    _seed_certification(db_path, sha=OTHER, gate_ran=True)
    _seed_review(db_path, sha=OTHER, gate_ran=True)

    certification = run_sync(certify_head(db_path, RUN_ID, HEAD))

    assert not certification.certified
    assert certification.evidence_kind is None
