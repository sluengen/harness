"""Validate AUTHORING.md's YAML examples.

Three checks, in order of strictness:

1. The release-notes worked example exists on disk and validates against
   Workflow (this is the file a reader would copy from in §7).
2. Every ``` yaml block in AUTHORING.md parses as valid YAML.
3. Every yaml block that's a *full workflow* (has top-level ``name`` +
   ``steps``) validates against the Workflow schema.

Step-only snippets (single-step blocks that reference state fields without
the upstream steps to populate them) are intentionally NOT validated — they
are illustrative. The two full workflows (the minimal §1 example and the §7
release-notes example) are the strict gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from harness.workflow.schema import Workflow

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE_PATH = REPO_ROOT / "AUTHORING.md"
RELEASE_NOTES_PATH = REPO_ROOT / "workflows" / "release-notes.yaml"

_YAML_BLOCK = re.compile(r"```yaml\n(.*?)```", re.DOTALL)


def _yaml_blocks() -> list[str]:
    return _YAML_BLOCK.findall(GUIDE_PATH.read_text())


def test_release_notes_workflow_loads() -> None:
    """The §7 worked example exists and is a valid workflow."""
    wf = Workflow.model_validate(yaml.safe_load(RELEASE_NOTES_PATH.read_text()))
    assert wf.name == "release-notes"
    assert len(wf.steps) == 3


def test_authoring_guide_exists_and_has_yaml_examples() -> None:
    assert GUIDE_PATH.exists(), "AUTHORING.md should exist at the repo root"
    blocks = _yaml_blocks()
    assert blocks, "AUTHORING.md should contain at least one ```yaml block"


def test_every_yaml_block_parses() -> None:
    """No yaml syntax errors in any example."""
    for i, block_text in enumerate(_yaml_blocks()):
        try:
            yaml.safe_load(block_text)
        except yaml.YAMLError as e:
            pytest.fail(
                f"AUTHORING.md yaml block {i + 1} has YAML syntax errors:\n"
                f"{block_text}\nError: {e}"
            )


def test_every_full_workflow_block_validates() -> None:
    """Every block that's a full workflow validates against Workflow schema."""
    full_workflows: list[tuple[int, dict]] = []
    for i, block_text in enumerate(_yaml_blocks()):
        parsed = yaml.safe_load(block_text)
        if (
            isinstance(parsed, dict)
            and "name" in parsed
            and "steps" in parsed
            and isinstance(parsed["steps"], list)
        ):
            full_workflows.append((i + 1, parsed))

    assert len(full_workflows) >= 1, (
        "AUTHORING.md should contain at least one full workflow example "
        "(top-level name + steps)"
    )

    for block_num, parsed in full_workflows:
        try:
            Workflow.model_validate(parsed)
        except Exception as e:
            pytest.fail(
                f"AUTHORING.md yaml block {block_num} is a full workflow but "
                f"fails Workflow validation:\n{yaml.dump(parsed)}\nError: {e}"
            )
