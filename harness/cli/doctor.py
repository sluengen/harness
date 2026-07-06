"""``harness doctor`` — system health check."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import typer

from harness.state import store

# Minimum host git that understands the ``relativeWorktrees`` extension. Creating
# the first relative worktree stamps ``extensions.relativeWorktrees=true`` +
# ``repositoryformatversion=1`` into the repo-global ``.git/config`` — a permanent,
# repo-wide, one-way floor-raise — after which every git op fails
# ``fatal: unknown repository extension found: relativeworktrees`` under an older
# git (CAL-935/CAL-979). Compared as a ``(major, minor)`` tuple.
MIN_GIT_VERSION = (2, 48)

# ---------------------------------------------------------------------------
# Individual check functions — each returns (status, message).
# Accepting parameters makes them unit-testable without env coupling.
# ---------------------------------------------------------------------------


def check_auth(
    env: dict[str, str] | None = None,
    claude_dir: Path | None = None,
    now_ms: int | None = None,
) -> tuple[str, str]:
    """Pass if ANTHROPIC_API_KEY is set, CLAUDE_CODE_OAUTH_TOKEN is non-empty and
    unexpired, OR ~/.claude/ exists.

    ``CLAUDE_CODE_OAUTH_TOKEN`` is the credential the recommended ``~/bin/harness``
    Docker wrapper injects (extracted from the macOS Keychain); the wrapper mounts
    neither ``ANTHROPIC_API_KEY`` nor ``~/.claude``, so the token alone must pass.
    The wrapper forwards the variable as an empty string when Keychain extraction
    fails, so require a non-empty value — a present-but-empty token is no credential.

    Freshness (CAL-941): the wrapper also forwards ``CLAUDE_CODE_OAUTH_EXPIRES_AT``
    (epoch-ms). An *expired* access token 401s every in-container ``claude`` call —
    surfacing as a false ``review`` failure — so when the expiry is present and in
    the past this **FAILs loudly** rather than passing on mere presence. This is a
    backstop: the wrapper refreshes a stale token before it ever reaches here, so a
    FAIL means the refresh itself did not take (e.g. a dead refresh token → run
    ``claude -p ok`` / ``claude /login`` on the host). A missing or unparseable
    expiry falls back to the presence check (older wrapper / non-wrapper runs).
    """
    if env is None:
        import os

        env = dict(os.environ)
    if claude_dir is None:
        claude_dir = Path.home() / ".claude"

    if "ANTHROPIC_API_KEY" in env:
        return ("PASS", "ANTHROPIC_API_KEY set")
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        expires_at = env.get("CLAUDE_CODE_OAUTH_EXPIRES_AT")
        if expires_at:
            try:
                expires_ms = int(expires_at)
            except ValueError:
                expires_ms = None
            if expires_ms is not None:
                if now_ms is None:
                    import time

                    now_ms = int(time.time() * 1000)
                if now_ms >= expires_ms:
                    stale_min = (now_ms - expires_ms) // 60_000
                    return (
                        "FAIL",
                        f"CLAUDE_CODE_OAUTH_TOKEN expired {stale_min} min ago — "
                        "the wrapper's refresh did not take; run `claude -p ok` "
                        "(or `claude /login`) on the host to refresh the Keychain token",
                    )
        return ("PASS", "CLAUDE_CODE_OAUTH_TOKEN set")
    if claude_dir.exists():
        return ("PASS", f"{claude_dir} exists (Claude Code OAuth)")
    return (
        "FAIL",
        "none of ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, or ~/.claude/ found "
        "— see README §Authentication",
    )


def check_git(
    porcelain_output: str | None = None,
    returncode: int | None = None,
) -> tuple[str, str]:
    """Pass if the working tree is clean; warn if dirty or the CWD is not a repo.

    Outside a git repository ``git status --porcelain`` exits 128 with empty
    stdout; inspecting only stdout would misread that as a clean tree and PASS,
    so a non-zero returncode gates the result away from PASS.
    """
    if porcelain_output is None:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            porcelain_output = result.stdout
            returncode = result.returncode
        except (subprocess.TimeoutExpired, OSError):
            return ("WARN", "git not available or timed out")

    if returncode is not None and returncode != 0:
        return ("WARN", "not a git repository (git exited non-zero)")

    stripped = porcelain_output.strip()
    if not stripped:
        return ("PASS", "working tree clean")
    return ("WARN", f"working tree has uncommitted changes ({stripped.count(chr(10)) + 1} file(s))")


def check_git_version(
    version_output: str | None = None,
) -> tuple[str, str]:
    """FAIL if the git on PATH is below the ``MIN_GIT_VERSION`` floor; else PASS.

    Fail loud at setup, not mid-run (CAL-979): a host whose system git is < 2.48
    would have its repo silently floor-raised by the first relative-worktree
    create (see ``MIN_GIT_VERSION``) and then break for all its other tooling —
    the main checkout, the IDE, other contributors, CI on an old runner. The
    in-container git is 2.50, so this guards the *host* git.

    ``version_output`` injects the raw ``git --version`` stdout for tests; ``None``
    runs the real subprocess. A missing or unparseable git is a WARN — the
    precondition for the check could not be established (an entirely absent git is
    already flagged by ``check_git``) — so this FAILs only on the condition it
    actually tests: a git present but below the floor.
    """
    if version_output is None:
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return ("WARN", "could not determine git version (git --version exited non-zero)")
            version_output = result.stdout
        except (subprocess.TimeoutExpired, OSError):
            return ("WARN", "git not available or timed out")

    # ``git version 2.50.1 (Apple Git-155)`` → (2, 50); the parenthetical suffix
    # on Apple/packaged builds must not defeat the parse.
    match = re.search(r"git version (\d+)\.(\d+)", version_output)
    if match is None:
        return ("WARN", f"could not parse git version from {version_output.strip()!r}")

    found = (int(match.group(1)), int(match.group(2)))
    found_str = f"{found[0]}.{found[1]}"
    floor_str = f"{MIN_GIT_VERSION[0]}.{MIN_GIT_VERSION[1]}"
    if found >= MIN_GIT_VERSION:
        return ("PASS", f"git {found_str} >= {floor_str}")
    return (
        "FAIL",
        f"git {found_str} < {floor_str} — the first relative-worktree create would "
        "floor-raise this repo (repositoryformatversion=1) and break every git op "
        f"on it under this git; upgrade git to >= {floor_str}",
    )


def check_db(db_path: Path | None = None) -> tuple[str, str]:
    """Pass if harness.db exists and is readable; warn if not found."""
    if db_path is None:
        db_path = Path.cwd() / store.DEFAULT_DB_PATH

    if db_path.exists():
        try:
            # Probe readability with a single byte — the file only needs to be
            # openable, not slurped whole (it can grow large across many runs).
            with db_path.open("rb") as fh:
                fh.read(1)
            return ("PASS", f"{db_path} exists")
        except OSError as exc:
            return ("FAIL", f"{db_path} exists but is not readable: {exc}")
    return (
        "WARN",
        f"{db_path} not found (first run — created on first `harness run`)",
    )


def check_reviewer(
    claude_path: str | None = None,
    codex_path: str | None = None,
) -> tuple[str, str]:
    """Report whether the review-engine binaries are on PATH.

    ``review`` defaults to the ``claude`` engine (since CAL-701); ``codex`` is
    the opt-in ``--engine codex`` cross-model second opinion. A missing
    ``claude`` is therefore fatal to the default review path — it FAILs, where
    the old codex-only check would let such a host pass. A missing ``codex``
    only costs the optional second opinion, so it is a WARN. Pass ``""`` for
    either to force its not-found branch in tests (``None`` triggers a real
    PATH lookup).
    """
    import shutil

    if claude_path is None:
        claude_path = shutil.which("claude")
    if codex_path is None:
        codex_path = shutil.which("codex")

    if not claude_path:
        return (
            "FAIL",
            "claude not found on PATH — the default review engine; "
            "`harness review` will fail until it is installed",
        )
    if not codex_path:
        return (
            "WARN",
            f"claude at {claude_path}; codex not found on PATH — the opt-in "
            "`--engine codex` cross-model review is unavailable "
            "(default claude review still works)",
        )
    return ("PASS", f"claude at {claude_path}; codex at {codex_path}")


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
    from harness.cli._query_common import _resolve_db_path

    db_path = _resolve_db_path(db)

    typer.echo("harness doctor")
    typer.echo("==============")

    checks: list[tuple[str, tuple[str, str]]] = [
        ("auth", check_auth()),
        ("git", check_git()),
        ("git-version", check_git_version()),
        ("db", check_db(db_path)),
        ("reviewer", check_reviewer()),
        ("cli", check_cli()),
    ]

    any_fail = False
    for name, (status, msg) in checks:
        typer.echo(f"[{status}] {name:<12} {msg}")
        if status == "FAIL":
            any_fail = True

    if any_fail:
        raise typer.Exit(code=1)
