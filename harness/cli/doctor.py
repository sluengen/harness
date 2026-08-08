"""``harness doctor`` — system health check."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal, NamedTuple

import typer

from harness.cli._repo import REPO_OPTION

# size: one cohesive health-check module — each `check_*` function is a small,
# independent, injectable probe (auth, git, engines, gh, ...) plus the single
# `doctor_command` that aggregates and labels them. Splitting the checks into a
# sibling module would separate them from the `checks` list / label pairing
# their own tests pin (test_doctor_command_output_contains_check_labels),
# scattering one cohesive surface across files for no cohesion gain.

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


def check_codex_auth(
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> tuple[str, str]:
    """Pass only when the Codex CLI reports an active login."""
    if run is None:
        run = subprocess.run
    try:
        result = run(
            ["codex", "login", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return (
            "FAIL",
            "could not run `codex login status` — install Codex and authenticate",
        )
    if result.returncode != 0:
        return (
            "FAIL",
            "Codex is not authenticated — run `codex login` before Codex-only work",
        )
    return ("PASS", "Codex login active")


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


def check_db(db_path: Path) -> tuple[str, str]:
    """Pass if harness.db exists and is readable; warn if not found.

    The path is required: since #306 the command resolves it once, through the
    one repo seam, and hands it down. A ``None`` default here would be a second
    ambient read of the working directory — the bug class ADR 0012 retires.
    """
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


class EngineProbe(NamedTuple):
    """The result of probing one review engine.

    ``outcome`` is one of ``"absent"`` (not on PATH), ``"cannot_run"`` (on PATH
    but its ``--version`` liveness probe could not run here), or ``"ok"`` (on
    PATH and the probe ran). ``path`` is the resolved binary path, or ``None``
    when absent. The three-way outcome is the whole point of CAL-1083: a binary
    on PATH is not proof it can run.
    """

    outcome: str
    path: str | None


def _probe_engine(
    binary: str,
    which: Callable[[str], str | None] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> EngineProbe:
    """Resolve ``binary`` on PATH and run ``<binary> --version`` as a liveness probe.

    Distinguishes *not installed* (``absent``) from *installed but cannot execute
    here* (``cannot_run``) — the distinction doctor's PATH-only check could not
    draw. A ``--version`` probe is deliberately minimal: it proves the binary
    **launches** in this environment without invoking the engine's review
    sandbox. Per ADR 0002, codex's real review shells out through ``bwrap``,
    which a ``--version`` never touches — so a passing probe proves launch, not
    that a cross-model review will run in-container. A binary that is on PATH but
    exits non-zero or cannot be exec'd at all (``OSError``) is ``cannot_run``, not
    ``absent`` — it was found, it just does not work here.

    ``which`` / ``run`` are injectable for tests; ``None`` uses the real
    ``shutil.which`` / ``subprocess.run``.
    """
    if which is None:
        which = shutil.which
    path = which(binary)
    if not path:
        return EngineProbe("absent", None)
    if run is None:
        run = subprocess.run
    try:
        result = run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return EngineProbe("cannot_run", path)
    if result.returncode != 0:
        return EngineProbe("cannot_run", path)
    return EngineProbe("ok", path)


def check_reviewer(
    claude_probe: EngineProbe | None = None,
    codex_probe: EngineProbe | None = None,
    engine: Literal["claude", "codex"] = "claude",
) -> tuple[str, str]:
    """Report whether the review engines can actually *run*, not just resolve on PATH.

    ``review`` defaults to the ``claude`` engine (since CAL-701); ``codex`` is the
    opt-in ``--engine codex`` cross-model second opinion. Doctor probes each with
    ``<binary> --version`` (CAL-1083), because a binary on PATH is not proof it
    runs here — in the ``harness:dev`` container ``codex`` is always on PATH but a
    real review cannot run (ADR 0002).

    - **claude** is the default engine, so *every* failure mode is fatal: absent
      → FAIL; on PATH but its probe cannot run → FAIL naming the wall (a PATH-only
      check would have let this host pass).
    - **codex** is optional, so the two failure modes differ. Simply *absent* is a
      WARN — the default claude review still works. But *on PATH yet unable to
      run* is a misconfiguration worth failing on: FAIL naming the wall and citing
      ADR 0002 (the unprivileged container cannot open the user namespace codex's
      ``bwrap`` sandbox needs; a genuine ``--engine codex`` review is host-only).

    Pass an :class:`EngineProbe` for either to force a branch in tests; ``None``
    runs the real probe.
    """
    if codex_probe is None:
        codex_probe = _probe_engine("codex")

    if engine == "codex":
        if codex_probe.outcome == "absent":
            return (
                "FAIL",
                "codex not found on PATH — the selected Codex review engine "
                "cannot run",
            )
        if codex_probe.outcome == "cannot_run":
            return (
                "FAIL",
                f"codex at {codex_probe.path} is on PATH but its liveness probe "
                "(`codex --version`) could not run here",
            )
        return ("PASS", f"codex runs ({codex_probe.path})")

    if claude_probe is None:
        claude_probe = _probe_engine("claude")

    # claude — the default engine — is fatal in every failure mode.
    if claude_probe.outcome == "absent":
        return (
            "FAIL",
            "claude not found on PATH — the default review engine; "
            "`harness review` will fail until it is installed",
        )
    if claude_probe.outcome == "cannot_run":
        return (
            "FAIL",
            f"claude at {claude_probe.path} is on PATH but its liveness probe "
            "(`claude --version`) could not run here — installed but cannot "
            "execute; `harness review` will fail on the default engine",
        )

    # claude runs — assess the opt-in codex engine.
    if codex_probe.outcome == "absent":
        return (
            "WARN",
            f"claude runs ({claude_probe.path}); codex not found on PATH — the "
            "opt-in `--engine codex` cross-model review is unavailable "
            "(default claude review still works)",
        )
    if codex_probe.outcome == "cannot_run":
        return (
            "FAIL",
            f"codex at {codex_probe.path} is on PATH but its liveness probe "
            "(`codex --version`) could not run here — installed but cannot "
            "execute (ADR 0002: codex's bwrap sandbox needs a user namespace the "
            "unprivileged container cannot open; a genuine `--engine codex` "
            "review is host-only)",
        )
    return (
        "PASS",
        f"claude runs ({claude_probe.path}); codex runs ({codex_probe.path}) "
        "— note ADR 0002: a real `--engine codex` review is host-only, which "
        "`--version` cannot verify",
    )


def check_gh(gh_probe: EngineProbe | None = None) -> tuple[str, str]:
    """Report whether the ``gh`` binary can actually *run*, not just resolve on PATH.

    ``harness promote pr``'s release-hop publication step shells out to ``gh pr
    create`` (:mod:`harness.promotion_pr`, #187) — it is the only seam that needs
    it. Every other verb runs without ``gh``, so unlike :func:`check_reviewer`'s
    treatment of the default ``claude`` engine, absence here is never fatal:
    *absent* and *on PATH but unable to run* are both WARN, naming the wall so a
    ``promote pr`` failure is diagnosable ahead of time rather than as a bare
    ``pr_create_failed`` refusal.

    Pass an :class:`EngineProbe` to force a branch in tests; ``None`` runs the
    real probe.
    """
    if gh_probe is None:
        gh_probe = _probe_engine("gh")

    if gh_probe.outcome == "absent":
        return (
            "WARN",
            "gh not found on PATH — `harness promote pr`'s release-hop "
            "publication step will fail until it is installed (every other "
            "verb runs without it)",
        )
    if gh_probe.outcome == "cannot_run":
        return (
            "WARN",
            f"gh at {gh_probe.path} is on PATH but its liveness probe "
            "(`gh --version`) could not run here — installed but cannot "
            "execute; `harness promote pr`'s release-hop publication step "
            "will fail",
        )
    return ("PASS", f"gh runs ({gh_probe.path})")


def check_verify_config(repo_root: Path) -> tuple[str, str]:
    """WARN when the repo's ``CONTEXT.md`` configures no ``verify:`` gate command.

    Under the CAL-1082 evidence model ``review`` records an unconfigured gate
    honestly (``gate_reason='not_configured'``) and proceeds — the harness cannot
    gate what a repo does not define — but an unenforced gate is worth surfacing:
    a ``pass`` for such a repo certifies only that a reviewer ran, with no test
    evidence behind it. This is a **WARN, not a FAIL**: a repo may legitimately
    define no gate, and doctor must not block it. Reuses
    :func:`harness.gate.load_gate_command` (``None`` for both an absent
    ``CONTEXT.md`` and a missing ``verify:`` key) rather than re-parsing.
    """
    from harness.gate import load_gate_command

    command = load_gate_command(repo_root)
    if command:
        return ("PASS", f"verify gate configured: {command}")
    return (
        "WARN",
        "no `verify:` command in CONTEXT.md — `review` records the gate as "
        "`not_configured` and proceeds, so a `pass` for this repo carries no "
        "test evidence and the merge gate is unenforced",
    )


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


# The one-line remedy the wrapper-drift messages point at.
_RESYMLINK = (
    'ln -sf <repo>/docker/harness-wrapper.sh "$(command -v harness)" '
    "(see docker/README.md)"
)


def check_wrapper(
    env: dict[str, str] | None = None,
    in_container: bool | None = None,
) -> tuple[str, str]:
    """Pass if the ``harness`` wrapper on ``PATH`` is a symlink to the versioned
    ``docker/harness-wrapper.sh``; FAIL if it is a drifted or detached copy.

    A hand-copied ``~/bin/harness`` silently rots: a shipped wrapper fix (the
    image-staleness guard, credential-path fixes) is inert until someone
    re-copies by hand, and nothing tells them to (CAL-1149). ``doctor`` is the
    external observer that catches it — the wrapper cannot check itself, since a
    stale copy would be running the stale check.

    doctor runs *in-container*, where ``~/bin/harness`` is not mounted, so it
    cannot read the on-PATH wrapper directly. The wrapper does the comparison
    host-side (the one place both it and its versioned source are readable) and
    forwards the verdict as ``HARNESS_WRAPPER_STATUS`` — ``symlink`` (a symlink
    into the checkout), ``copy`` (a byte-identical copy, not yet drifted but it
    will), ``drifted`` (a copy already behind its source), or ``detached`` (a
    copy outside any checkout, with no source to track).

    When the variable is **absent**, the wrapper predates this check — or doctor
    was not run through the wrapper at all. Those two are told apart by
    container-presence, the signal AC-3 turns on: only the wrapper starts the
    container, so *in-container with no verdict* is an old wrapper that could not
    self-report (a stale copy → FAIL), while *not in a container* is a native run
    with no wrapper on PATH to drift (→ PASS). That is the distinction between a
    "drifted copy" and "a wrapper not on PATH at all".
    """
    if env is None:
        import os

        env = dict(os.environ)
    if in_container is None:
        in_container = Path("/.dockerenv").exists()

    status = env.get("HARNESS_WRAPPER_STATUS")
    if status == "symlink":
        return ("PASS", "wrapper on PATH is symlinked to docker/harness-wrapper.sh")
    if status == "copy":
        return (
            "WARN",
            "wrapper on PATH is a copy, not a symlink — it will drift as the repo "
            f"moves; re-symlink: {_RESYMLINK}",
        )
    if status == "drifted":
        return (
            "FAIL",
            "wrapper on PATH has drifted from docker/harness-wrapper.sh — shipped "
            f"wrapper fixes are not running; re-symlink: {_RESYMLINK}",
        )
    if status == "detached":
        return (
            "FAIL",
            "wrapper on PATH is a detached copy outside any checkout — it silently "
            f"rots as fixes ship; re-symlink: {_RESYMLINK}",
        )
    # No verdict forwarded.
    if in_container:
        return (
            "FAIL",
            "wrapper on PATH predates the drift check (CAL-1149) and did not "
            f"self-report — it is a stale copy; re-symlink: {_RESYMLINK}",
        )
    return (
        "PASS",
        "not run via the Docker wrapper (native install) — no wrapper on PATH to check",
    )


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def doctor_command(
    repo: Path | None = REPO_OPTION,
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
    engine: Literal["claude", "codex"] = typer.Option(  # noqa: B008
        "claude",
        "--engine",
        help="Engine whose authentication and liveness must be ready.",
    ),
) -> None:
    """Run system health checks."""
    from harness.cli._query_common import _resolve_db_path
    from harness.cli._repo import repo_arg_or_cwd

    repo_root = repo_arg_or_cwd(repo)
    db_path = _resolve_db_path(db, repo_root)

    typer.echo("harness doctor")
    typer.echo("==============")

    checks: list[tuple[str, tuple[str, str]]] = [
        ("auth", check_codex_auth() if engine == "codex" else check_auth()),
        ("git", check_git()),
        ("git-version", check_git_version()),
        ("db", check_db(db_path)),
        ("reviewer", check_reviewer(engine=engine)),
        ("gh", check_gh()),
        ("verify", check_verify_config(repo_root)),
        ("cli", check_cli()),
        ("wrapper", check_wrapper()),
    ]

    any_fail = False
    for name, (status, msg) in checks:
        typer.echo(f"[{status}] {name:<12} {msg}")
        if status == "FAIL":
            any_fail = True

    if any_fail:
        raise typer.Exit(code=1)
