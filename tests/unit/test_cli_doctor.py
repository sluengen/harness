"""Tests for harness doctor command — system health checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app

runner = CliRunner()


@pytest.fixture
def engines_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin both review engines as *live* — on PATH and their ``--version`` probe
    runs — so a CLI-level doctor test states a fact about ``doctor`` rather than
    about the machine running it (CAL-1110).

    ``check_reviewer`` now runs a real liveness probe per engine (CAL-1083):
    ``_probe_engine`` resolves the binary with ``shutil.which`` **and** shells
    out to ``<binary> --version``. Pinning ``shutil.which`` alone is no longer
    enough — the probe would still exec a binary the CI host lacks and report it
    as ``cannot_run``. So patch the probe itself to report both engines live; the
    decision logic that maps probe outcomes to PASS/WARN/FAIL is exercised
    directly by the unit tests below. Before this, a CLI-level "doctor exits 0"
    test *assumed* its own precondition instead of establishing it, and only
    failed once CI finally ran (release PR #161, the first CI run in 670 commits).
    """
    from harness.cli import doctor

    def fake_probe(binary: str, *args: object, **kwargs: object) -> doctor.EngineProbe:
        return doctor.EngineProbe("ok", f"/usr/local/bin/{binary}")

    monkeypatch.setattr(doctor, "_probe_engine", fake_probe)


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


# ---------------------------------------------------------------------------
# Engine liveness probe (CAL-1083) — a binary on PATH is not proof it can run
# ---------------------------------------------------------------------------


def test_probe_engine_absent_when_not_on_path() -> None:
    from harness.cli.doctor import EngineProbe, _probe_engine

    probe = _probe_engine("claude", which=lambda _cmd: None)
    assert probe == EngineProbe("absent", None)


def test_probe_engine_ok_when_version_exits_zero() -> None:
    import subprocess

    from harness.cli.doctor import _probe_engine

    def fake_run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="1.2.3\n", stderr="")

    probe = _probe_engine(
        "claude", which=lambda _cmd: "/usr/local/bin/claude", run=fake_run
    )
    assert probe.outcome == "ok"
    assert probe.path == "/usr/local/bin/claude"


def test_probe_engine_cannot_run_when_version_exits_nonzero() -> None:
    import subprocess

    from harness.cli.doctor import _probe_engine

    # On PATH but the probe exits non-zero: "installed but cannot execute here",
    # not "not installed" — the distinction this check exists to draw.
    def fake_run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")

    probe = _probe_engine(
        "codex", which=lambda _cmd: "/usr/local/bin/codex", run=fake_run
    )
    assert probe.outcome == "cannot_run"
    assert probe.path == "/usr/local/bin/codex"


def test_probe_engine_cannot_run_when_exec_raises() -> None:
    from harness.cli.doctor import _probe_engine

    # A binary that cannot even be launched (OSError) is also "cannot execute
    # here", not absent — it was found on PATH.
    def fake_run(*_a: object, **_k: object) -> object:
        raise OSError("cannot exec")

    probe = _probe_engine(
        "codex", which=lambda _cmd: "/usr/local/bin/codex", run=fake_run
    )
    assert probe.outcome == "cannot_run"


# ---------------------------------------------------------------------------
# check_reviewer maps probe outcomes to PASS/WARN/FAIL (CAL-1083)
# ---------------------------------------------------------------------------


def test_check_reviewer_passes_when_both_engines_live() -> None:
    from harness.cli.doctor import EngineProbe, check_reviewer

    # AC-2: in a healthy environment both engine probes ran → PASS.
    status, msg = check_reviewer(
        claude_probe=EngineProbe("ok", "/usr/local/bin/claude"),
        codex_probe=EngineProbe("ok", "/usr/local/bin/codex"),
    )
    assert status == "PASS"
    assert "claude" in msg.lower()
    assert "codex" in msg.lower()


def test_check_reviewer_fails_when_claude_absent() -> None:
    from harness.cli.doctor import EngineProbe, check_reviewer

    # claude has been the default review engine since CAL-701 (review.py); a host
    # missing it fails `harness review` at runtime, so doctor must FAIL — not the
    # old WARN, which let a broken host pass.
    status, msg = check_reviewer(
        claude_probe=EngineProbe("absent", None),
        codex_probe=EngineProbe("ok", "/usr/local/bin/codex"),
    )
    assert status == "FAIL"
    assert "claude" in msg.lower()


def test_check_reviewer_fails_when_claude_present_but_cannot_run() -> None:
    from harness.cli.doctor import EngineProbe, check_reviewer

    # AC-1 (claude variant): a binary on PATH whose liveness probe cannot run is
    # "installed but cannot execute" — a FAIL naming the wall, distinct from a
    # clean "not installed". A PATH-only check would have let this host pass.
    status, msg = check_reviewer(
        claude_probe=EngineProbe("cannot_run", "/usr/local/bin/claude"),
        codex_probe=EngineProbe("ok", "/usr/local/bin/codex"),
    )
    assert status == "FAIL"
    assert "claude" in msg.lower()
    assert "cannot" in msg.lower() or "could not" in msg.lower()


