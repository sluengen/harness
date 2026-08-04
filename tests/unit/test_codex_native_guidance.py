"""Codex-native guidance derivation is documented and current."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
CODEX_AGENT_DIR = REPO_ROOT / ".codex" / "agents"
BUILD_COMMAND = REPO_ROOT / "commands" / "build.md"
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"


def _text(path: Path) -> str:
    return path.read_text()


def test_bootstrap_derives_codex_native_artifacts() -> None:
    """Bootstrap must install Codex-native config, not only Claude mirrors."""

    text = _text(BOOTSTRAP)

    assert ".codex/agents/*.toml" in text
    assert "${CODEX_HOME:-$HOME/.codex}/skills" in text
    assert "Codex-native" in text
    assert "agents/*.md" in text
    assert "skills/<id>/SKILL.md" in text


def test_update_guidance_rederives_codex_native_artifacts() -> None:
    """Update guidance must keep Codex's generated surface fresh."""

    text = _text(UPDATE_GUIDANCE)

    assert ".codex/agents/*.toml" in text
    assert "${CODEX_HOME:-$HOME/.codex}/skills" in text
    assert "Codex-native" in text
    assert "stale Codex agent config" in text


def test_codex_agent_tomls_reference_current_skill_paths() -> None:
    """The checked-in Codex roles must not point at retired flat skill names."""

    retired_fragments = [
        "skills/test-driven-development.md",
        "skills/code-review.md",
        "skills/scope-discipline.md",
        "skills/verification-before-completion.md",
    ]

    for path in CODEX_AGENT_DIR.glob("*.toml"):
        text = _text(path)
        for retired in retired_fragments:
            assert retired not in text, f"{path} still references {retired}"

    python_dev = _text(CODEX_AGENT_DIR / "python-dev.toml")
    reviewer = _text(CODEX_AGENT_DIR / "reviewer.toml")

    assert "skills/test-driven-development/SKILL.md" in python_dev
    assert "skills/code-quality/SKILL.md" in python_dev
    assert "skills/review-discipline/SKILL.md" in reviewer


def test_agent_led_commands_use_tool_neutral_entry_doc() -> None:
    """Reusable command docs should not hard-code Claude's entry file."""

    build = _text(BUILD_COMMAND)
    harness = _text(HARNESS_COMMAND)

    assert "entry process doc" in build
    assert "PROJECT_PROCESS_DOC" in build
    assert "host sub-agent mechanism" in build
    assert "CLAUDE_MD" not in build

    assert "orchestrating agent session" in harness
    assert "entry process doc" in harness


def test_repo_context_describes_agent_neutral_orchestration() -> None:
    """CONTEXT.md should not make Claude the only orchestrating host."""

    context = _text(CONTEXT)

    assert "orchestrating agent session" in context
    assert "single Claude session" not in context
    assert "orchestrating Claude session" not in context
