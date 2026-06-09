"""Tests for workflow directory resolution fallback chain (HAR — portability).

``_resolve_workflows_dir`` in ``harness.cli.run`` implements the four-step
lookup described in the acceptance criteria:

1. Explicit ``--workflows-dir`` flag value (always wins).
2. ``$HARNESS_WORKFLOWS_DIR`` environment variable.
3. ``Path("workflows")`` relative to CWD when that directory exists.
4. ``importlib.resources.files("harness.workflows")`` — installed package data.

Each step is exercised in isolation; priority ordering is also asserted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.cli.run import _resolve_workflows_dir

# Repo root is two levels above this file (tests/unit/ → tests/ → repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOP_LEVEL_WORKFLOWS = _REPO_ROOT / "workflows"
_PKG_WORKFLOWS = _REPO_ROOT / "harness" / "workflows"

# ---------------------------------------------------------------------------
# Step 1 — explicit path
# ---------------------------------------------------------------------------


class TestExplicitPath:
    def test_explicit_path_returned_as_is(self, tmp_path: Path) -> None:
        """An explicit path is returned without modification."""
        result = _resolve_workflows_dir(tmp_path)
        assert result == tmp_path

    def test_explicit_beats_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit path wins even when HARNESS_WORKFLOWS_DIR is set."""
        monkeypatch.setenv("HARNESS_WORKFLOWS_DIR", "/should/be/ignored")
        result = _resolve_workflows_dir(tmp_path)
        assert result == tmp_path

    def test_explicit_beats_local_workflows_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit path wins even when a local ./workflows/ dir exists."""
        local_dir = tmp_path / "workflows"
        local_dir.mkdir()
        explicit = tmp_path / "custom"
        explicit.mkdir()
        monkeypatch.chdir(tmp_path)
        result = _resolve_workflows_dir(explicit)
        assert result == explicit


# ---------------------------------------------------------------------------
# Step 2 — HARNESS_WORKFLOWS_DIR env var
# ---------------------------------------------------------------------------


class TestEnvVar:
    def test_env_var_returned_as_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HARNESS_WORKFLOWS_DIR is converted to Path and returned."""
        monkeypatch.setenv("HARNESS_WORKFLOWS_DIR", str(tmp_path))
        monkeypatch.chdir(tmp_path)  # no workflows/ here
        result = _resolve_workflows_dir(None)
        assert result == tmp_path

    def test_env_var_beats_local_workflows_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HARNESS_WORKFLOWS_DIR wins over a local ./workflows/ directory."""
        env_dir = tmp_path / "env_wf"
        env_dir.mkdir()
        local_dir = tmp_path / "workflows"
        local_dir.mkdir()
        monkeypatch.setenv("HARNESS_WORKFLOWS_DIR", str(env_dir))
        monkeypatch.chdir(tmp_path)
        result = _resolve_workflows_dir(None)
        assert result == env_dir

    def test_env_var_beats_package_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HARNESS_WORKFLOWS_DIR wins over bundled package data."""
        env_dir = tmp_path / "custom_workflows"
        env_dir.mkdir()
        monkeypatch.setenv("HARNESS_WORKFLOWS_DIR", str(env_dir))
        monkeypatch.chdir(tmp_path)  # no local workflows/
        result = _resolve_workflows_dir(None)
        assert result == env_dir


# ---------------------------------------------------------------------------
# Step 3 — local ./workflows/ relative to CWD
# ---------------------------------------------------------------------------


class TestLocalWorkflowsDir:
    def test_local_dir_used_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``./workflows`` relative to CWD is the third fallback."""
        local_dir = tmp_path / "workflows"
        local_dir.mkdir()
        monkeypatch.delenv("HARNESS_WORKFLOWS_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        result = _resolve_workflows_dir(None)
        assert result == local_dir

    def test_local_dir_skipped_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ``./workflows`` doesn't exist, resolution falls through to
        package data — the result is a directory that does exist."""
        monkeypatch.delenv("HARNESS_WORKFLOWS_DIR", raising=False)
        monkeypatch.chdir(tmp_path)  # tmp_path has no workflows/
        result = _resolve_workflows_dir(None)
        # Must not return the non-existent local path.
        assert result.is_dir(), (
            f"Expected an existing directory from package-data fallback, got {result}"
        )


# ---------------------------------------------------------------------------
# Step 4 — package data (importlib.resources)
# ---------------------------------------------------------------------------


class TestPackageData:
    def test_package_data_is_an_existing_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Package data fallback resolves to a real, existing directory."""
        monkeypatch.delenv("HARNESS_WORKFLOWS_DIR", raising=False)
        monkeypatch.chdir(tmp_path)  # tmp_path has no workflows/
        result = _resolve_workflows_dir(None)
        assert result.is_dir(), f"Expected a directory, got {result}"

    def test_package_data_contains_build_workflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bundled package data includes build.yaml."""
        monkeypatch.delenv("HARNESS_WORKFLOWS_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        result = _resolve_workflows_dir(None)
        assert (result / "build.yaml").is_file(), (
            f"Expected build.yaml in package data at {result}"
        )

    def test_package_data_contains_all_bundled_workflows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All four canonical workflows are bundled in the package data."""
        monkeypatch.delenv("HARNESS_WORKFLOWS_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        result = _resolve_workflows_dir(None)
        expected = {"build.yaml", "build-codex.yaml", "release.yaml", "steward.yaml"}
        found = {p.name for p in result.iterdir() if p.suffix == ".yaml"}
        assert expected <= found, f"Missing workflows: {expected - found}"


# ---------------------------------------------------------------------------
# Mirror equivalence — harness/workflows/ must match workflows/
# ---------------------------------------------------------------------------


class TestPackageMirror:
    """Assert that ``harness/workflows/<name>.yaml`` is identical to
    ``workflows/<name>.yaml`` for every file in the top-level directory.

    ``harness/workflows/`` is a copy of ``workflows/`` used as installed
    package data. If they drift, the installed harness silently runs the
    wrong workflow definitions. This test is the single enforcement point.
    """

    def test_every_top_level_workflow_has_a_package_mirror(self) -> None:
        """Every ``workflows/*.yaml`` has a matching file in ``harness/workflows/``."""
        top_level = list(_TOP_LEVEL_WORKFLOWS.glob("*.yaml"))
        assert top_level, "Expected at least one workflow YAML in workflows/"
        for wf in top_level:
            mirror = _PKG_WORKFLOWS / wf.name
            assert mirror.is_file(), (
                f"harness/workflows/{wf.name} is missing — "
                f"add it to mirror workflows/{wf.name}"
            )

    def test_package_mirror_content_matches_top_level(self) -> None:
        """Each ``harness/workflows/<name>.yaml`` has identical content to
        the corresponding ``workflows/<name>.yaml``."""
        for wf in _TOP_LEVEL_WORKFLOWS.glob("*.yaml"):
            mirror = _PKG_WORKFLOWS / wf.name
            if not mirror.is_file():
                # test_every_top_level_workflow_has_a_package_mirror covers
                # the missing-file case; skip here to avoid a double-failure.
                continue
            assert wf.read_text() == mirror.read_text(), (
                f"harness/workflows/{wf.name} is out of sync with "
                f"workflows/{wf.name} — update both files together"
            )
