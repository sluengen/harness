"""The Codex compile step, run against fixtures (v5 chunk 3, ADR 0017 D2).

``scripts/generate_codex_artifacts.py`` compiles the secondary Codex surface
from the canonical guidance: ``AGENTS.md`` at the repo root (the spine plus a
generated index of the skills and commands, because Codex reads ``AGENTS.md``
natively but discovers none of the leaves on its own) and ``.codex/`` (agent
definitions as TOML, skills as symlinks, commands as skill-typed adapters —
Codex discovers repo-local skills, not repo-local slash commands).

Admission (ADR 0017 D5): class (a) — the generator is executable code, so its
behaviour is proven by *running* it against fixture repos built in ``tmp_path``,
never by reading its text. The one committed-tree concern — a stale committed
``AGENTS.md`` or ``.codex/`` — is caught by the gate itself:
``scripts/verify.sh`` runs the generator's ``--check`` as a stage, and the
wiring of that stage is pinned here the same way the coverage floor's wiring is
pinned in ``tests/unit/test_verify_coverage_gate.py``.

Every test calls :func:`main` in-process (``scripts/`` is not a package, so the
module is loaded from its file path), which keeps the generator inside the
coverage population the gate measures.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "generate_codex_artifacts.py"
VERIFY = REPO_ROOT / "scripts" / "verify.sh"

#: The spine text every fixture writes — distinctive enough that finding it in
#: the compiled ``AGENTS.md`` is evidence of the spine, not of boilerplate.
_SPINE_TEXT = "# How work happens here\n\nThe fixture spine body: laws, contract, config.\n"


def _module():
    """Import the standalone script as a module (``scripts/`` is not a package).

    Registered in ``sys.modules`` before execution: the script defines
    dataclasses under ``from __future__ import annotations``, and the dataclass
    machinery resolves the defining module through ``sys.modules``.
    """
    spec = importlib.util.spec_from_file_location("generate_codex_artifacts", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gca = _module()


def _fixture_repo(root: Path) -> None:
    """A minimal canonical surface: a spine, one skill, two commands, one agent.

    The second command reproduces the real repo's ``assess.md`` shape — a bold
    preamble paragraph *before* the ``# /name — description`` heading — so the
    index parser is exercised on both heading positions the tree actually has.
    """
    (root / "CLAUDE.md").write_text(_SPINE_TEXT, encoding="utf-8")

    skill = root / "skills" / "alpha"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Use when testing the compile step.\n---\n# Alpha\n",
        encoding="utf-8",
    )

    commands = root / "commands"
    commands.mkdir()
    (commands / "go.md").write_text(
        "# /go — run the fixture workflow\n\nBody of the command.\n", encoding="utf-8"
    )
    (commands / "later.md").write_text(
        "**A preamble paragraph before the heading.**\n"
        "# /later — defer the fixture workflow\n\nBody.\n",
        encoding="utf-8",
    )

    agents = root / "agents"
    agents.mkdir()
    (agents / "dev.md").write_text(
        "---\nname: dev\ndescription: Fixture implementation agent.\n"
        "tools: [Read, Bash]\n---\n\n# Developer\n\nBuild things.\n",
        encoding="utf-8",
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_repo(root)
    return root


def _generate(root: Path) -> int:
    return int(gca.main(["--root", str(root)]))


def _check(root: Path) -> int:
    return int(gca.main(["--root", str(root), "--check"]))


# --- Generation ---------------------------------------------------------------


def test_generation_compiles_agents_md_from_the_spine_and_the_leaves(repo: Path) -> None:
    """AC: ``AGENTS.md`` carries the spine verbatim plus an index a Codex
    session can follow to every command and skill file."""
    assert _generate(repo) == 0

    agents_md = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert _SPINE_TEXT.strip() in agents_md, "the spine content must appear verbatim"
    assert "generate_codex_artifacts.py" in agents_md.splitlines()[0], (
        "the first line must say the file is generated and by what"
    )
    # Commands: name, description, and the path the entry points at.
    assert "`/go`" in agents_md and "run the fixture workflow" in agents_md
    assert "`commands/go.md`" in agents_md
    assert "`/later`" in agents_md and "defer the fixture workflow" in agents_md, (
        "a command whose heading follows a preamble paragraph must still be indexed"
    )
    # Skills: name, frontmatter description, path.
    assert "alpha" in agents_md and "Use when testing the compile step." in agents_md
    assert "`skills/alpha/SKILL.md`" in agents_md


def test_generation_ports_agents_commands_and_skills_into_codex(repo: Path) -> None:
    """AC: ``.codex/`` holds the agent TOMLs, skill symlinks, and skill-typed
    command adapters — the shapes Codex discovers."""
    assert _generate(repo) == 0

    toml = (repo / ".codex" / "agents" / "dev.toml").read_text(encoding="utf-8")
    assert 'name = "dev"' in toml
    assert 'description = "Fixture implementation agent."' in toml
    assert "developer_instructions = '''" in toml and "Build things." in toml

    link = repo / ".codex" / "skills" / "alpha"
    assert link.is_symlink(), "each canonical skill is exposed to Codex as a symlink"
    assert (link / "SKILL.md").read_text(encoding="utf-8").startswith("---\nname: alpha")

    adapter = (repo / ".codex" / "skills" / "command-go" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: command-go" in adapter
    assert "commands/go.md" in adapter, "the adapter must point back at the canonical command"


def test_regeneration_prunes_artifacts_whose_sources_are_gone(repo: Path) -> None:
    """A retired agent, skill, or command must not leave its port behind."""
    assert _generate(repo) == 0
    (repo / "agents" / "dev.md").unlink()
    (repo / "commands" / "go.md").unlink()
    skill_md = repo / "skills" / "alpha" / "SKILL.md"
    skill_md.unlink()
    skill_md.parent.rmdir()

    assert _generate(repo) == 0
    assert not (repo / ".codex" / "agents" / "dev.toml").exists()
    assert not (repo / ".codex" / "skills" / "command-go").exists()
    assert not (repo / ".codex" / "skills" / "alpha").is_symlink()


# --- The drift direction (--check) --------------------------------------------


def test_check_is_green_immediately_after_generation(repo: Path) -> None:
    assert _generate(repo) == 0
    assert _check(repo) == 0


def test_check_flags_a_stale_agents_md(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC: a committed ``AGENTS.md`` that no longer matches a regeneration fails
    the check and is named — this is what lets the gate catch a stale artifact."""
    assert _generate(repo) == 0
    agents_md = repo / "AGENTS.md"
    agents_md.write_text(agents_md.read_text(encoding="utf-8") + "\nhand edit\n", "utf-8")

    assert _check(repo) == 1
    assert "AGENTS.md" in capsys.readouterr().err


