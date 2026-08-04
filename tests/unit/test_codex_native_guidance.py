"""Codex-native guidance derivation is documented and current."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
CODEX_AGENT_DIR = REPO_ROOT / ".codex" / "agents"
CODEX_SKILLS = REPO_ROOT / ".codex" / "skills"
CODEX_COMMANDS = REPO_ROOT / ".codex" / "commands"
CODEX_GENERATOR = REPO_ROOT / "templates" / "generate_codex_artifacts.py"
BUILD_COMMAND = REPO_ROOT / "commands" / "build.md"
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"


def _text(path: Path) -> str:
    return path.read_text()


def test_bootstrap_derives_codex_native_artifacts() -> None:
    """Bootstrap must install Codex-native config, not only Claude mirrors."""

    text = _text(BOOTSTRAP)

    assert ".codex/agents/*.toml" in text
    assert ".codex/skills -> ../skills" in text
    assert ".codex/commands -> ../commands" in text
    assert "Codex-native" in text
    assert "agents/*.md" in text
    assert "skills/<id>/SKILL.md" in text


def test_update_guidance_rederives_codex_native_artifacts() -> None:
    """Update guidance must keep Codex's generated surface fresh."""

    text = _text(UPDATE_GUIDANCE)

    assert ".codex/agents/*.toml" in text
    assert "skills symlink" in text
    assert "commands symlink" in text
    assert "Codex-native" in text
    assert "stale Codex agent config" in text


def test_codex_local_discovery_symlinks_match_claude_shape() -> None:
    """Codex should see the same repo-local skills and commands Claude sees."""

    assert CODEX_SKILLS.is_symlink()
    assert CODEX_SKILLS.readlink() == Path("../skills")
    assert (CODEX_SKILLS / "code-quality" / "SKILL.md").exists()

    assert CODEX_COMMANDS.is_symlink()
    assert CODEX_COMMANDS.readlink() == Path("../commands")
    assert (CODEX_COMMANDS / "harness.md").exists()


def test_codex_agent_tomls_are_generated_for_all_repo_agents() -> None:
    """Every canonical repo agent gets a Codex TOML role."""

    retired_fragments = [
        "skills/test-driven-development.md",
        "skills/code-review.md",
        "skills/scope-discipline.md",
        "skills/verification-before-completion.md",
    ]
    expected_agents = {"architect", "dev", "researcher", "reviewer", "steward"}
    generated = {path.stem for path in CODEX_AGENT_DIR.glob("*.toml")}

    assert generated == expected_agents
    assert not (CODEX_AGENT_DIR / "python-dev.toml").exists()

    for path in CODEX_AGENT_DIR.glob("*.toml"):
        text = _text(path)
        data = tomllib.loads(text)
        assert data["name"] == path.stem
        assert data["developer_instructions"].startswith("# ")
        for retired in retired_fragments:
            assert retired not in text, f"{path} still references {retired}"

    dev = _text(CODEX_AGENT_DIR / "dev.toml")
    reviewer = _text(CODEX_AGENT_DIR / "reviewer.toml")

    assert "skills/test-driven-development/SKILL.md" in dev
    assert "skills/code-quality/SKILL.md" in dev
    assert "skills/review-discipline/SKILL.md" in reviewer


def test_codex_generator_is_idempotent() -> None:
    """The checked-in Codex artifacts are generated, not hand-maintained."""

    result = subprocess.run(
        ["python3", str(CODEX_GENERATOR), "--check"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


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
