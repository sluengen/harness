"""Codex-native guidance derivation is documented and current."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
CODEX_AGENT_DIR = REPO_ROOT / ".codex" / "agents"
CODEX_SKILLS = REPO_ROOT / ".codex" / "skills"
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
    assert ".codex/skills/<id> -> ../../skills/<id>" in text
    assert ".codex/skills/command-<id>/SKILL.md" in text
    assert "Codex-native" in text
    assert "agents/*.md" in text
    assert "skills/<id>/SKILL.md" in text
    assert "commands/*.md" in text


def test_update_guidance_rederives_codex_native_artifacts() -> None:
    """Update guidance must keep Codex's generated surface fresh."""

    text = _text(UPDATE_GUIDANCE)

    assert ".codex/agents/*.toml" in text
    assert "generated Codex command-skills" in text
    assert "skills directory" in text
    assert "Codex-native" in text
    assert "stale Codex agent config" in text


def test_codex_local_discovery_skills_include_repo_skills_and_commands() -> None:
    """Codex should see repo skills and command adapters through skills."""

    assert CODEX_SKILLS.is_dir()
    assert not CODEX_SKILLS.is_symlink()

    code_quality = CODEX_SKILLS / "code-quality"
    assert code_quality.is_symlink()
    assert code_quality.readlink() == Path("../../skills/code-quality")
    assert (code_quality / "SKILL.md").exists()

    command_files = sorted((REPO_ROOT / "commands").glob("*.md"))
    expected_command_skills = {f"command-{path.stem}" for path in command_files}
    generated_command_skills = {
        path.name for path in CODEX_SKILLS.glob("command-*") if path.is_dir()
    }

    assert generated_command_skills == expected_command_skills
    assert not (REPO_ROOT / ".codex" / "commands").exists()

    build_skill = _text(CODEX_SKILLS / "command-build" / "SKILL.md")
    harness_skill = _text(CODEX_SKILLS / "command-harness" / "SKILL.md")

    assert "name: command-build" in build_skill
    assert "`/build`" in build_skill
    assert "commands/build.md" in build_skill
    assert "read and follow the command file completely before acting" in build_skill

    assert "name: command-harness" in harness_skill
    assert "`/harness run`" in harness_skill
    assert "`/harness routine`" in harness_skill
    assert "commands/harness.md" in harness_skill


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


def test_codex_generator_migrates_old_symlink_surface(tmp_path: Path) -> None:
    """Initial bootstrap/update-guidance must replace the old Codex command shape."""

    repo = tmp_path / "consumer"
    (repo / "agents").mkdir(parents=True)
    (repo / "commands").mkdir()
    (repo / "skills" / "code-quality").mkdir(parents=True)
    (repo / "templates").mkdir()
    (repo / ".codex" / "agents").mkdir(parents=True)

    shutil.copy2(CODEX_GENERATOR, repo / "templates" / "generate_codex_artifacts.py")
    (repo / "agents" / "dev.md").write_text(
        "---\n"
        "name: dev\n"
        "description: Build changes\n"
        "---\n"
        "# Dev\n\n"
        "Use skills/code-quality/SKILL.md.\n"
    )
    (repo / "commands" / "build.md").write_text("# /build\n\nBuild the ticket.\n")
    (repo / "skills" / "code-quality" / "SKILL.md").write_text(
        "---\n"
        "name: code-quality\n"
        "description: Use while implementing.\n"
        "---\n"
        "# Code Quality\n"
    )
    (repo / ".codex" / "agents" / "stale.toml").write_text("name = \"stale\"\n")
    (repo / ".codex" / "skills").symlink_to(Path("../skills"))
    (repo / ".codex" / "commands").symlink_to(Path("../commands"))

    result = subprocess.run(
        ["python3", "templates/generate_codex_artifacts.py"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / ".codex" / "agents" / "dev.toml").exists()
    assert not (repo / ".codex" / "agents" / "stale.toml").exists()
    assert (repo / ".codex" / "skills").is_dir()
    assert not (repo / ".codex" / "skills").is_symlink()
    assert (repo / ".codex" / "skills" / "code-quality").readlink() == Path(
        "../../skills/code-quality"
    )
    assert (repo / ".codex" / "skills" / "command-build" / "SKILL.md").exists()
    assert not (repo / ".codex" / "commands").exists()

    check = subprocess.run(
        ["python3", "templates/generate_codex_artifacts.py", "--check"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )

    assert check.returncode == 0, check.stdout + check.stderr


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


def test_harness_command_defines_strict_native_codex_only_mode() -> None:
    """The agent-led loop must carry strict engine flags through every stage."""
    command = _text(HARNESS_COMMAND)

    assert "/harness run <ISSUE-ID> --codex-only" in command
    assert "harness doctor --engine codex" in command
    assert "harness design --run-id <run_id> --engine codex" in command
    assert "harness review --run-id <run_id> --engine codex --no-fallback" in command
    assert "native-only" in command.lower()
    assert "#314" in command
    assert "never invoke Claude" in command
