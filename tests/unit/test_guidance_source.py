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
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
CONTEXT_TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"


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


def _registry_profile_names() -> list[str]:
    """The profile keys declared under the registry's ``profiles:`` block.

    A profile key is a two-space-indented ``name:`` line (no further nesting,
    no inline value) between ``\\nprofiles:`` and the following ``\\nfiles:``
    block. Comment and blank lines are skipped. Kept regex-only for the same
    reason as :func:`_registry_files` — PyYAML is not a declared dependency.
    """
    text = REGISTRY.read_text()
    start = text.index("\nprofiles:")
    end = text.index("\nfiles:", start)
    names: list[str] = []
    for line in text[start:end].splitlines():
        m = re.fullmatch(r"  (?P<name>[A-Za-z0-9_-]+):\s*", line)
        if m:
            names.append(m.group("name"))
    return names


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


# --- CAL-652: one surface, no standard/harness profile split ------------------
#
# The standard-vs-harness profile split is retired (specs/architecture-principles.md,
# "maturity-only", 2026-06-13): one surface, one profile; repo-type variation
# (feature_specs, design_system) is per-repo CONTEXT.md ``layers:`` config, not a
# profile. These guards keep a second profile (and the retired standard-only
# process/settings files) from creeping back into the registry.


def test_registry_has_single_profile() -> None:
    """``registry.yaml`` declares exactly one profile, and not ``standard`` (CAL-652, AC-1)."""
    names = _registry_profile_names()
    assert names == ["harness"], (
        "the standard/harness profile split is retired — one surface, one profile "
        f"(specs/architecture-principles.md, 'maturity-only'). Got profiles: {names}. "
        "Do not re-introduce a second profile; repo-type variation is per-repo "
        "CONTEXT.md layers: config (CAL-652, AC-1)."
    )


def test_registry_lists_no_standard_only_files() -> None:
    """No retired standard-only files reappear in the copy-list (CAL-652, AC-1/AC-3).

    The standard process doc and settings were folded into the single surface —
    ``process/standard.md`` is absorbed into ``process/harness.md`` and
    ``settings/standard.json`` was byte-identical to ``settings/harness.json``.
    Re-listing either would re-create the split.
    """
    paths = set(_registry_files())
    assert "process/standard.md" not in paths, (
        "process/standard.md is retired; its content is folded into the single "
        "process doc process/harness.md (CAL-652, AC-1)."
    )
    assert "settings/standard.json" not in paths, (
        "settings/standard.json is retired (it was byte-identical to "
        "settings/harness.json, the single settings file) (CAL-652, AC-1)."
    )


def test_imported_product_skills_are_home() -> None:
    """The product-only skills brought home (D6) are listed and present (CAL-652, AC-3).

    design-system and ux-design were the standard-profile-only skills; with the
    agents repo retired they live in the one surface. design-system engages only
    where the CONTEXT.md ``design_system`` layer is on (install-time gating is
    CAL-675); ux-design applies to any user-facing surface, independent of that
    layer.
    """
    files = _registry_files()
    for skill in ("skills/design-system/SKILL.md", "skills/ux-design/SKILL.md"):
        assert skill in files, f"{skill} must be listed in registry.yaml (CAL-652, AC-3)"
        assert (REPO_ROOT / skill).exists(), f"{skill} must be present in the tree (CAL-652, AC-3)"


def test_imported_feature_template_is_home() -> None:
    """The feature-spec template brought home (D6) is listed and present (CAL-652, AC-3).

    ``templates/feature.md`` is the as-built record template a repo uses when its
    ``feature_specs`` layer is on; with the agents repo retired it lives in the
    one surface.
    """
    assert "templates/feature.md" in _registry_files(), (
        "templates/feature.md must be listed in registry.yaml (CAL-652, AC-3)"
    )
    assert (REPO_ROOT / "templates" / "feature.md").exists(), (
        "templates/feature.md must be present in the tree (CAL-652, AC-3)"
    )


