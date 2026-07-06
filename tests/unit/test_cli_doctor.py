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


def test_check_auth_passes_when_oauth_token_in_env() -> None:
    from harness.cli.doctor import check_auth

    # The recommended ~/bin/harness Docker wrapper injects CLAUDE_CODE_OAUTH_TOKEN
    # (extracted from the macOS Keychain) and mounts neither ANTHROPIC_API_KEY nor
    # ~/.claude — so the OAuth token alone must satisfy the auth check.
    status, msg = check_auth(env={"CLAUDE_CODE_OAUTH_TOKEN": "tok-test"}, claude_dir=None)
    assert status == "PASS"
    assert "CLAUDE_CODE_OAUTH_TOKEN" in msg


def test_check_auth_fails_on_expired_oauth_token() -> None:
    from harness.cli.doctor import check_auth

    # CAL-941: the wrapper also exports CLAUDE_CODE_OAUTH_EXPIRES_AT (epoch-ms).
    # When the token is the active credential but its expiry is in the past, the
    # check must FAIL loudly (an expired token 401s every in-container claude call)
    # rather than PASS on mere presence.
    status, msg = check_auth(
        env={
            "CLAUDE_CODE_OAUTH_TOKEN": "tok-stale",
            "CLAUDE_CODE_OAUTH_EXPIRES_AT": "1000",  # epoch-ms, long past
        },
        claude_dir=None,
        now_ms=2000,
    )
    assert status == "FAIL"
    assert "expired" in msg.lower()


def test_check_auth_passes_on_fresh_oauth_token_with_expiry() -> None:
    from harness.cli.doctor import check_auth

    # A token whose expiry is in the future passes.
    status, msg = check_auth(
        env={
            "CLAUDE_CODE_OAUTH_TOKEN": "tok-fresh",
            "CLAUDE_CODE_OAUTH_EXPIRES_AT": "9000",
        },
        claude_dir=None,
        now_ms=2000,
    )
    assert status == "PASS"
    assert "CLAUDE_CODE_OAUTH_TOKEN" in msg


def test_check_auth_passes_on_oauth_token_without_expiry() -> None:
    from harness.cli.doctor import check_auth

    # Backward compatible: no CLAUDE_CODE_OAUTH_EXPIRES_AT (older wrapper) — a
    # present non-empty token still passes; freshness is only asserted when the
    # expiry is supplied.
    status, _msg = check_auth(
        env={"CLAUDE_CODE_OAUTH_TOKEN": "tok-test"}, claude_dir=None, now_ms=2000
    )
    assert status == "PASS"


def test_check_auth_passes_on_non_integer_expiry() -> None:
    from harness.cli.doctor import check_auth

    # A malformed expiry must not crash nor spuriously FAIL — fall back to the
    # presence check.
    status, _msg = check_auth(
        env={
            "CLAUDE_CODE_OAUTH_TOKEN": "tok-test",
            "CLAUDE_CODE_OAUTH_EXPIRES_AT": "not-a-number",
        },
        claude_dir=None,
        now_ms=2000,
    )
    assert status == "PASS"


def test_check_auth_does_not_pass_on_empty_oauth_token(tmp_path: Path) -> None:
    from harness.cli.doctor import check_auth

    # The wrapper exports CLAUDE_CODE_OAUTH_TOKEN as an empty string when Keychain
    # extraction fails; a present-but-empty token is no usable credential, so the
    # check must not PASS on it.
    status, _msg = check_auth(
        env={"CLAUDE_CODE_OAUTH_TOKEN": ""}, claude_dir=tmp_path / "nonexistent"
    )
    assert status == "FAIL"


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
    # The FAIL message must name all three recognised credentials so the operator
    # knows every way to satisfy the check.
    assert "ANTHROPIC_API_KEY" in msg
    assert "CLAUDE_CODE_OAUTH_TOKEN" in msg
    assert "~/.claude" in msg


def test_check_git_passes_on_clean_output() -> None:
    from harness.cli.doctor import check_git

    status, msg = check_git(porcelain_output="")
    assert status == "PASS"


def test_check_git_warns_on_dirty_tree() -> None:
    from harness.cli.doctor import check_git

    status, msg = check_git(porcelain_output=" M harness/foo.py\n")
    assert status == "WARN"
    assert "uncommitted" in msg.lower() or "dirty" in msg.lower()


def test_check_git_does_not_pass_outside_a_repo() -> None:
    from harness.cli.doctor import check_git

    # Outside a git repo `git status --porcelain` exits 128 with empty stdout.
    # Inspecting only stdout would misread that as a clean tree and PASS; the
    # non-zero returncode must demote it away from PASS.
    status, msg = check_git(porcelain_output="", returncode=128)
    assert status != "PASS"
    assert "repo" in msg.lower() or "git" in msg.lower()