def test_check_flags_a_missing_or_stale_codex_artifact(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _generate(repo) == 0
    (repo / ".codex" / "agents" / "dev.toml").write_text("tampered\n", encoding="utf-8")
    stale = repo / ".codex" / "skills" / "command-old"
    stale.mkdir()
    (stale / "SKILL.md").write_text("orphaned adapter\n", encoding="utf-8")

    assert _check(repo) == 1
    err = capsys.readouterr().err
    assert "dev.toml" in err
    assert "command-old" in err

    # And a regeneration repairs both directions.
    assert _generate(repo) == 0
    assert _check(repo) == 0
    assert not stale.exists()


def test_check_never_writes(repo: Path) -> None:
    """``--check`` on an ungenerated tree reports rather than generating."""
    assert _check(repo) == 1
    assert not (repo / "AGENTS.md").exists()
    assert not (repo / ".codex").exists()


# --- Gate wiring --------------------------------------------------------------


def test_the_gate_runs_the_codex_drift_check() -> None:
    """``scripts/verify.sh`` carries the ``--check`` stage, so a stale committed
    ``AGENTS.md`` / ``.codex/`` is a red gate rather than silent drift — the
    same wiring pin the coverage floor and the design-token guard carry."""
    stages = [
        line.strip()
        for line in VERIFY.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("#")
        and "generate_codex_artifacts.py" in line
    ]
    assert len(stages) == 1, (
        f"expected exactly one codex drift stage in scripts/verify.sh; found {stages}"
    )
    assert "--check" in stages[0], (
        f"the gate must run the generator in --check mode, not regenerate: {stages[0]}"
    )
