"""CAL-646 — the harness is the guidance SOURCE, not a consumer.

Breakdown item 1 of ``specs/proposals/merge-guidance-into-harness.md`` (D1–D5):
promote the harness to *own* the guidance copy-list rather than install it from
a separate ``agents`` repo. These guards are the evidence that the promotion
landed, and stays landed:

* **AC-1** — ``registry.yaml`` is present at the repo root and
  ``.guidance-lock.yaml`` is gone. A source repo owns the copy-list and does not
  self-lock (D5).
* **AC-2** — the installed surface is held to the registry: skill paths are the
  Agent Skills ``skills/<id>/SKILL.md`` shape (D2, reversed 2026-06-13; CAL-658),
  every surface file's ``guidance:<id>@<version>`` header equals its registry
  version, and the freshness hook runs in SOURCE mode on a surface edit (keyed on
  ``registry.yaml``, not the absent lock).
* **AC-3** — the ``.claude/`` discovery symlinks still resolve.

The presence/absence guards judge the **committed** tree (CAL-619): a clean
checkout must carry ``registry.yaml`` and must not carry the lock, regardless of
what lingers untracked on an author's disk.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "registry.yaml"


def _tracked(rel: str) -> bool:
    """True if ``rel`` is a path git tracks at the repo root."""
    return (REPO_ROOT / rel).resolve() in tracked_files_under(rel)


# --- registry parsing (regex; PyYAML is not a declared dependency) ------------


def _registry_files() -> dict[str, dict[str, object]]:
    """Map each ``files:`` entry path → ``{"version", "profiles"}``.

    The registry's ``files:`` block lists one ``path: { ... }`` entry per line,
    so a line regex is enough and avoids coupling the test to a transitive
    ``yaml`` import. The ``profiles:`` and ``meta:`` blocks are skipped by
    slicing to the ``files:`` section.
    """
    text = REGISTRY.read_text()
    start = text.index("\nfiles:")
    end = text.index("\nmeta:", start)
    out: dict[str, dict[str, object]] = {}
    for line in text[start:end].splitlines():
        m = re.match(r"\s*(?P<path>[\w./-]+):\s*\{(?P<body>.*)\}\s*$", line)
        if not m:
            continue
        body = m.group("body")
        vm = re.search(r"version:\s*([\d.]+)", body)
        if not vm:
            continue
        pm = re.search(r"profiles:\s*\[([^\]]*)\]", body)
        profiles = (
            [p.strip() for p in pm.group(1).split(",") if p.strip()] if pm else []
        )
        out[m.group("path")] = {"version": vm.group(1), "profiles": profiles}
    return out


# --- AC-1: source repo owns the copy-list, does not self-lock -----------------


def test_registry_present_committed() -> None:
    """``registry.yaml`` is a committed file at the repo root (AC-1, D5)."""
    assert _tracked("registry.yaml"), (
        "The harness is the guidance SOURCE now and must carry the copy-list. "
        "Commit registry.yaml at the repo root (CAL-646 AC-1, D5)."
    )


def test_guidance_lock_removed() -> None:
    """``.guidance-lock.yaml`` is gone — a source repo does not self-lock (AC-1, D5)."""
    assert not _tracked(".guidance-lock.yaml"), (
        ".guidance-lock.yaml is a CONSUMER artifact. The harness is source-only / "
        "not self-bootstrapped (D5) — remove it (CAL-646 AC-1)."
    )


# --- AC-2: the surface is held to the registry --------------------------------


def test_registry_lists_skills() -> None:
    """Guard the parser: the registry must list skill entries to check."""
    assert any(p.startswith("skills/") for p in _registry_files()), (
        "registry.yaml lists no skills/ entries — the parser or the copy-list is "
        "wrong."
    )


def test_registry_skill_paths_are_nested() -> None:
    """Skill paths are the Agent Skills ``skills/<id>/SKILL.md`` shape (D2; CAL-658).

    D2 was reversed (2026-06-13) from the flat ``skills/<id>.md`` to the
    directory-per-skill ``skills/<id>/SKILL.md`` structure — the source's shape,
    the spec, and where the Claude Code ecosystem is going. The freshness hook's
    version-drift lookup keys on exactly the registry path, and ``.claude/skills``
    discovery expects ``skills/*/SKILL.md``, so the registry must use it too.
    """
    skill_paths = [p for p in _registry_files() if p.startswith("skills/")]
    bad = [p for p in skill_paths if not re.fullmatch(r"skills/[\w-]+/SKILL\.md", p)]
    assert not bad, (
        f"skill paths must be the Agent Skills shape skills/<id>/SKILL.md (D2, "
        f"reversed 2026-06-13; CAL-658), not the flat skills/<id>.md: {bad}"
    )


def test_harness_profile_files_present() -> None:
    """Every harness-profile surface file the registry lists exists in the tree.

    (Standard-profile-only files are intentionally deferred to the agents-repo
    retirement — breakdown item 7 — so they are not asserted here.)
    """
    missing = [
        p
        for p, meta in _registry_files().items()
        if "harness" in meta["profiles"] and not (REPO_ROOT / p).exists()
    ]
    assert not missing, (
        f"registry.yaml lists these as harness-profile surface but they are "
        f"absent from the tree: {missing}"
    )


def test_surface_headers_match_registry() -> None:
    """Each present, header-carrying surface file's version equals the registry's.

    ``/update-guidance`` and the freshness hook key off the version, so a header
    that drifts from ``registry.yaml`` is invisible breakage. JSON settings carry
    no header (the registry version is authoritative) and are skipped.
    """
    mismatches: list[tuple[str, str, object]] = []
    for path, meta in _registry_files().items():
        fp = REPO_ROOT / path
        if not fp.exists() or path.endswith(".json"):
            continue
        m = re.search(r"guidance:[\w-]+@([\d.]+)", fp.read_text())
        if not m:
            mismatches.append((path, "<no header>", meta["version"]))
        elif m.group(1) != meta["version"]:
            mismatches.append((path, m.group(1), meta["version"]))
    assert not mismatches, (
        "surface file header must equal its registry version "
        f"(file, header, registry): {mismatches}"
    )


def test_freshness_hook_runs_in_source_mode(tmp_path: Path) -> None:
    """Editing a surface file fires the SOURCE-mode freshness reminder (AC-2).

    The hook branches on ``registry.yaml`` present → SOURCE mode vs.
    ``.guidance-lock.yaml`` present → CONSUMER mode. With ``registry.yaml`` at the
    root and the lock gone, a surface edit must yield the SOURCE-mode reminder
    (keyed on ``registry.yaml``), never the CONSUMER "installed guidance" message.

    A non-prose surface file (``hooks/prompt-guard.js``) is used so the leak-guard
    branch is skipped and the version/bump reminder is deterministic. ``TMPDIR`` is
    redirected to an isolated dir so the hook's 4h debounce markers cannot
    suppress the message.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    surface = REPO_ROOT / "hooks" / "prompt-guard.js"
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(surface)}}
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    proc = subprocess.run(
        [node, str(REPO_ROOT / "hooks" / "guidance-freshness.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    ctx = json.loads(proc.stdout).get("additionalContext", "")
    assert "registry.yaml" in ctx, (
        "a surface edit in the source repo must trigger the SOURCE-mode freshness "
        f"reminder (keyed on registry.yaml); got: {ctx!r}"
    )
    assert "installed guidance" not in ctx and ".guidance-lock.yaml" not in ctx, (
        f"hook must be in SOURCE mode, not CONSUMER mode; got: {ctx!r}"
    )


def test_freshness_hook_watches_rehomed_installer(tmp_path: Path) -> None:
    """The hook treats the re-homed installer (``INSTALLER.md``) as a meta file.

    Re-homing the generic installer off ``BOOTSTRAP.md`` only works if the
    freshness hook's ``META`` set follows the rename — otherwise edits to the
    installer bypass version-drift and bump reminders, letting its header and
    registry version silently diverge (CAL-646 review P2). Isolated ``TMPDIR``
    defeats the 4h debounce.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(REPO_ROOT / "INSTALLER.md")},
    }
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    proc = subprocess.run(
        [node, str(REPO_ROOT / "hooks" / "guidance-freshness.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    ctx = json.loads(proc.stdout).get("additionalContext", "")
    assert "INSTALLER.md" in ctx, (
        "editing the re-homed installer must trigger a meta bump/drift reminder "
        f"(the hook's META set must include INSTALLER.md); got: {ctx!r}"
    )
    assert "installed guidance" not in ctx, (
        f"hook must be in SOURCE mode, not CONSUMER mode; got: {ctx!r}"
    )


def test_freshness_hook_ignores_registry_excluded_repo_file(tmp_path: Path) -> None:
    """A repo-owned file the registry does not list draws no SOURCE-mode warning.

    Flipping to SOURCE mode must not make the hook claim a registry-*excluded*
    file is distributed guidance. ``commands/harness.md`` is the canonical
    repo-owned command kept out of ``registry.yaml`` (the app/surface boundary);
    editing it in the source repo must not demand a registry version bump or
    assert consumers installed it (CAL-646 review). Isolated ``TMPDIR`` defeats
    the debounce.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    excluded = REPO_ROOT / "commands" / "harness.md"
    if not excluded.exists():
        pytest.skip("commands/harness.md not present")
    # Precondition: the file really is outside the registry's files:/meta: lists.
    assert "commands/harness.md" not in REGISTRY.read_text()
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(excluded)}}
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    proc = subprocess.run(
        [node, str(REPO_ROOT / "hooks" / "guidance-freshness.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    ctx = json.loads(proc.stdout).get("additionalContext", "")
    assert ctx == "", (
        "editing a registry-excluded repo-owned file must produce no freshness "
        f"warning in SOURCE mode; got: {ctx!r}"
    )


def test_freshness_hook_always_checks_meta_files(tmp_path: Path) -> None:
    """Meta files are checked regardless of registry membership.

    The registry-membership gate must apply only to distributable *surface*
    files — not to meta files (``registry.yaml`` / ``INSTALLER.md``). Otherwise a
    malformed registry edit that drops its own ``meta:`` self-entry would make
    ``registryMember`` return false and silently skip the bump/drift reminder for
    the very file being broken (CAL-646 review). This fixture writes a registry
    whose ``meta:`` block omits the ``registry.yaml`` self-entry and confirms an
    edit to it still warns.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    # A SOURCE-mode repo whose registry does NOT list registry.yaml in meta:.
    (tmp_path / "registry.yaml").write_text(
        "# guidance:registry@0.4.0\nregistry_format: 1\nfiles:\n"
        "  skills/code-quality.md: { id: code-quality, version: 0.4.0, profiles: [harness] }\n"
        "meta:\n  INSTALLER.md: { id: bootstrap, version: 0.4.2 }\n"
    )
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "registry.yaml")},
    }
    env = {**os.environ, "TMPDIR": str(tmp_path / "_tmp")}
    (tmp_path / "_tmp").mkdir()
    proc = subprocess.run(
        [node, str(REPO_ROOT / "hooks" / "guidance-freshness.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(tmp_path),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    ctx = json.loads(proc.stdout).get("additionalContext", "")
    assert "registry.yaml" in ctx or "CHANGELOG" in ctx, (
        "editing a meta file must always trigger a freshness reminder, even when "
        f"its own registry entry is missing/malformed; got: {ctx!r}"
    )


def test_freshness_hook_warns_on_unregistered_headered_surface(tmp_path: Path) -> None:
    """A new *headered* surface file not yet in the registry still gets a reminder.

    The membership exclusion is for repo-owned files, which are *headerless* (the
    same "no ``guidance:`` header → repo-owned" rule the installer uses). A new
    distributable file that carries a ``guidance:`` header but has not been added
    to ``registry.yaml`` yet must still be nudged to register/version — otherwise
    the hook stops being a registry-integrity backstop (CAL-646 review).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    (tmp_path / "registry.yaml").write_text(
        "# guidance:registry@0.4.0\nregistry_format: 1\nfiles:\n"
        "  skills/code-quality.md: { id: code-quality, version: 0.4.0, profiles: [harness] }\n"
        "meta:\n  INSTALLER.md: { id: bootstrap, version: 0.4.2 }\n"
    )
    (tmp_path / "skills").mkdir()
    new_file = tmp_path / "skills" / "new-skill.md"
    new_file.write_text("<!-- guidance:new-skill@0.1.0 -->\n# New skill\n")
    (tmp_path / "_tmp").mkdir()
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(new_file)}}
    env = {**os.environ, "TMPDIR": str(tmp_path / "_tmp")}
    proc = subprocess.run(
        [node, str(REPO_ROOT / "hooks" / "guidance-freshness.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(tmp_path),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    ctx = json.loads(proc.stdout).get("additionalContext", "")
    assert "registry.yaml" in ctx, (
        "a new headered surface file absent from the registry must still draw a "
        f"register/bump reminder; got: {ctx!r}"
    )


def test_freshness_hook_warns_on_unregistered_json_settings(tmp_path: Path) -> None:
    """A new headerless ``settings/*.json`` not yet in the registry still warns.

    JSON settings are headerless *by design* yet are distributable guidance, so
    the "headerless → repo-owned" exclusion must not swallow them: a new
    ``settings/<profile>.json`` created before its registry entry must still draw
    the register/version reminder (CAL-646 review). Repo-owned files (the
    ``commands/harness.md`` case) are headerless **and** not ``.json``.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    (tmp_path / "registry.yaml").write_text(
        "# guidance:registry@0.4.0\nregistry_format: 1\nfiles:\n"
        "  skills/code-quality.md: { id: code-quality, version: 0.4.0, profiles: [harness] }\n"
        "meta:\n  INSTALLER.md: { id: bootstrap, version: 0.4.2 }\n"
    )
    (tmp_path / "settings").mkdir()
    new_json = tmp_path / "settings" / "newprofile.json"
    new_json.write_text('{"hooks": {}}\n')
    (tmp_path / "_tmp").mkdir()
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(new_json)}}
    env = {**os.environ, "TMPDIR": str(tmp_path / "_tmp")}
    proc = subprocess.run(
        [node, str(REPO_ROOT / "hooks" / "guidance-freshness.js")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(tmp_path),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    ctx = json.loads(proc.stdout).get("additionalContext", "")
    assert "registry.yaml" in ctx, (
        "a new headerless JSON settings file absent from the registry must still "
        f"draw a register/bump reminder; got: {ctx!r}"
    )


# --- AC-3: discovery symlinks still resolve -----------------------------------


@pytest.mark.parametrize("name", ["commands", "skills", "agents", "hooks"])
def test_claude_discovery_symlink_resolves(name: str) -> None:
    """``.claude/<name>`` is a symlink resolving to a real directory (AC-3)."""
    link = REPO_ROOT / ".claude" / name
    assert link.is_symlink(), f".claude/{name} must be a discovery symlink"
    assert link.resolve().is_dir(), (
        f".claude/{name} symlink does not resolve to a directory"
    )
