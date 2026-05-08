"""Tests for harness.workflow.resolver — `$contracts/<name>` reference
resolver (H-007).

The resolver detects a `$contracts/<name>` string reference, loads
`<contracts_root>/<name>.yaml`, and compiles the YAML mapping to a Pydantic
model via H-006's :func:`compile_inline_contract`. The resolver itself is the
deliverable; the workflow-level wiring is H-008's job.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from harness.workflow.contract import (
    ContractCompileError,
    compile_inline_contract,
)
from harness.workflow.resolver import (
    CONTRACT_REF_PREFIX,
    ContractRefError,
    is_contract_ref,
    resolve_contract_ref,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


REVIEW_VERDICT_YAML = """\
status:
  type: string
  enum: [PASS, FAIL]
issues:
  type: list
  of:
    severity: string
    description: string
blocking: boolean
"""


@pytest.fixture
def contracts_root(tmp_path: Path) -> Path:
    root = tmp_path / "contracts"
    root.mkdir()
    return root


@pytest.fixture
def review_verdict_file(contracts_root: Path) -> Path:
    path = contracts_root / "review-verdict.yaml"
    path.write_text(REVIEW_VERDICT_YAML)
    return path


# ---------------------------------------------------------------------------
# AC1 — happy path: $contracts/<name> resolves to a working Pydantic model
# ---------------------------------------------------------------------------


def test_happy_path_resolves_to_pydantic_model(
    review_verdict_file: Path, contracts_root: Path
) -> None:
    model_cls = resolve_contract_ref("$contracts/review-verdict", contracts_root)
    assert issubclass(model_cls, BaseModel)


def test_happy_path_model_validates_documented_shape(
    review_verdict_file: Path, contracts_root: Path
) -> None:
    model_cls = resolve_contract_ref("$contracts/review-verdict", contracts_root)
    instance = model_cls.model_validate(
        {
            "status": "PASS",
            "issues": [{"severity": "low", "description": "nit"}],
            "blocking": False,
        }
    )
    assert instance.model_dump() == {
        "status": "PASS",
        "issues": [{"severity": "low", "description": "nit"}],
        "blocking": False,
    }


def test_happy_path_model_rejects_invalid_payload(
    review_verdict_file: Path, contracts_root: Path
) -> None:
    model_cls = resolve_contract_ref("$contracts/review-verdict", contracts_root)
    # status enum violation
    with pytest.raises(ValidationError):
        model_cls.model_validate(
            {"status": "MAYBE", "issues": [], "blocking": False}
        )


def test_happy_path_model_name_is_derived_from_ref(
    review_verdict_file: Path, contracts_root: Path
) -> None:
    """Model name should be deterministic and readable. Hyphens become
    underscores so the symbol is a valid Python identifier."""
    model_cls = resolve_contract_ref("$contracts/review-verdict", contracts_root)
    assert model_cls.__name__ == "Contract_review_verdict"


# ---------------------------------------------------------------------------
# AC2 — non-ref strings + malformed refs rejected with ContractRefError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ref",
    [
        "foo",
        "$state.x",
        "$contracts",  # no slash
        "$contracts/",  # empty name
    ],
)
def test_invalid_ref_strings_raise_contract_ref_error(
    bad_ref: str, contracts_root: Path
) -> None:
    with pytest.raises(ContractRefError):
        resolve_contract_ref(bad_ref, contracts_root)


def test_is_contract_ref_returns_true_for_valid_prefix() -> None:
    assert is_contract_ref("$contracts/review-verdict") is True


@pytest.mark.parametrize(
    "value",
    [
        "foo",
        "$state.x",
        "",
        42,
        None,
        {"type": "string"},
        ["$contracts/x"],
    ],
)
def test_is_contract_ref_returns_false_for_non_refs(value: object) -> None:
    assert is_contract_ref(value) is False


def test_contract_ref_prefix_is_dollar_contracts_slash() -> None:
    """The prefix is load-bearing — pin it so accidental drift fails loudly."""
    assert CONTRACT_REF_PREFIX == "$contracts/"


# ---------------------------------------------------------------------------
# AC3 — missing file raises ContractRefError mentioning the path
# ---------------------------------------------------------------------------


def test_missing_file_raises_with_path_in_message(contracts_root: Path) -> None:
    with pytest.raises(ContractRefError) as excinfo:
        resolve_contract_ref("$contracts/does-not-exist", contracts_root)
    msg = str(excinfo.value)
    assert "does-not-exist" in msg
    # The expected file path should appear so the error guides the author to
    # the missing file.
    assert "does-not-exist.yaml" in msg


# ---------------------------------------------------------------------------
# AC4 — path traversal rejected by the name regex BEFORE filesystem access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "../etc/passwd",
        "foo/bar",
        ".hidden",
        "foo..bar",  # `..` anywhere is suspicious; regex disallows dots
        "ABS",  # uppercase rejected by `^[a-z]...` regex
        "1leading-digit",
        "-leading-hyphen",
        "name with space",
        "name.with.dot",
    ],
)
def test_traversal_and_unsafe_names_rejected_before_io(
    bad_name: str, contracts_root: Path
) -> None:
    """The name regex must reject these BEFORE we touch the filesystem.

    Even if a file with such a name happened to exist, the resolver must not
    open it. We assert by checking that the error path is the regex one (not
    a "missing file" message), and we additionally guard by *not* creating
    any matching file.
    """
    ref = f"{CONTRACT_REF_PREFIX}{bad_name}"
    with pytest.raises(ContractRefError) as excinfo:
        resolve_contract_ref(ref, contracts_root)
    msg = str(excinfo.value).lower()
    # The error must come from name validation, not from filesystem lookup.
    assert "name" in msg or "invalid" in msg


# ---------------------------------------------------------------------------
# AC5 — invalid YAML wraps as ContractRefError
# ---------------------------------------------------------------------------


def test_invalid_yaml_raises_contract_ref_error(contracts_root: Path) -> None:
    bad = contracts_root / "broken.yaml"
    bad.write_text("status: [unclosed\n")  # malformed YAML
    with pytest.raises(ContractRefError) as excinfo:
        resolve_contract_ref("$contracts/broken", contracts_root)
    # Caller gets a single resolution-error class, not a yaml.YAMLError.
    msg = str(excinfo.value).lower()
    assert "yaml" in msg or "parse" in msg or "invalid" in msg


# ---------------------------------------------------------------------------
# AC6 — non-mapping top-level YAML raises ContractRefError
# ---------------------------------------------------------------------------


def test_top_level_list_raises_contract_ref_error(contracts_root: Path) -> None:
    listy = contracts_root / "listy.yaml"
    listy.write_text("- one\n- two\n")
    with pytest.raises(ContractRefError, match="mapping"):
        resolve_contract_ref("$contracts/listy", contracts_root)


def test_top_level_scalar_raises_contract_ref_error(contracts_root: Path) -> None:
    scalar = contracts_root / "scalar.yaml"
    scalar.write_text("just-a-string\n")
    with pytest.raises(ContractRefError, match="mapping"):
        resolve_contract_ref("$contracts/scalar", contracts_root)


def test_empty_yaml_file_raises_contract_ref_error(contracts_root: Path) -> None:
    """Empty file → yaml.safe_load returns None, which is not a mapping."""
    empty = contracts_root / "empty.yaml"
    empty.write_text("")
    with pytest.raises(ContractRefError, match="mapping"):
        resolve_contract_ref("$contracts/empty", contracts_root)


# ---------------------------------------------------------------------------
# AC7 — ContractCompileError propagates unchanged
# ---------------------------------------------------------------------------


def test_compile_error_propagates_unchanged(contracts_root: Path) -> None:
    """A YAML mapping that's structurally fine but compiles to a bad contract
    (unknown leaf type) raises ContractCompileError, NOT ContractRefError.

    Callers distinguish "couldn't load the file" (resolution) from "the
    contract is malformed" (compile)."""
    bad = contracts_root / "bad-type.yaml"
    bad.write_text("x: float\n")  # 'float' is not a recognised leaf type
    with pytest.raises(ContractCompileError):
        resolve_contract_ref("$contracts/bad-type", contracts_root)


