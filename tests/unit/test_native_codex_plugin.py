"""The repository ships one plugin identity through Claude and Codex.

These are tree-consistency checks over machine-readable distribution artifacts:
the native manifest must describe the same release as the Claude manifest, and
the repo marketplace must resolve that native plugin from this repository root.
"""

from __future__ import annotations

import json
import re

from tests.unit._prose import REPO_ROOT

CLAUDE_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST = REPO_ROOT / ".codex-plugin" / "plugin.json"
CODEX_MARKETPLACE = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_native_manifest_is_the_same_plugin_release() -> None:
    claude = _json(CLAUDE_MANIFEST)
    codex = _json(CODEX_MANIFEST)

    assert codex["name"] == claude["name"] == "harness"
    assert codex["version"] == claude["version"]
    assert codex["description"] == claude["description"]
    assert codex["skills"] == "./skills/"
    assert "hooks" not in codex, "Codex discovers the default hooks/hooks.json path"
    assert codex["interface"]["displayName"] == "Harness"
    assert codex["interface"]["category"] == "Developer Tools"


def test_repo_marketplace_exposes_the_native_plugin_root() -> None:
    marketplace = _json(CODEX_MARKETPLACE)
    entries = marketplace["plugins"]

    assert marketplace["name"] == "harness"
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "harness"
    assert entry["source"] == {"source": "local", "path": "./"}
    assert entry["policy"] == {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL",
    }
    assert entry["category"] == "Developer Tools"


def test_every_portable_skill_resolves_its_plugin_asset_references() -> None:
    """Installed skills live at ``<plugin>/skills/<name>/SKILL.md``.

    Paths owned by the plugin must therefore resolve from the plugin root two
    directories above the skill file, not from the consumer workspace.
    """
    asset = re.compile(
        r"`((?:commands|skills|agents|templates|hooks|\.codex)/[^`\s]+)`"
    )
    generated = sorted((REPO_ROOT / "skills").glob("command-*/SKILL.md")) + sorted(
        (REPO_ROOT / "skills").glob("agent-*/SKILL.md")
    )
    assert generated

    for skill in generated:
        text = skill.read_text(encoding="utf-8")
        assert "two directories above this SKILL.md" in text
        plugin_root = skill.parents[2]
        for reference in asset.findall(text):
            if any(char in reference for char in "*<>{}"):
                continue
            assert (plugin_root / reference).exists(), (
                f"{skill.relative_to(REPO_ROOT)} names missing plugin asset {reference}"
            )


def test_every_legacy_command_skill_resolves_its_plugin_asset_references() -> None:
    """Legacy ``.codex`` discovery has one additional directory level."""
    asset = re.compile(
        r"`((?:commands|skills|agents|templates|hooks|\.codex)/[^`\s]+)`"
    )
    generated = sorted(
        (REPO_ROOT / ".codex" / "skills").glob("command-*/SKILL.md")
    )
    assert generated

    for skill in generated:
        text = skill.read_text(encoding="utf-8")
        assert "three directories above this SKILL.md" in text
        plugin_root = skill.parents[3]
        for reference in asset.findall(text):
            if any(char in reference for char in "*<>{}"):
                continue
            assert (plugin_root / reference).exists(), (
                f"{skill.relative_to(REPO_ROOT)} names missing plugin asset {reference}"
            )