def test_check_reviewer_warns_when_codex_absent() -> None:
    from harness.cli.doctor import EngineProbe, check_reviewer

    # codex is the opt-in cross-model second opinion (`--engine codex`); simply
    # not being installed is not fatal because the default claude review still
    # works, so an absent codex is a WARN, not a FAIL.
    status, msg = check_reviewer(
        claude_probe=EngineProbe("ok", "/usr/local/bin/claude"),
        codex_probe=EngineProbe("absent", None),
    )
    assert status == "WARN"
    assert "codex" in msg.lower()


def test_check_reviewer_fails_when_codex_present_but_cannot_run_cites_adr_0002() -> None:
    from harness.cli.doctor import EngineProbe, check_reviewer

    # AC-1 (codex variant): codex on PATH but unable to run is "installed but
    # cannot execute" — a FAIL whose reason names the wall and cites ADR 0002
    # (the unprivileged container cannot open the user namespace codex's bwrap
    # sandbox needs; a real `--engine codex` review is host-only). This is
    # distinct from codex simply being absent (the WARN above): a present-but-
    # broken engine is a misconfiguration, an absent optional engine is a choice.
    status, msg = check_reviewer(
        claude_probe=EngineProbe("ok", "/usr/local/bin/claude"),
        codex_probe=EngineProbe("cannot_run", "/usr/local/bin/codex"),
    )
    assert status == "FAIL"
    assert "codex" in msg.lower()
    assert "0002" in msg


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
# Verify-gate config check (CAL-1083) — an unenforced gate should be visible
# ---------------------------------------------------------------------------


def test_check_verify_config_passes_when_configured(tmp_path: Path) -> None:
    from harness.cli.doctor import check_verify_config

    (tmp_path / "CONTEXT.md").write_text('verify:  "bash scripts/verify.sh"\n')
    status, msg = check_verify_config(repo_root=tmp_path)
    assert status == "PASS"
    assert "bash scripts/verify.sh" in msg


def test_check_verify_config_warns_when_absent(tmp_path: Path) -> None:
    # AC-3: a CONTEXT.md with no `verify:` produces a WARN naming the evidence-
    # model consequence (review records `not_configured`; a `pass` for this repo
    # carries no test evidence), NOT a FAIL — a repo may legitimately define no
    # gate, and doctor must not block it.
    from harness.cli.doctor import check_verify_config

    (tmp_path / "CONTEXT.md").write_text("repo:\n  name: demo\n")
    status, msg = check_verify_config(repo_root=tmp_path)
    assert status == "WARN"
    assert "not_configured" in msg
    lower = msg.lower()
    assert "no test evidence" in lower or "unenforced" in lower


def test_check_verify_config_warns_when_no_context_md(tmp_path: Path) -> None:
    # No CONTEXT.md at all resolves to "no gate defined" — a WARN, the same as an
    # empty `verify:` (load_gate_command returns None for both).
    from harness.cli.doctor import check_verify_config

    status, msg = check_verify_config(repo_root=tmp_path)
    assert status == "WARN"


# ---------------------------------------------------------------------------
# check_wrapper — the on-PATH wrapper must be the versioned source (CAL-1149)
#
# ``doctor`` runs in-container, where ``~/bin/harness`` is not mounted, so it
# cannot read the on-PATH wrapper itself. The wrapper does the comparison
# host-side (the one place both it and its versioned source are readable) and
# forwards a verdict as ``HARNESS_WRAPPER_STATUS``; ``check_wrapper`` maps it.
# A wrapper predating this ticket does not set the var — doctor then reads its
# own container-presence to distinguish that stale wrapper (in-container → FAIL)
# from a native run with no wrapper at all (not in-container → PASS). That split
# is what lets AC-3 tell "drifted copy" from "no wrapper on PATH".
# ---------------------------------------------------------------------------


def test_check_wrapper_passes_on_symlinked_install() -> None:
    from harness.cli.doctor import check_wrapper

    status, msg = check_wrapper(env={"HARNESS_WRAPPER_STATUS": "symlink"})
    assert status == "PASS"
    assert "symlink" in msg.lower()


def test_check_wrapper_fails_on_drifted_copy() -> None:
    from harness.cli.doctor import check_wrapper

    # A copy whose content has already fallen behind the versioned wrapper —
    # the exact rot this ticket exists to surface. FAIL, and name the remedy.
    status, msg = check_wrapper(env={"HARNESS_WRAPPER_STATUS": "drifted"})
    assert status == "FAIL"
    lower = msg.lower()
    assert "drift" in lower
    assert "symlink" in lower  # names the fix (AC-2)


def test_check_wrapper_fails_on_detached_copy() -> None:
    from harness.cli.doctor import check_wrapper

    # A copy outside any checkout (the real ~/bin/harness deployment before the
    # relink): no source tree to track, guaranteed to rot silently → FAIL.
    status, msg = check_wrapper(env={"HARNESS_WRAPPER_STATUS": "detached"})
    assert status == "FAIL"
    lower = msg.lower()
    assert "detached" in lower
    assert "symlink" in lower


