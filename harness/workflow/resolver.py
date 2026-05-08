"""`$contracts/<name>` reference resolver — SPEC §5 (H-007).

A workflow YAML may declare a contract in two forms:

* **Inline** — a YAML mapping under ``contract:`` (compiled by H-006).
* **Shared** — a string ``$contracts/<name>`` that names a file in the
  project's ``contracts/`` directory.

This module owns the *shared* form. It detects the reference, validates the
``<name>`` against a strict filename regex, loads ``contracts/<name>.yaml``,
and hands the resulting mapping to H-006's
:func:`harness.workflow.contract.compile_inline_contract`.

Scope:

* H-007 returns the same Pydantic-model artefact that
  :func:`compile_inline_contract` returns. A second tool-schema artefact is
  called out in SPEC §5 but lands in a later issue.
* The full Workflow-object scan that walks every step's ``contract:`` field
  is H-008's job; this module is the unit H-008 will call.

Errors:

* :class:`ContractRefError` covers everything that goes wrong *resolving* a
  reference: bad prefix, bad name, missing file, invalid YAML, non-mapping
  top-level YAML.
* A YAML mapping that loads cleanly but is structurally invalid as a
  contract surfaces :class:`ContractCompileError` from H-006 — it is *not*
  wrapped, so callers can distinguish "couldn't load" from "loaded but
  malformed".

Caching: deliberately omitted. Recompilation is cheap and adding a cache
before there's a measured need would couple us to a process-lifetime
assumption we don't yet need.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from harness.workflow.contract import compile_inline_contract

__all__ = [
    "CONTRACT_REF_PREFIX",
    "ContractRefError",
    "is_contract_ref",
    "resolve_contract_ref",
]

#: The reference prefix as fixed in SPEC §5. The remainder of the string is
#: the contract name and must satisfy :data:`_NAME_RE`.
CONTRACT_REF_PREFIX = "$contracts/"

# Same shape as the workflow `name:` regex in schema.py: lowercase letter
# leading, then lowercase letters / digits / underscores / hyphens. Crucially
# this rules out `.`, `/`, ``..``, leading hyphens/digits, and uppercase —
# every traversal vector lives in those forbidden characters, so we reject
# at the regex layer *before* the filesystem ever sees the value.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


class ContractRefError(ValueError):
    """Raised when a ``$contracts/<name>`` reference cannot be resolved.

    Covers: bad prefix, missing/invalid name, missing file, invalid YAML, and
    non-mapping top-level YAML. Does NOT cover schema-level errors in the
    contract itself — those propagate as
    :class:`harness.workflow.contract.ContractCompileError` from H-006.
    """


def is_contract_ref(spec: object) -> bool:
    """Return ``True`` iff ``spec`` is a string starting with ``$contracts/``.

    Cheap predicate H-008's loader can use to branch between inline-dict
    handling and reference resolution. Implemented as a function (rather
    than left as an inline check at the call site) because callers reading
    ``if is_contract_ref(...)`` get the intent immediately, and the test
    suite pins the prefix once instead of once per call site.
    """
    return isinstance(spec, str) and spec.startswith(CONTRACT_REF_PREFIX)


def resolve_contract_ref(ref: str, contracts_root: Path) -> type[BaseModel]:
    """Resolve ``$contracts/<name>`` to a Pydantic model.

    Args:
        ref: The reference string. Must start with ``$contracts/`` and the
            remainder must match ``^[a-z][a-z0-9_-]*$``.
        contracts_root: Directory containing ``<name>.yaml`` files.

    Returns:
        A :class:`pydantic.BaseModel` subclass — the same artefact type that
        :func:`compile_inline_contract` returns when called with an inline
        dict. The model's ``__name__`` is ``Contract_<safe-name>``, where
        hyphens become underscores so it is a valid Python identifier.

    Raises:
        ContractRefError: bad prefix, bad name, missing file, invalid YAML,
            traversal attempt, or non-mapping top-level YAML.
        ContractCompileError: the YAML mapping is malformed as a contract
            (propagated unchanged from H-006 so callers can distinguish
            resolution errors from compile errors).
    """
    if not is_contract_ref(ref):
        raise ContractRefError(
            f"invalid contract reference {ref!r}: must start with "
            f"{CONTRACT_REF_PREFIX!r}"
        )

    name = ref[len(CONTRACT_REF_PREFIX) :]
    if not _NAME_RE.fullmatch(name):
        raise ContractRefError(
            f"invalid contract name {name!r} in reference {ref!r}: "
            f"name must match {_NAME_RE.pattern} "
            f"(lowercase letter leading, then lowercase letters, digits, "
            f"underscores, or hyphens)"
        )

    contract_path = contracts_root / f"{name}.yaml"
    if not contract_path.is_file():
        raise ContractRefError(
            f"contract reference {ref!r} could not be resolved: "
            f"no such file at {contract_path}"
        )

    raw_text = contract_path.read_text()
    try:
        loaded: Any = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ContractRefError(
            f"contract reference {ref!r}: invalid YAML in "
            f"{contract_path}: {exc}"
        ) from exc

    if not isinstance(loaded, dict):
        raise ContractRefError(
            f"contract reference {ref!r}: top-level YAML in "
            f"{contract_path} must be a mapping, got "
            f"{type(loaded).__name__}"
        )

    # Hyphens are not legal in Python identifiers; underscores keep the
    # generated model name readable in tracebacks while remaining valid.
    model_name = f"Contract_{name.replace('-', '_')}"
    return compile_inline_contract(loaded, name=model_name)
