"""#285 — feature specs cannot hand-list a code-owned set without a guard."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
REGISTRY = REPO_ROOT / "registry.yaml"
PRE_CHANGE_ABSENT_TOKENS = frozenset(
    {"class family", "command surface", "reason vocabulary"}
)


def _feature_spec_section() -> str:
    text = SKILL.read_text()
    return text.split("## Feature spec\n", maxsplit=1)[1].split(
        "\n## Quality bar", maxsplit=1
    )[0]


def test_feature_spec_rule_prevents_hand_listed_code_owned_sets() -> None:
    section = _feature_spec_section()
    assert "must not enumerate a set the code owns" in section
    assert "Name the module that owns it" in section
    assert "pair it with a guard that derives the set from the code" in section


def test_feature_spec_guard_tokens_were_absent_before_this_change() -> None:
    section = _feature_spec_section()
    introduced = frozenset(
        token for token in PRE_CHANGE_ABSENT_TOKENS if token in section.casefold()
    )
    assert introduced == PRE_CHANGE_ABSENT_TOKENS, (
        "The #285 guard is keyed only on terms absent from the pre-change "
        "Feature spec section, so it cannot silently pass on a pre-existing rule."
    )


def test_spec_authoring_patch_version_matches_registry() -> None:
    header = re.search(r"guidance:spec-authoring@([\d.]+)", SKILL.read_text())
    entry = re.search(
        r"skills/spec-authoring/SKILL\.md:\s*\{[^}]*version:\s*([\d.]+)",
        REGISTRY.read_text(),
    )
    assert header and entry
    assert header.group(1) == entry.group(1) == "0.10.1"
