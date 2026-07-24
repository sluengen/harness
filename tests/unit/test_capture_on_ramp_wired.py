"""#202 — wire `/bug` and `/tweak` into the process docs + command table.

*Source:* ``specs/proposals/bug-and-tweak-capture-commands.md`` (accepted
2026-07-24), breakdown item 4. Depends on items 1-3 (``templates/adjustment.md``
#199, ``commands/bug.md`` #200, ``commands/tweak.md`` #201 — all shipped and
already registered in ``registry.yaml``). This ticket's remaining scope is
documentation only:

* name the capture on-ramp in ``spec-driven-development`` / ``spec-authoring``
  (where change specs are introduced), and
* add ``/bug`` / ``/tweak`` to the ``process/harness.md`` command table (whose
  byte-identical mirrors are ``CLAUDE.md`` / ``AGENTS.md`` / ``GEMINI.md``),
  with the crisp three-way boundary written explicitly: capture the
  confirmed-small (``/bug``, ``/tweak``) vs decide the unconfirmed
  (``/propose``) vs pick up the filed (``/start``) — the defense named against
  a later steward lean/MECE finding (the proposal's own Risks section).

These guards pin that the wiring landed and stays consistent (header versions
matching their ``registry.yaml`` entries).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
MIRRORS = [REPO_ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")]
SPEC_DRIVEN = REPO_ROOT / "skills" / "spec-driven-development" / "SKILL.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def _registry_entry(path: str) -> str:
    pattern = re.escape(path) + r":\s*\{[^}]*\}"
    m = re.search(pattern, REGISTRY.read_text())
    assert m, f"registry.yaml must have a files: entry for {path}"
    return m.group(0)


# --- AC-1: the command table lists /bug and /tweak, with the boundary stated -


def test_command_table_lists_bug() -> None:
    text = PROCESS_DOC.read_text()
    assert re.search(r"\|\s*`/bug[^`]*`\s*\|", text), (
        "process/harness.md's Commands table must list `/bug` (#202 AC-1)."
    )


def test_command_table_lists_tweak() -> None:
    text = PROCESS_DOC.read_text()
    assert re.search(r"\|\s*`/tweak[^`]*`\s*\|", text), (
        "process/harness.md's Commands table must list `/tweak` (#202 AC-1)."
    )


def test_three_way_boundary_stated_explicitly() -> None:
    """The proposal's own Risks section warns a steward lean/MECE finding will
    ask why two commands (`/bug`/`/tweak`) share a template with `/propose` and
    `/start` unless the boundary is written into the command table, not left
    implicit. Assert the three roles are named in the same document."""
    text = PROCESS_DOC.read_text()
    assert "/propose" in text and "/bug" in text and "/tweak" in text and "/start" in text, (
        "process/harness.md must name /propose, /bug, /tweak, and /start "
        "together so the three-way boundary is legible (#202 AC-1)."
    )
    assert re.search(r"confirmed-small", text) and re.search(
        r"unconfirmed", text
    ), (
        "process/harness.md must state the three-way boundary explicitly — "
        "capture the confirmed-small (/bug, /tweak) vs decide the unconfirmed "
        "(/propose) vs pick up the filed (/start) — not leave it implicit "
        "(#202 AC-1, defending against a steward lean/MECE finding)."
    )


# --- AC-2: the mirrors stay byte-identical (generic guard already exists in
#     test_routine_commands.py::test_process_doc_mirrors_byte_identical; these
#     two just confirm the new content actually reached the mirrors) ----------


def test_mirrors_carry_the_same_bug_tweak_wiring() -> None:
    canonical = PROCESS_DOC.read_text()
    for mirror in MIRRORS:
        assert mirror.read_text() == canonical, (
            f"{mirror.relative_to(REPO_ROOT)} must be byte-identical to "
            "process/harness.md, including the new /bug /tweak wiring "
            "(#202 AC-2)."
        )


# --- AC-3: spec-driven-development / spec-authoring name the on-ramp ---------


def test_spec_driven_development_names_the_capture_on_ramp() -> None:
    text = SPEC_DRIVEN.read_text()
    assert "/bug" in text and "/tweak" in text, (
        "spec-driven-development must name the /bug / /tweak capture on-ramp "
        "where change specs are introduced (#202 AC-3)."
    )
    assert "templates/adjustment.md" in text, (
        "spec-driven-development must name templates/adjustment.md as the "
        "capture form /bug and /tweak file (#202 AC-3)."
    )


def test_spec_authoring_names_the_capture_on_ramp() -> None:
    text = SPEC_AUTHORING.read_text()
    assert "/bug" in text and "/tweak" in text, (
        "spec-authoring must name the /bug / /tweak capture on-ramp in its "
        "Change spec section (#202 AC-3)."
    )
    assert "templates/adjustment.md" in text, (
        "spec-authoring must name templates/adjustment.md as the capture form "
        "/bug and /tweak file, ahead of the full change-spec form (#202 AC-3)."
    )


# --- AC-4: header versions match registry.yaml, registry self-version synced -


def test_process_harness_header_matches_registry() -> None:
    header = re.search(r"guidance:process-harness@([\d.]+)", PROCESS_DOC.read_text())
    assert header, "process/harness.md must carry a guidance:process-harness@x.y.z header."
    entry = _registry_entry("process/harness.md")
    registry_version = re.search(r"version:\s*([\d.]+)", entry).group(1)
    assert header.group(1) == registry_version, (
        f"process/harness.md header {header.group(1)!r} must match "
        f"registry.yaml's {registry_version!r} (#202 AC-4)."
    )


def test_spec_driven_development_header_matches_registry() -> None:
    header = re.search(
        r"guidance:spec-driven-development@([\d.]+)", SPEC_DRIVEN.read_text()
    )
    assert header, "spec-driven-development must carry its guidance: header."
    entry = _registry_entry("skills/spec-driven-development/SKILL.md")
    registry_version = re.search(r"version:\s*([\d.]+)", entry).group(1)
    assert header.group(1) == registry_version, (
        f"spec-driven-development header {header.group(1)!r} must match "
        f"registry.yaml's {registry_version!r} (#202 AC-4)."
    )


def test_spec_authoring_header_matches_registry() -> None:
    header = re.search(r"guidance:spec-authoring@([\d.]+)", SPEC_AUTHORING.read_text())
    assert header, "spec-authoring must carry its guidance: header."
    entry = _registry_entry("skills/spec-authoring/SKILL.md")
    registry_version = re.search(r"version:\s*([\d.]+)", entry).group(1)
    assert header.group(1) == registry_version, (
        f"spec-authoring header {header.group(1)!r} must match "
        f"registry.yaml's {registry_version!r} (#202 AC-4)."
    )


def test_registry_self_version_header_matches_meta_entry() -> None:
    """registry.yaml itself changes in this ticket (three files' entries move),
    so its own header and `meta:` self-entry must be bumped together — the
    three-place self-version trap hit at ticks #94/#95/#96 (registry.yaml IS
    the file whose header + files:/meta: entries can drift independently)."""
    text = REGISTRY.read_text()
    header = re.search(r"#\s*guidance:registry@([\d.]+)", text)
    assert header, "registry.yaml must carry its own `# guidance:registry@x.y.z` header."
    meta_entry = re.search(r"registry\.yaml:\s*\{[^}]*\}", text)
    assert meta_entry, "registry.yaml's meta: block must list its own self-entry."
    meta_version = re.search(r"version:\s*([\d.]+)", meta_entry.group(0)).group(1)
    assert header.group(1) == meta_version, (
        f"registry.yaml header {header.group(1)!r} must match its own meta: "
        f"self-entry {meta_version!r} (#202 AC-4)."
    )
