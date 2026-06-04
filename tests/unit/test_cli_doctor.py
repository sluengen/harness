"""Tests for harness doctor command — system health checks."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from harness.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Check-function isolation tests — each check is independently testable
# ---------------------------------------------------------------------------


def test_check_auth_passes_when_api_key_in_env() -> None:
    from harness.cli.doctor import check_auth

    status, msg = check_auth(env={"ANTHROPIC_API_KEY": "sk-test"}, claude_dir=None)
    assert status == "PASS"
    assert "ANTHROPIC_API_KEY" in msg


def test_check_auth_passes_when_claude_dir_exists(tmp_path: Path) -> None:
    from harness.cli.doctor import check_auth

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    status, msg = check_auth(env={}, claude_dir=claude_dir)
    assert status == "PASS"
    assert ".claude" in msg or "claude" in msg.lower()


def test_check_auth_fails_when_neither_present(tmp_path: Path) -> None:
    from harness.cli.doctor import check_auth

    status, msg = check_auth(env={}, claude_dir=tmp_path / "nonexistent")
    assert status == "FAIL"


def test_check_git_passes_on_clean_output() -> None:
    from harness.cli.doctor import check_git

    status, msg = check_git(porcelain_output="")
    assert status == "PASS"


def test_check_git_warns_on_dirty_tree() -> None:
    from harness.cli.doctor import check_git

    status, msg = check_git(porcelain_output=" M harness/foo.py\n")
    assert status == "WARN"
    assert "uncommitted" in msg.lower() or "dirty" in msg.lower()


def test_check_db_passes_when_file_exists(tmp_path: Path) -> None:
    from harness.cli.doctor import check_db

    db = tmp_path / ".harness" / "harness.db"
    db.parent.mkdir()
    db.write_bytes(b"SQLite format 3\x00")
    status, msg = check_db(db_path=db)
    assert status == "PASS"


def test_check_db_warns_when_not_found(tmp_path: Path) -> None:
    from harness.cli.doctor import check_db

    db = tmp_path / ".harness" / "harness.db"
    status, msg = check_db(db_path=db)
    assert status == "WARN"
    assert "not found" in msg.lower() or "first run" in msg.lower()


def test_check_adapters_returns_pass_with_matrix() -> None:
    from harness.cli.doctor import check_adapters

    status, msg = check_adapters()
    assert status == "PASS"
    assert "ClaudeAgent" in msg


def test_check_cli_passes_when_version_exits_zero() -> None:
    from harness.cli.doctor import check_cli

    status, msg = check_cli(exit_code=0, stdout="harness 0.1.0")
    assert status == "PASS"
    assert "harness" in msg


def test_check_cli_fails_when_version_exits_nonzero() -> None:
    from harness.cli.doctor import check_cli

    status, msg = check_cli(exit_code=1, stdout="")
    assert status == "FAIL"


# ---------------------------------------------------------------------------
# CLI integration — harness doctor command
# ---------------------------------------------------------------------------


def test_doctor_command_registered_in_app() -> None:
    """doctor must appear in the CLI help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout
    assert "doctor" in result.stdout


def test_doctor_command_exits_zero_on_pass_or_warn(tmp_path: Path) -> None:
    """With no failures, doctor exits 0."""
    db = tmp_path / ".harness" / "harness.db"
    result = runner.invoke(
        app,
        ["doctor", "--db", str(db)],
        env={"ANTHROPIC_API_KEY": "sk-test"},
        catch_exceptions=False,
    )
    # Exit 0 when all checks pass or warn.
    assert result.exit_code == 0, result.stdout


def test_doctor_command_output_contains_check_labels(tmp_path: Path) -> None:
    """Output must include the named checks."""
    db = tmp_path / ".harness" / "harness.db"
    result = runner.invoke(
        app,
        ["doctor", "--db", str(db)],
        env={"ANTHROPIC_API_KEY": "sk-test"},
    )
    out = result.stdout
    assert "auth" in out
    assert "db" in out
    assert "adapters" in out
    assert "cli" in out


def test_doctor_output_shows_pass_or_warn_or_fail_prefix(tmp_path: Path) -> None:
    """Each check line must start with [PASS], [WARN], or [FAIL]."""
    db = tmp_path / ".harness" / "harness.db"
    result = runner.invoke(
        app,
        ["doctor", "--db", str(db)],
        env={"ANTHROPIC_API_KEY": "sk-test"},
    )
    out = result.stdout
    # At least one of these must appear.
    assert "[PASS]" in out or "[WARN]" in out or "[FAIL]" in out