def test_process_doc_does_not_gate_ux_design_on_design_system() -> None:
    """ux-design applies to ANY user-facing surface, not only when design_system is on.

    The merged process doc (CAL-652, AC-1) must not couple ux-design to the
    design_system layer: the imported skill (skills/ux-design/SKILL.md) applies to
    any user-facing interface, design system or not — only design-system is
    layer-gated. Regression guard for the CAL-652 review finding that the merge
    dropped this standard-process behavior.
    """
    rows = [
        ln
        for ln in PROCESS_DOC.read_text().splitlines()
        if re.match(r"\|\s*`ux-design`", ln)
    ]
    assert rows, "process/harness.md has no ux-design skills-table row to check"
    row = rows[0]
    assert "user-facing" in row, (
        f"the ux-design row must tie the skill to any user-facing surface; got: {row!r}"
    )
    # The regression coupled ux-design to the layer ("only when design_system …").
    # Mentioning the layer to say ux-design is *independent* of it is fine; gating
    # on it is not.
    assert not re.search(r"only when[^|]*design_system", row), (
        "the ux-design row must NOT gate the skill on the design_system layer — "
        f"ux-design applies regardless of a design system; got: {row!r}"
    )


def test_process_doc_states_one_unconditional_build_option() -> None:
    """The process doc must not carve a repo out of the option it publishes.

    ``process/harness.md`` is the single distributed process doc — it installs as
    every consumer's ``AGENTS.md``. CAL-652 found it unconditionally forbidding
    ``/build`` "here", which misinstructed every consumer, and the fix was to gate
    the steer on ``CONTEXT.md`` repo identity. #435 removed the thing the carve-out
    existed for: there is no second execution surface to prefer, so the rule is
    now that ``/build`` is simply available everywhere.

    The guard therefore keeps the original defect's polarity and tightens it. The
    original defect — a prohibition on ``/build`` — must still be absent, tested
    verbatim. The gate that used to make it safe must now *also* be absent: a
    repo-identity condition on the execution option is exactly the drift that
    would reintroduce a two-surface split under a new name. And the positive half
    is asserted, so an edit satisfying both negatives by deleting the option
    entirely fails.
    """
    text = PROCESS_DOC.read_text()
    assert "Do not invoke `/build` or `/build-codex` here." not in text, (
        "process/harness.md unconditionally forbids /build; as the single "
        "distributed process doc this misinstructs non-harness repos (CAL-652)."
    )
    assert "If this repo is the harness" not in text, (
        "process/harness.md carves this repo out of the execution option it "
        "publishes. ADR 0015 left one surface — the carve-out named a second "
        "one that no longer exists (#435)."
    )
    assert re.search(r"`/build`", text), (
        "the process doc must name `/build` as the way a ticket is driven."
    )
    assert re.search(r"available in every repo|available everywhere", text), (
        "the process doc must state that the option it publishes is available "
        "everywhere — the property the retired carve-out used to qualify."
    )


#: A line that GATES something on the design_system layer: a gating phrase
#: ("only when/where", "gated on") adjacent to the design_system layer name.
#: Lines that say a skill is *independent* of the layer are exempted by the
#: caller (they legitimately name both while decoupling them).
_LAYER_GATE_RE = re.compile(
    r"(?:only when|only where|gated on)[^|\n]*design_system"
    r"|design_system[^|\n]*(?:only when|only where|gated on)"
)


def test_no_canonical_file_gates_ux_design_on_design_system() -> None:
    """ux-design is never gated on the design_system layer in canonical metadata.

    The fix must hold across every canonical home, not just the process-doc
    skills table: the merged process doc and the ``registry.yaml`` copy-list
    comments both describe the skills. ux-design applies
    to any user-facing surface regardless of a design system; only design-system
    is layer-gated (skills/ux-design/SKILL.md). A line that names ux-design while
    gating it on the design_system layer is the regression — unless it is
    explicitly decoupling them (``independent``). Guards the CAL-652 review
    finding across canonical metadata.
    """
    canonical = {
        "process/harness.md": PROCESS_DOC,
        "registry.yaml": REGISTRY,
    }
    offenders: list[str] = []
    for name, path in canonical.items():
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if "ux-design" not in line or "independent" in line:
                continue
            if _LAYER_GATE_RE.search(line):
                offenders.append(f"{name}:{i}: {line.strip()}")
    assert not offenders, (
        "ux-design must not be gated on the design_system layer (it applies to "
        f"any user-facing surface; only design-system is layer-gated): {offenders}"
    )