def test_check_wrapper_warns_on_identical_copy() -> None:
    from harness.cli.doctor import check_wrapper

    # A copy byte-identical today but not a symlink: not yet drifted, but it will
    # the moment the repo moves. A WARN, not a hard FAIL.
    status, msg = check_wrapper(env={"HARNESS_WRAPPER_STATUS": "copy"})
    assert status == "WARN"
    assert "copy" in msg.lower()


def test_check_wrapper_fails_on_old_wrapper_in_container() -> None:
    from harness.cli.doctor import check_wrapper

    # No HARNESS_WRAPPER_STATUS but running in-container: a wrapper mediated this
    # run (only the wrapper starts the container) yet did not self-report, so it
    # predates this check — a stale copy. FAIL and point at the re-symlink.
    status, msg = check_wrapper(env={}, in_container=True)
    assert status == "FAIL"
    assert "symlink" in msg.lower()


def test_check_wrapper_passes_when_no_wrapper_native_run() -> None:
    from harness.cli.doctor import check_wrapper

    # No HARNESS_WRAPPER_STATUS and NOT in a container: doctor was run natively,
    # with no Docker wrapper on PATH — there is no wrapper to drift. This is the
    # third AC-3 state ("a wrapper not on PATH at all"), distinct from a drifted
    # copy: a PASS, not a FAIL.
    status, msg = check_wrapper(env={}, in_container=False)
    assert status == "PASS"
    lower = msg.lower()
    assert "native" in lower or "no wrapper" in lower


# ---------------------------------------------------------------------------
# CLI integration — harness doctor command
# ---------------------------------------------------------------------------


def test_doctor_command_registered_in_app() -> None:
    """doctor must appear in the CLI help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout
    assert "doctor" in result.stdout


def test_doctor_command_exits_zero_on_pass_or_warn(
    tmp_path: Path, engines_live: None
) -> None:
    """With no failures, doctor exits 0.

    ``engines_live`` establishes the no-failure precondition this asserts;
    without it the test only holds on a host that happens to have both engines
    installed *and* runnable (CAL-1110, CAL-1083).
    """
    db = tmp_path / ".harness" / "harness.db"
    result = runner.invoke(
        app,
        ["doctor", "--db", str(db)],
        env={"ANTHROPIC_API_KEY": "sk-test"},
        catch_exceptions=False,
    )
    # Exit 0 when all checks pass or warn.
    assert result.exit_code == 0, result.stdout


def test_doctor_command_exits_one_on_failure(
    tmp_path: Path, engines_live: None
) -> None:
    """A FAILing check must propagate as a non-zero (exit 1) CLI status.

    The pass/warn cases pin exit 0; without this, the FAIL → typer.Exit(code=1)
    path is unasserted at the CLI level. Force a deterministic auth FAIL: remove
    ANTHROPIC_API_KEY and supply an OAuth token whose expiry is in the past
    (CAL-941). That branch returns FAIL before the ~/.claude fallback, so it
    fails regardless of the host's home directory.

    ``engines_live`` makes auth the *only* FAIL (CAL-1110). Without it, a host
    with no ``claude`` produces a second, unrelated FAIL — and this test would
    then pass on the reviewer's failure even if the auth branch it exists to pin
    had stopped failing.
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
    # Pin that exit 1 came from a real doctor FAIL line, not a stray exception —
    # and that the FAIL is the auth one, not some other check failing by accident.
    fail_lines = [ln for ln in result.stdout.splitlines() if "[FAIL]" in ln]
    assert len(fail_lines) == 1, (
        f"expected auth to be the only FAIL, got: {fail_lines}"
    )
    assert "auth" in fail_lines[0]


def test_doctor_command_output_contains_check_labels(
    tmp_path: Path, engines_live: None
) -> None:
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
    # The verify-gate config check (CAL-1083) must be wired in too.
    assert "verify" in out


def test_doctor_command_fails_when_engine_installed_but_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1 end-to-end: an engine on PATH whose liveness probe cannot run makes
    the aggregated ``doctor`` command FAIL (exit 1) with a reason naming the wall
    — here the codex/container case, whose reason cites ADR 0002.
    """
    from harness.cli import doctor

    def fake_probe(binary: str, *_a: object, **_k: object) -> doctor.EngineProbe:
        if binary == "codex":
            return doctor.EngineProbe("cannot_run", "/usr/local/bin/codex")
        return doctor.EngineProbe("ok", "/usr/local/bin/claude")

    monkeypatch.setattr(doctor, "_probe_engine", fake_probe)
    db = tmp_path / ".harness" / "harness.db"
    result = runner.invoke(
        app,
        ["doctor", "--db", str(db)],
        env={"ANTHROPIC_API_KEY": "sk-test"},
    )
    assert result.exit_code == 1, result.stdout
    reviewer_lines = [ln for ln in result.stdout.splitlines() if "reviewer" in ln]
    assert reviewer_lines and "[FAIL]" in reviewer_lines[0], result.stdout
    assert "0002" in result.stdout


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