def test_check_git_version_passes_on_recent_git() -> None:
    from harness.cli.doctor import check_git_version

    # The host git shipped by recent macOS/Homebrew is well past the floor.
    status, msg = check_git_version(version_output="git version 2.50.1 (Apple Git-155)")
    assert status == "PASS"
    assert "2.50" in msg


def test_check_git_version_passes_at_exact_threshold() -> None:
    from harness.cli.doctor import check_git_version

    # The threshold is inclusive: 2.48 is the first git that understands the
    # relativeWorktrees extension, so exactly 2.48 must PASS.
    status, _msg = check_git_version(version_output="git version 2.48.0")
    assert status == "PASS"


def test_check_git_version_passes_on_newer_major() -> None:
    from harness.cli.doctor import check_git_version

    # A higher major must pass regardless of minor (3.0 > 2.48).
    status, _msg = check_git_version(version_output="git version 3.0.0")
    assert status == "PASS"


def test_check_git_version_fails_just_below_threshold() -> None:
    from harness.cli.doctor import check_git_version

    # 2.47 is one minor below the floor: the first relative-worktree create would
    # floor-raise the repo and then break every git op under this git, so FAIL.
    status, msg = check_git_version(version_output="git version 2.47.9")
    assert status == "FAIL"
    # The FAIL message must name the found version and the required floor so the
    # operator knows exactly what to upgrade.
    assert "2.47" in msg
    assert "2.48" in msg


def test_check_git_version_fails_on_old_apple_system_git() -> None:
    from harness.cli.doctor import check_git_version

    # The concrete host this guards: an un-upgraded macOS Apple system git, whose
    # version string carries a parenthetical suffix that must not defeat parsing.
    status, msg = check_git_version(version_output="git version 2.39.3 (Apple Git-146)")
    assert status == "FAIL"
    assert "2.39" in msg


def test_check_git_version_warns_when_unparseable() -> None:
    from harness.cli.doctor import check_git_version

    # If the version string cannot be parsed, the precondition for the check could
    # not be established — WARN rather than a spurious FAIL. This check FAILs only
    # on the condition it actually tests (a version below the floor).
    status, msg = check_git_version(version_output="not a git version string")
    assert status == "WARN"
    assert "git" in msg.lower()


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


def test_check_reviewer_passes_when_both_engines_present() -> None:
    from harness.cli.doctor import check_reviewer

    status, msg = check_reviewer(
        claude_path="/usr/local/bin/claude", codex_path="/usr/local/bin/codex"
    )
    assert status == "PASS"
    assert "claude" in msg.lower()
    assert "codex" in msg.lower()


def test_check_reviewer_fails_when_claude_missing() -> None:
    from harness.cli.doctor import check_reviewer

    # claude has been the default review engine since CAL-701 (review.py); a host
    # missing it fails `harness review` at runtime, so doctor must FAIL — not the
    # old WARN, which let a broken host pass. An explicit empty path forces the
    # not-found branch deterministically (None would trigger a real PATH lookup).
    status, msg = check_reviewer(claude_path="", codex_path="/usr/local/bin/codex")
    assert status == "FAIL"
    assert "claude" in msg.lower()


def test_check_reviewer_warns_when_only_codex_missing() -> None:
    from harness.cli.doctor import check_reviewer

    # codex is the opt-in cross-model second opinion (`--engine codex`); its
    # absence is not fatal because the default claude review still works, so a
    # missing codex is a WARN, not a FAIL.
    status, msg = check_reviewer(claude_path="/usr/local/bin/claude", codex_path="")
    assert status == "WARN"
    assert "codex" in msg.lower()


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


def test_doctor_command_exits_one_on_failure(tmp_path: Path) -> None:
    """A FAILing check must propagate as a non-zero (exit 1) CLI status.

    The pass/warn cases pin exit 0; without this, the FAIL → typer.Exit(code=1)
    path is unasserted at the CLI level. Force a deterministic auth FAIL: remove
    ANTHROPIC_API_KEY and supply an OAuth token whose expiry is in the past
    (CAL-941). That branch returns FAIL before the ~/.claude fallback, so it
    fails regardless of the host's home directory.
    """
    db = tmp_path / ".harness" / "harness.db"
    result = runner.invoke(
        app,
        ["doctor", "--db", str(db)],
        env={
            "ANTHROPIC_API_KEY": None,
            "CLAUDE_CODE_OAUTH_TOKEN": "tok-stale",
            "CLAUDE_CODE_OAUTH_EXPIRES_AT": "1000",
        },
    )
    assert result.exit_code == 1, result.stdout
    # Pin that exit 1 came from a real doctor FAIL line, not a stray exception.
    assert "[FAIL]" in result.stdout
    assert "auth" in result.stdout


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
    assert "reviewer" in out
    assert "cli" in out
    # The git-version check (CAL-979) must be wired into the aggregated command,
    # not merely defined as a function — pin its label in the real output.
    assert "git-version" in out


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
