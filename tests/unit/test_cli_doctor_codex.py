"""Codex-specific readiness checks for ``harness doctor``."""

from __future__ import annotations

import subprocess

from harness.cli.doctor import EngineProbe, check_codex_auth, check_reviewer


def test_check_codex_auth_passes_when_login_status_succeeds() -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd, 0, stdout="Logged in using ChatGPT\n", stderr=""
        )

    status, msg = check_codex_auth(run=fake_run)

    assert status == "PASS"
    assert calls == [["codex", "login", "status"]]
    assert "codex" in msg.lower()


def test_check_codex_auth_fails_when_login_status_fails() -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Not logged in")

    status, msg = check_codex_auth(run=fake_run)

    assert status == "FAIL"
    assert "login" in msg.lower()


def test_check_reviewer_codex_mode_passes_without_claude() -> None:
    status, msg = check_reviewer(
        engine="codex",
        claude_probe=EngineProbe("absent", None),
        codex_probe=EngineProbe("ok", "/usr/local/bin/codex"),
    )

    assert status == "PASS"
    assert "codex" in msg.lower()
    assert "claude" not in msg.lower()


def test_check_reviewer_codex_mode_fails_without_codex() -> None:
    status, msg = check_reviewer(
        engine="codex",
        claude_probe=EngineProbe("ok", "/usr/local/bin/claude"),
        codex_probe=EngineProbe("absent", None),
    )

    assert status == "FAIL"
    assert "codex" in msg.lower()
