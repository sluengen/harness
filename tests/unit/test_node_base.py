"""Tests for harness.nodes.base — see SPEC §4.3."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from harness.nodes.base import Artifacts, Attestation, NodeResult

# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------


def test_attestation_minimal() -> None:
    a = Attestation(status="complete")
    assert a.status == "complete"
    assert a.reasoning == ""


@pytest.mark.parametrize("status", ["complete", "partial", "blocked"])
def test_attestation_status_values(status: str) -> None:
    a = Attestation(status=status)  # type: ignore[arg-type]
    assert a.status == status


def test_attestation_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        Attestation(status="done")  # type: ignore[arg-type]


def test_attestation_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Attestation.model_validate({"status": "complete", "garbage": True})


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def test_artifacts_default_empty() -> None:
    a = Artifacts()
    assert a.diff is None
    assert a.commit_sha is None
    assert a.files_changed == []


def test_artifacts_with_diff_and_files() -> None:
    a = Artifacts(
        diff="--- a/x.py\n+++ b/x.py\n...",
        commit_sha="abc123",
        files_changed=[Path("x.py"), Path("y.py")],
    )
    assert a.commit_sha == "abc123"
    assert len(a.files_changed) == 2


def test_artifacts_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Artifacts.model_validate({"garbage": True})


# ---------------------------------------------------------------------------
# NodeResult
# ---------------------------------------------------------------------------


class _SampleContract(BaseModel):
    """Used to exercise the generic NodeResult[T]."""

    summary: str
    count: int = 0


def test_node_result_holds_typed_contract() -> None:
    result: NodeResult[_SampleContract] = NodeResult(
        contract=_SampleContract(summary="ok", count=3),
        attestation=Attestation(status="complete"),
    )
    assert result.contract.summary == "ok"
    assert result.contract.count == 3
    assert result.artifacts.files_changed == []


def test_node_result_with_artifacts() -> None:
    result: NodeResult[_SampleContract] = NodeResult(
        contract=_SampleContract(summary="x"),
        attestation=Attestation(status="partial", reasoning="ran out of time"),
        artifacts=Artifacts(commit_sha="deadbeef"),
    )
    assert result.attestation.reasoning == "ran out of time"
    assert result.artifacts.commit_sha == "deadbeef"


def test_node_result_validates_parametrized_contract_shape() -> None:
    """When parametrized with NodeResult[_SampleContract], malformed contract data fails."""
    with pytest.raises(ValidationError):
        NodeResult[_SampleContract].model_validate(
            {
                "contract": {"summary": 123, "count": "not-an-int"},
                "attestation": {"status": "complete"},
            }
        )


def test_node_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        NodeResult.model_validate(
            {
                "contract": _SampleContract(summary="x"),
                "attestation": Attestation(status="complete"),
                "garbage": True,
            }
        )


def test_node_result_requires_attestation() -> None:
    """Attestation is informational but mandatory — every node owes a self-report."""
    with pytest.raises(ValidationError):
        NodeResult.model_validate(
            {"contract": _SampleContract(summary="x")}
        )
