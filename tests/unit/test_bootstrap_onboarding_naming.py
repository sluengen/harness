"""CAL-835 — the guidance installer and the harness onboarding doc carry
non-inverted names.

History: the pre-merge agents-repo installer was ``guidance:bootstrap``, named
``BOOTSTRAP.md``. The merge into the harness collided with the harness's own
``BOOTSTRAP.md`` onboarding doc, so the installer was re-homed to ``INSTALLER.md``
while keeping its ``bootstrap`` id — leaving the filename and the id inverted:
the file *named* INSTALLER was the bootstrap, and the file *named* BOOTSTRAP was
the onboarding/setup doc. ``bootstrap`` and ``installer`` are near-synonyms, so
the pair read as interchangeable. CAL-835 realigns each name to its distinct
concept:

* the installer (``guidance:bootstrap``) is ``BOOTSTRAP.md`` — filename matches id
  and the "re-bootstrap" verb the prose uses throughout;
* the harness onboarding/setup doc is ``ONBOARDING.md`` — filename matches its
  own title ("onboarding the harness to a repo").

These guards pin the realigned names so the inversion cannot silently return.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_OLD = REPO_ROOT / "INSTALLER.md"
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"  # the installer (guidance:bootstrap)
ONBOARDING = REPO_ROOT / "ONBOARDING.md"  # the harness onboarding/setup doc
REGISTRY = REPO_ROOT / "registry.yaml"
FRESHNESS_HOOK = REPO_ROOT / "hooks" / "guidance-freshness.js"

#: Live guidance docs that must not reference the retired ``INSTALLER.md``
#: filename. CHANGELOG.md, assessments/, and specs/proposals/ are historical
#: records — they legitimately name the filename that existed at the time.
_LIVE_DOCS = (
    "BOOTSTRAP.md",
    "ONBOARDING.md",
    "RELEASING.md",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "process/harness.md",
    "commands/update-guidance.md",
)


def test_old_installer_filename_is_gone() -> None:
    """``INSTALLER.md`` is retired — the installer re-homes to ``BOOTSTRAP.md``."""
    assert INSTALLER_OLD.resolve() not in tracked_files_under("INSTALLER.md"), (
        "INSTALLER.md must no longer be a tracked file — the guidance installer "
        "re-homes to BOOTSTRAP.md so its filename matches its `bootstrap` id "
        "(CAL-835)."
    )


def test_installer_is_bootstrap_md() -> None:
    """``BOOTSTRAP.md`` is the installer and carries the ``bootstrap`` header."""
    assert BOOTSTRAP.resolve() in tracked_files_under("BOOTSTRAP.md"), (
        "BOOTSTRAP.md (the guidance installer) must be a committed file (CAL-835)."
    )
    first = BOOTSTRAP.read_text().splitlines()[0]
    assert re.match(r"<!--\s*guidance:bootstrap@[\d.]+\s*-->", first), (
        "BOOTSTRAP.md must carry the `guidance:bootstrap@<version>` header on line "
        f"1 — it IS the installer; got: {first!r} (CAL-835)."
    )


def test_onboarding_doc_is_onboarding_md() -> None:
    """``ONBOARDING.md`` is the repo-owned harness onboarding/setup doc."""
    assert ONBOARDING.resolve() in tracked_files_under("ONBOARDING.md"), (
        "ONBOARDING.md (the harness onboarding/setup doc) must be a committed file "
        "(CAL-835)."
    )
    first = ONBOARDING.read_text().splitlines()[0]
    assert not first.startswith("<!-- guidance:"), (
        "ONBOARDING.md is a repo-owned doc, not a distributable — it must NOT carry "
        f"a `guidance:` header; got: {first!r} (CAL-835)."
    )
    assert "onboarding" in first.lower(), (
        f"ONBOARDING.md's title must name onboarding; got: {first!r} (CAL-835)."
    )


def test_registry_meta_maps_bootstrap_md() -> None:
    """``registry.yaml`` ``meta:`` maps ``BOOTSTRAP.md -> { id: bootstrap }``."""
    text = REGISTRY.read_text()
    assert re.search(
        r"^\s*BOOTSTRAP\.md:\s*\{[^}]*id:\s*bootstrap", text, re.MULTILINE
    ), "registry.yaml meta: must map BOOTSTRAP.md -> { id: bootstrap } (CAL-835)."
    assert "INSTALLER.md:" not in text, (
        "registry.yaml must not carry an INSTALLER.md meta key — the installer is "
        "BOOTSTRAP.md now (CAL-835)."
    )


def test_freshness_hook_meta_watches_bootstrap_md() -> None:
    """The freshness hook's ``META`` set watches ``BOOTSTRAP.md``, not the old name."""
    text = FRESHNESS_HOOK.read_text()
    meta_line = next((ln for ln in text.splitlines() if "const META" in ln), "")
    assert "BOOTSTRAP" in meta_line and "INSTALLER" not in meta_line, (
        "hooks/guidance-freshness.js META set must watch BOOTSTRAP.md (the "
        f"re-homed installer), not INSTALLER.md (CAL-835); got: {meta_line!r}"
    )


def test_no_live_doc_references_retired_installer_filename() -> None:
    """No live guidance doc names the retired ``INSTALLER.md`` filename."""
    offenders = [
        rel
        for rel in _LIVE_DOCS
        if (REPO_ROOT / rel).exists() and "INSTALLER.md" in (REPO_ROOT / rel).read_text()
    ]
    assert not offenders, (
        f"these live docs still reference the retired INSTALLER.md filename: "
        f"{list(offenders)}. The installer is BOOTSTRAP.md now — update the "
        "references (CAL-835)."
    )