def test_compile_error_is_not_caught_as_ref_error(contracts_root: Path) -> None:
    """Defensive: ContractCompileError must NOT be a subclass of
    ContractRefError, and the resolver must not wrap it."""
    bad = contracts_root / "bad-type.yaml"
    bad.write_text("x: float\n")
    with pytest.raises(ContractCompileError) as excinfo:
        resolve_contract_ref("$contracts/bad-type", contracts_root)
    assert not isinstance(excinfo.value, ContractRefError)


# ---------------------------------------------------------------------------
# AC8 — resolver result is shape-equivalent to compile_inline_contract
# ---------------------------------------------------------------------------


def test_resolver_result_matches_direct_compile(
    review_verdict_file: Path, contracts_root: Path
) -> None:
    """Whether you reach a contract via inline dict or `$contracts/<name>`,
    you get the same artefact type and the same validation behaviour."""
    resolved = resolve_contract_ref("$contracts/review-verdict", contracts_root)

    # The same spec, compiled directly via H-006, should accept and reject the
    # same payloads.
    direct_spec = {
        "status": {"type": "string", "enum": ["PASS", "FAIL"]},
        "issues": {
            "type": "list",
            "of": {"severity": "string", "description": "string"},
        },
        "blocking": "boolean",
    }
    direct = compile_inline_contract(direct_spec, name="Contract_review_verdict")

    payload = {
        "status": "PASS",
        "issues": [{"severity": "low", "description": "nit"}],
        "blocking": False,
    }
    assert resolved.model_validate(payload).model_dump() == direct.model_validate(
        payload
    ).model_dump()

    # Both reject the same bad payload.
    with pytest.raises(ValidationError):
        resolved.model_validate({"status": "PASS", "issues": [], "blocking": "nope"})
    with pytest.raises(ValidationError):
        direct.model_validate({"status": "PASS", "issues": [], "blocking": "nope"})


def test_resolver_returns_basemodel_subclass(
    review_verdict_file: Path, contracts_root: Path
) -> None:
    model_cls = resolve_contract_ref("$contracts/review-verdict", contracts_root)
    assert issubclass(model_cls, BaseModel)