def test_context_template_documents_layer_mapping() -> None:
    """AC-2: the CONTEXT template documents the feature_specs/design_system layer mapping.

    The old profiles' ``default_layers`` are now per-repo ``CONTEXT.md`` layers;
    the scaffold must teach that mapping and drop the standard|harness profile
    choice.
    """
    text = CONTEXT_TEMPLATE.read_text()
    assert "standard | harness" not in text, (
        "the CONTEXT template still offers a standard|harness profile choice; the "
        "profile split is retired (CAL-652, AC-2)."
    )
    assert re.search(r"feature_specs:.*#.*specs/features", text), (
        "the CONTEXT template must document the feature_specs layer (records to "
        "specs/features/) (CAL-652, AC-2)."
    )
    assert re.search(r"design_system:.*#.*design system", text), (
        "the CONTEXT template must document the design_system layer (CAL-652, AC-2)."
    )


# --- AC-2: the surface is held to the registry --------------------------------


def test_registry_lists_skills() -> None:
    """Guard the parser: the registry must list skill entries to check."""
    assert any(p.startswith("skills/") for p in _registry_files()), (
        "registry.yaml lists no skills/ entries — the parser or the copy-list is "
        "wrong."
    )


def test_registry_skill_paths_are_nested() -> None:
    """Skill roots and their one-level references use the nested Agent Skills shape.

    D2 was reversed (2026-06-13) from the flat ``skills/<id>.md`` to the
    directory-per-skill ``skills/<id>/SKILL.md`` structure — the source's shape,
    the spec, and where the Claude Code ecosystem is going. The freshness hook's
    version-drift lookup keys on exactly the registry path, and ``.claude/skills``
    discovery expects ``skills/*/SKILL.md``, so the registry must use it too.
    """
    skill_paths = [p for p in _registry_files() if p.startswith("skills/")]
    allowed = r"skills/[\w-]+/(?:SKILL\.md|references/[\w-]+\.md)"
    bad = [p for p in skill_paths if not re.fullmatch(allowed, p)]
    assert not bad, (
        "skill paths must be roots or one-level registered references beneath "
        f"skills/<id>; invalid paths: {bad}"
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
    """The hook treats the installer (``BOOTSTRAP.md``) as a meta file.

    The installer's filename has moved over time — the agents-repo's
    ``BOOTSTRAP.md`` became ``INSTALLER.md`` on the merge (CAL-646 review P2),
    then realigned back to ``BOOTSTRAP.md`` so its filename matches its
    ``bootstrap`` id (CAL-835). Each move only works if the freshness hook's
    ``META`` set follows the current name — otherwise edits to the installer
    bypass version-drift and bump reminders, letting its header and registry
    version silently diverge. Isolated ``TMPDIR`` defeats the 4h debounce.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    payload = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(REPO_ROOT / "BOOTSTRAP.md")},
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
    assert "BOOTSTRAP.md" in ctx, (
        "editing the re-homed installer must trigger a meta bump/drift reminder "
        f"(the hook's META set must include BOOTSTRAP.md); got: {ctx!r}"
    )
    assert "installed guidance" not in ctx, (
        f"hook must be in SOURCE mode, not CONSUMER mode; got: {ctx!r}"
    )


def test_freshness_hook_ignores_registry_excluded_repo_file(tmp_path: Path) -> None:
    """A repo-owned file the registry does not list draws no SOURCE-mode warning.

    Flipping to SOURCE mode must not make the hook claim a registry-*excluded*
    file is distributed guidance. The hook treats a surface-dir file that is
    absent from ``registry.yaml``, carries no ``guidance:`` header, and is not a
    ``.json`` as repo-owned (e.g. a consuming repo's own namespaced command):
    editing it must not demand a registry version bump or assert consumers
    installed it (CAL-646 review). A synthetic repo isolates the behaviour from
    any one real file's registry status — ``commands/harness.md`` was this example
    until CAL-764 registered it as a distributed surface unit. Isolated ``TMPDIR``
    defeats the debounce.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    (tmp_path / "registry.yaml").write_text(
        "# guidance:registry@0.4.0\nregistry_format: 1\nfiles:\n"
        "  commands/start.md: { id: start, version: 0.2.1, profiles: [harness] }\n"
        "meta:\n  BOOTSTRAP.md: { id: bootstrap, version: 0.4.2 }\n"
    )
    (tmp_path / "commands").mkdir()
    # A genuinely repo-owned command: under a surface dir, headerless, not .json,
    # and absent from the registry's files:/meta: lists.
    repo_owned = tmp_path / "commands" / "myrepo.md"
    repo_owned.write_text("# /myrepo — a repo's own command\n")
    assert "commands/myrepo.md" not in (tmp_path / "registry.yaml").read_text()
    (tmp_path / "_tmp").mkdir()
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(repo_owned)}}
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
    assert ctx == "", (
        "editing a registry-excluded repo-owned file must produce no freshness "
        f"warning in SOURCE mode; got: {ctx!r}"
    )


