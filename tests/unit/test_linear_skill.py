"""CAL-714 — rename ``linear-sync`` → ``linear``; type-based state resolution;
no-embedded-GraphQL guard.

*Source:* ``assessments/2026-06-15-system-and-code.md`` — SYSTEM-2 /
SYSTEM-INSIGHT-2 (Medium). Linear workflow-state IDs are **per-team UUIDs** (not
portable across repos/trackers), yet the old ``linear-sync`` skill told
consumers to cache those UUIDs in ``CONTEXT.md`` — making setup mandatory and
the IDs brittle. Commands also re-derived their own GraphQL instead of
referencing the one skill that already holds the canonical recipes. This ticket
renames the skill to ``linear``, leads with **type-based runtime state
resolution**, demotes the CONTEXT-cached UUIDs to an override, and ratchets the
embedded GraphQL out of the installed command surface.

* **AC-1** — the skill is renamed and version-stamped: ``skills/linear/SKILL.md``
  exists (the old ``skills/linear-sync/`` path is gone), its frontmatter
  ``name`` is ``linear``, and its ``guidance:linear@<v>`` header version equals
  its ``registry.yaml`` version.
* **AC-2** — the skill documents type-based resolution as the **default** (the
  four stable ``type`` enums, disambiguating the two ``started`` states by name)
  and the CONTEXT-cached UUIDs as an **override** exception, not a requirement.
* **AC-3** — no *registered* command embeds raw Linear GraphQL
  (``api.linear.app``). ``commands/build.md`` is the single tracked exception
  that sibling **CAL-715** ("Thin /build … no embedded Linear GraphQL") empties;
  the offender set must not grow past it. The canonical recipes live in the
  ``linear`` skill.
* **AC-4** — no live-surface reference to ``linear-sync`` survives the rename
  (``CHANGELOG.md`` / ``assessments/`` legitimately keep the old id as history).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "registry.yaml"
LINEAR_SKILL = REPO_ROOT / "skills" / "linear" / "SKILL.md"
OLD_SKILL_DIR = REPO_ROOT / "skills" / "linear-sync"


# --- AC-1: rename + version parity -------------------------------------------


def test_skill_renamed_old_path_gone() -> None:
    assert LINEAR_SKILL.is_file(), (
        "skills/linear/SKILL.md must exist after the rename (AC-1)."
    )
    assert not OLD_SKILL_DIR.exists(), (
        "skills/linear-sync/ must be gone after the rename to skills/linear/ (AC-1)."
    )


def test_skill_name_and_header_match_registry() -> None:
    text = LINEAR_SKILL.read_text()
    assert re.search(r"^name:\s*linear\s*$", text, re.MULTILINE), (
        "skills/linear/SKILL.md frontmatter 'name:' must be 'linear' (AC-1)."
    )
    header = re.search(r"<!--\s*guidance:linear@(\d+\.\d+\.\d+)\s*-->", text)
    assert header, (
        "skills/linear/SKILL.md must carry a 'guidance:linear@x.y.z' header (AC-1)."
    )
    reg = re.search(
        r"skills/linear/SKILL\.md:\s*\{\s*id:\s*linear,\s*version:\s*(\d+\.\d+\.\d+)",
        REGISTRY.read_text(),
    )
    assert reg, "registry.yaml must list skills/linear/SKILL.md with id: linear (AC-1)."
    assert header.group(1) == reg.group(1), (
        f"header version {header.group(1)} != registry version {reg.group(1)} (AC-1)."
    )


# --- AC-2: type-based resolution is the default, CONTEXT is the override ------

#: The stable, cross-tracker workflow-state ``type`` enum (Linear's
#: ``WorkflowState.type``). Resolving by these — not by cached UUID — is what
#: makes the recipes portable across repos.
STABLE_TYPES = ("unstarted", "started", "completed", "canceled")


def test_type_based_resolution_documented() -> None:
    text = LINEAR_SKILL.read_text()
    for enum in STABLE_TYPES:
        assert enum in text, (
            f"skills/linear/SKILL.md must name the stable state type {enum!r} so a "
            "state can be resolved at runtime without a cached UUID (AC-2)."
        )
    assert "In Progress" in text and "In Review" in text, (
        "the skill must disambiguate the two 'started' states (In Progress / In "
        "Review) by name (AC-2)."
    )


def test_context_uuids_demoted_to_override() -> None:
    text = LINEAR_SKILL.read_text()
    assert "override" in text.lower(), (
        "the skill must frame CONTEXT-cached state UUIDs as an override/exception, "
        "not the default path (AC-2)."
    )
    assert "cache them in `CONTEXT.md`" not in text, (
        "the skill must not instruct consumers to cache state UUIDs in CONTEXT.md as "
        "the default — that is the brittle, per-team coupling this ticket removes (AC-2)."
    )


# --- AC-3: no registered command embeds raw Linear GraphQL --------------------

#: The single registered command still embedding Linear GraphQL. Sibling
#: CAL-714 *blocks* CAL-715 ("Thin /build … no embedded Linear GraphQL"), which
#: empties this set: when it lands, remove ``commands/build.md`` here and the
#: guard fully closes. ``commands/harness.md`` is the harness's own,
#: *repo-owned* (un-registered) verb-loop command and is not part of the
#: installed command surface this guard governs.
PENDING_GRAPHQL = {"commands/build.md"}


def _registered_commands() -> list[Path]:
    """The command files the registry installs into a consuming repo."""
    paths = re.findall(
        r"^\s*(commands/[\w./-]+\.md):", REGISTRY.read_text(), re.MULTILINE
    )
    return [REPO_ROOT / p for p in paths]


def test_no_registered_command_embeds_graphql() -> None:
    offenders = {
        c.relative_to(REPO_ROOT).as_posix()
        for c in _registered_commands()
        if "api.linear.app" in c.read_text()
    }
    extra = offenders - PENDING_GRAPHQL
    assert not extra, (
        f"registered command(s) embed raw Linear GraphQL: {sorted(extra)}. Reference "
        "the `linear` skill's canonical recipes instead of inlining api.linear.app (AC-3)."
    )
    stale = PENDING_GRAPHQL - offenders
    assert not stale, (
        f"{sorted(stale)} no longer embeds GraphQL — drop it from PENDING_GRAPHQL so "
        "the guard tightens to zero (AC-3)."
    )


def test_canonical_graphql_lives_in_linear_skill() -> None:
    assert "api.linear.app" in LINEAR_SKILL.read_text(), (
        "the `linear` skill must hold the canonical Linear GraphQL recipes — the one "
        "home every command references (AC-3)."
    )


# --- AC-4: no live-surface reference to the old skill id survives -------------

#: Live surface that must speak the new ``linear`` id. ``CHANGELOG.md`` and
#: ``assessments/`` are excluded: they are dated historical records where the
#: old ``linear-sync`` name is correct. ``tests/`` is excluded (this guard's own
#: docstring names the old id).
_LIVE_GLOBS = (
    "commands/*.md",
    "agents/**/*.md",
    "skills/**/*.md",
    "templates/*.md",
    "process/*.md",
)
_LIVE_FILES = (
    "registry.yaml",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "INSTALLER.md",
    "SPEC.md",
    "specs/architecture-principles.md",
)


def test_no_live_linear_sync_reference() -> None:
    offenders: set[str] = set()
    for glob in _LIVE_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if "linear-sync" in path.read_text():
                offenders.add(path.relative_to(REPO_ROOT).as_posix())
    for rel in _LIVE_FILES:
        path = REPO_ROOT / rel
        if path.is_file() and "linear-sync" in path.read_text():
            offenders.add(rel)
    assert not offenders, (
        f"live-surface file(s) still reference the old skill id 'linear-sync' after "
        f"the rename: {sorted(offenders)}. Update them to 'linear' (AC-4)."
    )
