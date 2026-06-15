"""Guard: ``/build`` is a single engine-arg command; ``/build-codex`` is retired (CAL-703).

``commands/build.md`` and ``commands/build-codex.md`` were ~95% identical — the only
real difference was the Review step (Claude inline vs ``codex exec``). A3 of the
pre-launch consolidation (``specs/proposals/pre-launch-consolidation.md``) collapses the
two into one ``commands/build.md`` whose review takes ``--engine codex`` (default Claude),
mirroring the engine-arg policy A1 set on the verb surface, and retires
``build-codex.md`` + its registry entry.

These guards pin the consolidated state so the split cannot regress and a re-import of
the retired file is caught by the verify gate:

* the second file is gone and unlisted (AC-1, AC-2);
* no dangling ``build-codex`` reference survives in the live distributed command/process
  surface (AC-3) — history (``CHANGELOG.md``), specs/proposals, and source comments about
  the long-retired ``build-codex.yaml`` workflow are out of scope and keep their records;
* the surviving ``build.md`` documents both engines and the agent-orchestrated
  Codex→Claude fallback (AC-1).

*Source:* CAL-703.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BUILD = REPO_ROOT / "commands" / "build.md"
BUILD_CODEX = REPO_ROOT / "commands" / "build-codex.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The live, installed command/process surface — the files a consumer repo pulls.
#: History (CHANGELOG), specs/proposals, source, and tests are deliberately excluded:
#: they legitimately record the retirement and the long-gone ``build-codex.yaml``.
_SURFACE = [
    *sorted((REPO_ROOT / "commands").glob("*.md")),
    REPO_ROOT / "process" / "harness.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "GEMINI.md",
    REGISTRY,
]


# --- AC-1 / AC-2: the second file is gone and unlisted ----------------------


def test_build_codex_file_removed() -> None:
    """``commands/build-codex.md`` no longer exists — it folded into ``build.md``."""
    assert not BUILD_CODEX.exists(), (
        "commands/build-codex.md must be removed — its review step folds into "
        "commands/build.md behind '--engine codex' (CAL-703)"
    )


def test_registry_does_not_list_build_codex() -> None:
    """The registry must not list ``build-codex.md`` (its entry is removed)."""
    text = REGISTRY.read_text()
    assert "build-codex" not in text, (
        "registry.yaml still references build-codex — remove its files: entry (CAL-703)"
    )


# --- AC-3: no dangling reference in the live distributed surface -------------


def test_no_build_codex_in_distributed_surface() -> None:
    """No live command/process-surface file mentions ``build-codex`` (AC-3)."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _SURFACE
        if p.exists() and "build-codex" in p.read_text()
    ]
    assert not offenders, (
        "the consolidated surface must carry no 'build-codex' reference; found in: "
        f"{offenders} (CAL-703 AC-3)"
    )


# --- AC-1: the surviving file documents both engines + the fallback ---------


def test_build_command_takes_engine_arg() -> None:
    """``build.md`` documents ``--engine codex`` with Claude as the default."""
    text = BUILD.read_text()
    assert "--engine codex" in text, (
        "build.md must document the '--engine codex' opt-in (CAL-703)"
    )
    assert re.search(r"default[^.\n]*[Cc]laude|[Cc]laude[^.\n]*default", text), (
        "build.md must state Claude is the default review engine (CAL-703)"
    )


def test_build_command_documents_codex_review_read_only_from_worktree() -> None:
    """The Codex engine path keeps the CAL-659 safety posture: read-only, in the worktree."""
    text = BUILD.read_text()
    assert "--dangerously-bypass-approvals-and-sandbox" not in text, (
        "build.md must not run the Codex reviewer unsandboxed — the diff/ticket are "
        "untrusted prompt content (CAL-659 carried into CAL-703)"
    )
    assert "--sandbox read-only" in text, (
        "build.md's Codex engine must run 'codex exec --sandbox read-only'"
    )
    codex_lines = [ln for ln in text.splitlines() if "codex exec" in ln]
    assert codex_lines, "build.md must invoke 'codex exec' for the Codex engine"
    for ln in codex_lines:
        assert 'cd "$worktree_path" &&' in ln, (
            "the 'codex exec' invocation must 'cd \"$worktree_path\"' first so Codex "
            f"reads the implementation under review, not the base checkout — got: {ln!r}"
        )


def test_build_command_documents_codex_to_claude_fallback() -> None:
    """``build.md`` documents the agent-orchestrated Codex→Claude fallback (AC-1)."""
    text = BUILD.read_text().lower()
    assert "fall" in text and "claude" in text, (
        "build.md must document the Codex→Claude fallback on an exhausted tier (CAL-703)"
    )
    assert "usage limit" in text or "exhausted" in text, (
        "build.md must name the exhausted-tier / usage-limit trigger for the fallback"
    )


# --- AC-2: version bumped consistently --------------------------------------


def test_build_version_bumped_to_1_3() -> None:
    """``build.md`` header is at least 1.3.0 (minor bump for the engine arg)."""
    m = re.search(r"guidance:build@(\d+)\.(\d+)\.(\d+)", BUILD.read_text())
    assert m, "build.md must carry a guidance:build@<version> header"
    major, minor, _ = (int(g) for g in m.groups())
    assert (major, minor) >= (1, 3), (
        f"build.md must be bumped to >= 1.3.0 for the added engine arg; got {m.group(0)}"
    )
