"""Codex-native guidance derivation is documented and current."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

from tests.unit._prose import REPO_ROOT

BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
CODEX_AGENT_DIR = REPO_ROOT / ".codex" / "agents"
CODEX_SKILLS = REPO_ROOT / ".codex" / "skills"
CODEX_GENERATOR = REPO_ROOT / "templates" / "generate_codex_artifacts.py"
BUILD_COMMAND = REPO_ROOT / "commands" / "build.md"
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
    promote_skill = _text(CODEX_SKILLS / "command-promote" / "SKILL.md")

    assert "name: command-build" in build_skill
    assert "`/build`" in build_skill
    assert "commands/build.md" in build_skill
    assert "read and follow the command file completely before acting" in build_skill

    assert "name: command-promote" in promote_skill
    assert "`/promote`" in promote_skill
    assert "commands/promote.md" in promote_skill


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


def test_codex_generator_prunes_a_symlink_whose_skill_is_gone(tmp_path: Path) -> None:
    """A retired skill's generated symlink is removed, and `--check` reports it.

    Retiring a skill (`guidance-coherence`, #435) deletes `skills/<id>/` but the
    generated `.codex/skills/<id>` symlink pointing into it is not one of the
    files the generator writes, so nothing rewrites it. It stayed behind as a
    dangling link that resolved to a directory that no longer existed — and
    `--check` was clean, because it only inspected the links it *expected*, never
    the ones it did not. The command-skill half already pruned its strays; the
    plain-skill half did not.
    """
    repo = tmp_path / "consumer"
    (repo / "agents").mkdir(parents=True)
    (repo / "commands").mkdir()
    (repo / "skills" / "code-quality").mkdir(parents=True)
    (repo / "templates").mkdir()
    (repo / ".codex" / "skills").mkdir(parents=True)

    shutil.copy2(CODEX_GENERATOR, repo / "templates" / "generate_codex_artifacts.py")
    (repo / "skills" / "code-quality" / "SKILL.md").write_text(
        "---\nname: code-quality\ndescription: Use while implementing.\n---\n# Code Quality\n"
    )
    retired = repo / ".codex" / "skills" / "guidance-coherence"
    retired.symlink_to(Path("../../skills/guidance-coherence"))
    assert retired.is_symlink() and not retired.exists(), "fixture must be a dangling link"

    stale_check = subprocess.run(
        ["python3", "templates/generate_codex_artifacts.py", "--check"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert stale_check.returncode == 1, stale_check.stdout + stale_check.stderr
    assert "guidance-coherence" in stale_check.stderr, stale_check.stderr

    result = subprocess.run(
        ["python3", "templates/generate_codex_artifacts.py"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not retired.is_symlink(), "the stale skill symlink must be pruned"
    assert (repo / ".codex" / "skills" / "code-quality").is_symlink(), (
        "pruning must not take the live skills with it"
    )


def test_agent_led_commands_use_tool_neutral_entry_doc() -> None:
    """Reusable command docs should not hard-code Claude's entry file."""

    build = _text(BUILD_COMMAND)

    assert "entry process doc" in build
    assert "PROJECT_PROCESS_DOC" in build
    assert "host sub-agent mechanism" in build
    assert "CLAUDE_MD" not in build


def test_repo_context_describes_agent_neutral_orchestration() -> None:
    """CONTEXT.md should not make Claude the only orchestrating host.

    The two negative assertions are the guard. The positive one is the floor
    under them: on a file that said nothing about who drives the work, both
    negatives would be trivially true. Its anchor was ``orchestrating agent
    session`` — the phrase describing a session calling the retired runtime's
    verbs — and #435 deleted the runtime, so the floor moves to the vocabulary
    the file now uses for the same question. Host-neutral either way, which is
    the whole point: the anchor must never be a product name.
    """

    context = _text(CONTEXT)

    assert "agent-led" in context
    assert "single Claude session" not in context
    assert "orchestrating Claude session" not in context
