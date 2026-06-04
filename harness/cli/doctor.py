"""``harness doctor`` — system health check."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from harness.state import store

# ---------------------------------------------------------------------------
# Individual check functions — each returns (status, message).
# Accepting parameters makes them unit-testable without env coupling.
# ---------------------------------------------------------------------------


def check_auth(
    env: dict[str, str] | None = None,
    claude_dir: Path | None = None,
) -> tuple[str, str]:
    """Pass if ANTHROPIC_API_KEY is set OR ~/.claude/ exists."""
    if env is None:
        import os

        env = dict(os.environ)
    if claude_dir is None:
        claude_dir = Path.home() / ".claude"

    if "ANTHROPIC_API_KEY" in env:
        return ("PASS", "ANTHROPIC_API_KEY set")
    if claude_dir.exists():
        return ("PASS", f"{claude_dir} exists (Claude Code OAuth)")
    return ("FAIL", "neither ANTHROPIC_API_KEY nor ~/.claude/ found — see README §Authentication")


def check_git(porcelain_output: str | None = None) -> tuple[str, str]:
    """Pass if the working tree is clean; warn if dirty."""
    if porcelain_output is None:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            porcelain_output = result.stdout
        except (subprocess.TimeoutExpired, OSError):
            return ("WARN", "git not available or timed out")

    stripped = porcelain_output.strip()
    if not stripped:
        return ("PASS", "working tree clean")
    return ("WARN", f"working tree has uncommitted changes ({stripped.count(chr(10)) + 1} file(s))")


def check_db(db_path: Path | None = None) -> tuple[str, str]:
    """Pass if harness.db exists and is readable; warn if not found."""
    if db_path is None:
        db_path = Path.cwd() / store.DEFAULT_DB_PATH

    if db_path.exists():
        try:
            db_path.read_bytes()
            return ("PASS", f"{db_path} exists")
        except OSError as exc:
            return ("FAIL", f"{db_path} exists but is not readable: {exc}")
    return (
        "WARN",
        f"{db_path} not found (first run — created on first `harness run`)",
    )


def check_adapters() -> tuple[str, str]:
    """Import ClaudeAgent and print its capability matrix."""
    from harness.dispatch.claude import ClaudeAgent

    cap = ClaudeAgent.capability
    matrix = (
        f"ClaudeAgent: submit={'✓' if cap.supports_submit_tool else '✗'} "
        f"cwd={'✓' if cap.supports_cwd else '✗'} "
        f"max_turns={'✓' if cap.supports_max_turns else '✗'} "
        f"tools={'✓' if cap.supports_tool_allowlist else '✗'}"
    )
    return ("PASS", matrix)


def check_cli(
    exit_code: int | None = None,
    stdout: str | None = None,
) -> tuple[str, str]:
    """Pass if ``harness version`` exits 0."""
    if exit_code is None:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "harness.cli", "version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            exit_code = result.returncode
            stdout = result.stdout
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ("FAIL", f"harness version subprocess failed: {exc}")

    if exit_code == 0:
        version_str = (stdout or "").strip()
        return ("PASS", version_str if version_str else "harness (version ok)")
    return ("FAIL", f"harness version exited {exit_code}")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def doctor_command(
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
) -> None:
    """Run system health checks."""
    from harness.cli.query import _resolve_db_path

    db_path = _resolve_db_path(db)

    typer.echo("harness doctor")
    typer.echo("==============")

    checks: list[tuple[str, tuple[str, str]]] = [
        ("auth", check_auth()),
        ("git", check_git()),
        ("db", check_db(db_path)),
        ("adapters", check_adapters()),
        ("cli", check_cli()),
    ]

    any_fail = False
    for name, (status, msg) in checks:
        typer.echo(f"[{status}] {name:<10} {msg}")
        if status == "FAIL":
            any_fail = True

    if any_fail:
        raise typer.Exit(code=1)
