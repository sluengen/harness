"""CLI-level tests for the verbs' ``--repo`` invocation gate (CAL-584, #214).

Every verb that accepts ``--repo`` (``start`` / ``review`` / ``close``) inherits
both checks at its path-acceptance point: the ``HARNESS_WORKSPACE_ROOTS``
allowlist (CAL-584) and, on what the allowlist admits, the git-top-level check
(#214). Either rejection is reported the same way — **exit code 2** and a stderr
message naming the path — *before* any Linear, git, or DB side effect runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app
from tests._gitutil import init_repo

runner = CliRunner()


def _argv(verb: str, repo: Path) -> list[str]:
    """Build a minimal invocation for ``verb`` pointing ``--repo`` at ``repo``."""
    if verb == "start":
        return ["start", "CAL-1", "--repo", str(repo)]
    if verb == "review":
        return ["review", "--repo", str(repo)]
    if verb == "close":
        return ["close", "CAL-1", "--repo", str(repo)]
    raise AssertionError(f"unknown verb {verb!r}")


@pytest.mark.parametrize("verb", ["start", "review", "close"])
def test_verb_rejects_repo_outside_allowlist(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside" / "repo"
    outside.mkdir(parents=True)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(allowed))

    result = runner.invoke(app, _argv(verb, outside))

    assert result.exit_code == 2
    # The rejection is reported on stderr and names the rejected path.
    assert str(outside.resolve()) in result.stderr
    # Roots are configured here, so this is not a wrong-binary story (#246).
    assert "~/bin/harness" not in result.stderr


@pytest.mark.parametrize("verb", ["start", "review", "close"])
def test_verb_fails_closed_when_roots_unset(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.delenv("HARNESS_WORKSPACE_ROOTS", raising=False)

    result = runner.invoke(app, _argv(verb, repo))

    assert result.exit_code == 2
    assert str(repo.resolve()) in result.stderr
    # Empty roots usually means the native CLI ran where the wrapper should
    # have — name it (#246).
    assert "~/bin/harness" in result.stderr


@pytest.mark.parametrize("verb", ["start", "review", "close"])
def test_verb_rejects_a_subdirectory_of_a_real_repo(
    verb: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verb run one directory too deep refuses at the same gate (#214).

    The subdirectory is inside the allowlist, so only the git-top-level check
    catches it. Same contract as every other invocation refusal: **exit 2**,
    the path named on stderr, before any tracker, git, or DB side effect.
    """
    repo = init_repo(tmp_path / "repo")
    package_dir = repo / "harness"
    package_dir.mkdir()
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))

    result = runner.invoke(app, _argv(verb, package_dir))

    assert result.exit_code == 2
    assert str(package_dir.resolve()) in result.stderr
    # Exit 2 alone does not prove *this* refusal fired — an unconfigured
    # tracker key refuses with the same code further down the verb. Pin that we
    # stopped at the path-acceptance point, before any tracker work.
    assert "LINEAR_API_KEY" not in result.stdout