def test_freshness_hook_always_checks_meta_files(tmp_path: Path) -> None:
    """Meta files are checked regardless of registry membership.

    The registry-membership gate must apply only to distributable *surface*
    files — not to meta files (``registry.yaml`` / ``BOOTSTRAP.md``). Otherwise a
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
        "meta:\n  BOOTSTRAP.md: { id: bootstrap, version: 0.4.2 }\n"
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
        "meta:\n  BOOTSTRAP.md: { id: bootstrap, version: 0.4.2 }\n"
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
    the register/version reminder (CAL-646 review). The headerless→repo-owned
    exclusion the hook applies is for genuinely repo-owned files (headerless
    **and** not ``.json`` — e.g. a repo's own namespaced command), which JSON
    settings are not. (``commands/harness.md`` was that example until CAL-764
    registered it as a headered surface unit.)
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    (tmp_path / "registry.yaml").write_text(
        "# guidance:registry@0.4.0\nregistry_format: 1\nfiles:\n"
        "  skills/code-quality.md: { id: code-quality, version: 0.4.0, profiles: [harness] }\n"
        "meta:\n  BOOTSTRAP.md: { id: bootstrap, version: 0.4.2 }\n"
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


# --- CAL-660: the harness turns on its own feature_specs layer ----------------
#
# The harness publishes the feature-spec skill, so it dogfoods it: its own
# per-repo config sets ``feature_specs: true`` and its as-built record lives in
# ``specs/features/`` (the migration of the record is CAL-661). No surface text
# may keep pinning the harness to design-doc specs or to a profile.

HARNESS_CONTEXT = REPO_ROOT / "CONTEXT.md"

#: Surface docs that must not pin the harness to design-doc specs (AC-2/AC-3).
_DESIGN_DOC_DOCS = [
    PROCESS_DOC,
    REPO_ROOT / "skills" / "spec-driven-development" / "SKILL.md",
]
#: A line claiming the harness uses design-doc specs (the stale, now-false claim).
_HARNESS_DESIGN_DOC_RE = re.compile(r"harness.*design[- ]doc spec", re.IGNORECASE)


def test_harness_context_enables_feature_specs() -> None:
    """AC-1: the harness's own CONTEXT.md turns on feature_specs at specs/features/.

    The flip is per-repo config, not a profile: the layers block sets
    ``feature_specs: true`` and points the as-built record at ``specs/features/``.
    """
    text = HARNESS_CONTEXT.read_text()
    assert re.search(r"feature_specs:\s*true", text), (
        "the harness CONTEXT.md layers: must set feature_specs: true — the harness "
        "dogfoods the feature-spec surface it publishes (CAL-660, AC-1)."
    )
    assert "specs/features" in text, (
        "the harness CONTEXT.md must declare the specs/features/ path for its "
        "as-built record (CAL-660, AC-1)."
    )


def test_surface_does_not_pin_harness_to_design_docs() -> None:
    """AC-2/AC-3: no surface doc states the harness uses design-doc specs.

    With ``feature_specs`` on, the universal process doc and the spec-driven-
    development skill must not present the harness (or a "harness profile") as a
    design-doc-spec repo — that is the divergence and the resurrected profile
    language this ticket removes. The generic Off-branch layer description stays;
    it does not name the harness.
    """
    offenders: list[str] = []
    for path in _DESIGN_DOC_DOCS:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if _HARNESS_DESIGN_DOC_RE.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, (
        "surface docs still pin the harness to design-doc specs; the harness sets "
        f"feature_specs: true (CAL-660, AC-2/AC-3): {offenders}"
    )
