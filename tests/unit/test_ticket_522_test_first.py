"""Test-first evidence for ticket #522."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_generate_codex_artifacts import _fixture_repo, _module


def test_generation_does_not_create_legacy_codex_skill_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_repo(root)

    generator = _module()
    assert generator.main(["--root", str(root)]) == 0

    assert not (root / ".agents" / "skills").exists()
    assert not (root / ".codex" / "skills").exists()
