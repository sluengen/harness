"""CAL-834 — freshness hook: dedicated edit-time warning for registry self-parity.

``registry.yaml`` carries its own version in two places: the
``# guidance:registry@X`` file-stamp header and its own row in the ``meta:``
inventory table (``registry.yaml: { id: registry, version: X }``). The integrity
guard ``test_guidance_github_source.test_registry_header_matches_meta_self_version``
requires the two to match, but both live in one file, so a one-sided bump is
easy to miss — and its only feedback is a gate-time failure.

``hooks/guidance-freshness.js`` already compared the two for ``registry.yaml`` in
its generic version-drift block, but that warning shared one debounce marker
(``D_DRIFT``) with every other file's drift — so an unrelated drift warning in
the same 4h window masked it (exactly what happened on the CAL-829 run). This
ticket gives the self-parity case a **dedicated** debounce marker (``D_SELFVER``)
and a message naming both spots and the enforcing guard.

These tests execute the hook as a node subprocess against a *synthetic* source
repo in ``tmp_path`` (in the style of
``test_guidance_source.test_freshness_hook_ignores_registry_excluded_repo_file``),
with ``TMPDIR`` redirected to an isolated dir so the 4h debounce markers are
fully under the test's control.

Acceptance criteria:

* **AC-1** — editing ``registry.yaml`` with header != meta self-entry warns, and
  the message names ``test_registry_header_matches_meta_self_version`` and the
  two-places nature. :func:`test_mismatch_warns_and_names_guard`.
* **AC-2** — the warning keys off its own marker, not ``D_DRIFT``: a recent
  ``D_DRIFT`` does not mask it, and a recent ``D_SELFVER`` does suppress it.
  :func:`test_not_masked_by_generic_drift_marker`,
  :func:`test_suppressed_by_its_own_marker`.
* **AC-3** — header == meta self-entry yields no self-parity warning, and the
  generic bump reminder still fires. :func:`test_match_is_silent_on_self_parity`.
* **AC-4** — editing a non-registry file does not trigger the self-parity
  warning. :func:`test_non_registry_edit_has_no_self_parity_warning`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "guidance-freshness.js"

#: The unique signal the self-parity warning carries (the enforcing guard's name).
_GUARD = "test_registry_header_matches_meta_self_version"
#: The hook's debounce marker base names inside ``TMPDIR``. Since #457 each one
#: carries a suffix scoping it to the repository the hook ran in — the markers
#: live in the machine-wide temp directory, so a fixed name let one checkout's
#: warning silence another's. :func:`_marker` reproduces the suffix, which is why
#: these are base names rather than filenames.
_D_DRIFT = "guidance-freshness-drift"
_D_SELFVER = "guidance-freshness-selfver"


def _marker(repo: Path, base: str) -> Path:
    """The scoped debounce marker ``base`` resolves to for a hook run in ``repo``.

    Mirrors ``scopedState`` in the hook: a truncated SHA-256 of the working
    directory. Pre-seeding a marker is how the two AC-2 cases distinguish "keys
    on its own marker" from "keys on the shared one", and a test that seeded an
    unscoped name would seed a file the hook never looks at — which reads as
    "the warning was not suppressed" no matter what the hook does.
    """
    key = hashlib.sha256(str(repo).encode()).hexdigest()[:16]
    return repo / "_tmp" / f"{base}-{key}"


def _registry(header_ver: str, self_ver: str) -> str:
    """A minimal source ``registry.yaml`` with a controllable header / self-entry.

    Includes one ``files:`` skill row (header-matched, so editing it draws no
    drift) and the ``registry.yaml`` ``meta:`` self-entry at ``self_ver``.
    """
    return (
        f"# guidance:registry@{header_ver}\n"
        "registry_format: 1\n"
        "files:\n"
        "  skills/foo/SKILL.md: { id: foo, version: 0.5.0, profiles: [harness] }\n"
        "meta:\n"
        f"  registry.yaml: {{ id: registry, version: {self_ver} }}\n"
    )


def _build_repo(tmp_path: Path, header_ver: str, self_ver: str) -> Path:
    """Lay down a synthetic source repo; return its root (the hook's ``cwd``)."""
    (tmp_path / "registry.yaml").write_text(_registry(header_ver, self_ver))
    skill = tmp_path / "skills" / "foo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("<!-- guidance:foo@0.5.0 -->\n# Foo\nbody\n")
    (tmp_path / "_tmp").mkdir()
    return tmp_path


def _run_hook(repo: Path, edited: Path) -> str:
    """Run the hook for an edit of ``edited`` in ``repo``; return additionalContext.

    ``TMPDIR`` points at ``repo/_tmp`` so the debounce markers are isolated and a
    test can pre-seed them.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(edited)}}
    env = {**os.environ, "TMPDIR": str(repo / "_tmp")}
    proc = subprocess.run(
        [node, str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(repo),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    return json.loads(proc.stdout).get("additionalContext", "")


# --- AC-1: the mismatch warns and names the guard -----------------------------


def test_mismatch_warns_and_names_guard(tmp_path: Path) -> None:
    """header @0.5.0 vs meta self-entry @0.4.0 → self-parity warning (AC-1)."""
    repo = _build_repo(tmp_path, header_ver="0.5.0", self_ver="0.4.0")
    ctx = _run_hook(repo, repo / "registry.yaml")
    assert _GUARD in ctx, (
        f"the self-parity warning must name the enforcing guard {_GUARD!r}; "
        f"got: {ctx!r}"
    )
    assert "two places" in ctx.lower(), (
        f"the warning must state the version lives in two places; got: {ctx!r}"
    )
    # Both disagreeing versions are surfaced so the fix is unambiguous.
    assert "0.5.0" in ctx and "0.4.0" in ctx, (
        f"the warning must name both the header and self-entry versions; got: {ctx!r}"
    )


# --- AC-2: the marker is dedicated, not the shared D_DRIFT ---------------------


def test_not_masked_by_generic_drift_marker(tmp_path: Path) -> None:
    """A recent D_DRIFT (another file's drift) must NOT mask the warning (AC-2)."""
    repo = _build_repo(tmp_path, header_ver="0.5.0", self_ver="0.4.0")
    # Simulate an unrelated drift warning earlier in the same window.
    _marker(repo, _D_DRIFT).write_text("recent")
    ctx = _run_hook(repo, repo / "registry.yaml")
    assert _GUARD in ctx, (
        "a recent generic-drift marker must not suppress the self-parity warning "
        f"(it keys on its own marker); got: {ctx!r}"
    )


def test_suppressed_by_its_own_marker(tmp_path: Path) -> None:
    """A recent D_SELFVER suppresses the self-parity warning (proves it keys on it)."""
    repo = _build_repo(tmp_path, header_ver="0.5.0", self_ver="0.4.0")
    _marker(repo, _D_SELFVER).write_text("recent")
    ctx = _run_hook(repo, repo / "registry.yaml")
    assert _GUARD not in ctx, (
        "a recent self-parity marker must debounce the warning — it must key on a "
        f"dedicated marker distinct from D_DRIFT; got: {ctx!r}"
    )


# --- AC-3: a matched registry is silent on self-parity ------------------------


def test_match_is_silent_on_self_parity(tmp_path: Path) -> None:
    """header == meta self-entry → no self-parity warning; generic reminder stays."""
    repo = _build_repo(tmp_path, header_ver="0.5.0", self_ver="0.5.0")
    ctx = _run_hook(repo, repo / "registry.yaml")
    assert _GUARD not in ctx, (
        f"a matched header/self-entry must not warn about self-parity; got: {ctx!r}"
    )
    # The generic version-stamp bump reminder is unchanged.
    assert "registry.yaml" in ctx and "bump" in ctx.lower(), (
        f"editing registry.yaml must still draw the generic bump reminder; got: {ctx!r}"
    )


# --- AC-4: a non-registry edit is unaffected ----------------------------------


def test_non_registry_edit_has_no_self_parity_warning(tmp_path: Path) -> None:
    """Editing a skill (even with registry.yaml itself mismatched) is unaffected."""
    repo = _build_repo(tmp_path, header_ver="0.5.0", self_ver="0.4.0")
    ctx = _run_hook(repo, repo / "skills" / "foo" / "SKILL.md")
    assert _GUARD not in ctx, (
        "the registry self-parity warning must fire only for registry.yaml edits, "
        f"not for a skill edit; got: {ctx!r}"
    )
