"""Routine-command guard — the Build + Quality loop logic is versioned (CAL-705).

The prompts that drive the unattended loops used to live only in the Claude
Code app's scheduled-task config (``~/.claude/scheduled-tasks/harness-work-
pull/SKILL.md``), unversioned and un-uplift-able — against four-loops' own
principle, *version the logic, not the schedule*. CAL-705 (workstream B2 of
``specs/proposals/pre-launch-consolidation.md``) lifts that logic into two
repo-owned, ``/harness``-namespaced commands:

* ``/harness routine build`` — the hourly loop: pull the Linear Todo queue, pick
  the lowest-ID build-actionable ticket, drive it. Primary surface
  ``/harness run``; agent-orchestrated fallback ``/build`` when the harness tool
  is unavailable. On an empty queue it falls through to the quality routine.
* ``/harness routine quality`` — idle → ``/assess code``; weekly →
  ``/assess code --deep``; findings filed back into the Build queue.

Both are sections of the **repo-owned** ``commands/harness.md`` (alongside
``/harness run`` and ``/harness ingest``), which is deliberately excluded from
``registry.yaml`` (``test_harness_command_repo_owned.py``, CAL-650): they drive
the harness's *own* loop, so they are never installed into a consuming repo and
carry no per-command ``guidance:`` header. The change is recorded through the
registered doc that documents them — ``process/harness.md`` (and its byte-
identical ``AGENTS.md`` / ``CLAUDE.md`` / ``GEMINI.md`` mirrors) — whose
namespacing section lists the new commands.

This guard pins that the loop logic is versioned in the repo and carries the
properties the acceptance criteria require.

*Source:* ``specs/proposals/pre-launch-consolidation.md`` (B2); CAL-705.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"
REGISTRY = REPO_ROOT / "registry.yaml"
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
MIRRORS = [REPO_ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")]

#: A registry mapping-entry line, key-first (mirrors the footprint/repo-owned
#: guards). PyYAML is not a declared dependency, so parse with a line regex.
_KEY_RE = re.compile(r"""\s+(?P<q>["']?)(?P<key>[^"'\s:]+)(?P=q)\s*:""")


def _registry_file_keys() -> list[str]:
    text = REGISTRY.read_text()
    start = text.index("\nfiles:")
    end = text.index("\nmeta:", start)
    keys: list[str] = []
    for line in text[start:end].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "files:":
            continue
        m = _KEY_RE.match(line)
        if m:
            keys.append(m.group("key"))
    return keys


def _section(text: str, heading_substr: str) -> str:
    """The body of the heading line that contains ``heading_substr`` up to the
    next heading of the same-or-higher level. Lets a test assert on a single
    routine's body without matching the other routine's text."""
    lines = text.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        if line.startswith("#") and heading_substr in line:
            start = i
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""
    body: list[str] = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            this_level = len(line) - len(line.lstrip("#"))
            if this_level <= level:
                break
        body.append(line)
    return "\n".join(body)


# --- AC-1: both commands exist, each with primary + fallback -----------------


def test_build_routine_command_present() -> None:
    """``/harness routine build`` is a versioned section of ``commands/harness.md``."""
    text = HARNESS_COMMAND.read_text()
    assert re.search(r"^#+ .*/harness routine build", text, re.MULTILINE), (
        "commands/harness.md must carry a `/harness routine build` command "
        "section — the versioned hourly Build loop (CAL-705 AC-1)."
    )


def test_quality_routine_command_present() -> None:
    """``/harness routine quality`` is a versioned section of ``commands/harness.md``."""
    text = HARNESS_COMMAND.read_text()
    assert re.search(r"^#+ .*/harness routine quality", text, re.MULTILINE), (
        "commands/harness.md must carry a `/harness routine quality` command "
        "section — the versioned Quality loop (CAL-705 AC-1)."
    )


def test_build_routine_documents_primary_and_fallback() -> None:
    """AC-1: the Build routine names a harness-tooled primary and an
    agent-orchestrated fallback (the ``/harness run`` vs ``/build`` duality)."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    assert "/harness run" in body, (
        "the Build routine must name `/harness run` as its primary surface "
        "(CAL-705 AC-1)."
    )
    assert "/build" in body, (
        "the Build routine must name `/build` as its agent-orchestrated fallback "
        "(CAL-705 AC-1)."
    )
    assert "primary" in body.lower() and "fallback" in body.lower(), (
        "the Build routine must explicitly mark which surface is the primary and "
        "which is the fallback (CAL-705 AC-1)."
    )


# --- AC-2: the quality routine wires the deep weekly arm ---------------------


def test_quality_routine_wires_deep_assess() -> None:
    """AC-2: the Quality routine runs ``/assess code`` on idle and
    ``/assess code --deep`` for the weekly arm (depends on B1, now shipped)."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine quality")
    assert "/assess code --deep" in body, (
        "the Quality routine must wire `/assess code --deep` for the weekly arm "
        "(CAL-705 AC-2)."
    )
    assert re.search(r"/assess code(?! --deep)", body), (
        "the Quality routine must also wire the plain `/assess code` idle arm "
        "(CAL-705 AC-2)."
    )


# --- AC-3: the process doc + mirrors reference the routines; no registry entry


def test_process_doc_and_mirrors_reference_routines() -> None:
    """AC-3: every distributed process doc (``process/harness.md`` and its
    byte-identical ``AGENTS.md`` / ``CLAUDE.md`` / ``GEMINI.md`` mirrors) lists
    the routine commands in its ``/harness`` namespacing surface."""
    for doc in [PROCESS_DOC, *MIRRORS]:
        text = doc.read_text()
        assert "/harness routine build" in text and "/harness routine quality" in text, (
            f"{doc.relative_to(REPO_ROOT)} must reference `/harness routine "
            "build` and `/harness routine quality` (CAL-705 AC-3)."
        )


def test_process_doc_mirrors_byte_identical() -> None:
    """The three entry-file mirrors stay byte-identical to the process doc — one
    derived process artifact under three names (INSTALLER.md)."""
    canonical = PROCESS_DOC.read_text()
    drifted = [m.relative_to(REPO_ROOT) for m in MIRRORS if m.read_text() != canonical]
    assert not drifted, (
        f"{drifted} drifted from process/harness.md — AGENTS/CLAUDE/GEMINI.md "
        "must be byte-identical copies (INSTALLER.md)."
    )


def test_routine_commands_stay_out_of_registry() -> None:
    """AC-3 boundary: the routine commands ride inside the repo-owned
    ``commands/harness.md`` and gain no ``registry.yaml`` ``files:`` entry — they
    drive the harness's own loop and are never installed into a consuming repo
    (consistent with ``test_harness_command_repo_owned.py``, CAL-650)."""
    offenders = [
        k
        for k in _registry_file_keys()
        if "routine" in posixpath.normpath(k)
    ]
    assert not offenders, (
        f"{offenders!r} add a routine command to registry.yaml's files: block — "
        "the routine commands are repo-owned (they drive the harness's own loop) "
        "and must not be installed into consuming repos (CAL-705 AC-3; CAL-650)."
    )


# --- AC-4: routines are local-trigger only ----------------------------------


def test_routines_documented_local_trigger_only() -> None:
    """AC-4: the routine surface documents that a routine is local-trigger only —
    a cloud routine cannot reach the local ``~/bin/harness`` wrapper."""
    text = HARNESS_COMMAND.read_text()
    # Scope the check to the `## /harness routine` parent section (its preamble
    # holds the shared note and both `### build`/`### quality` subsections) — not
    # the whole file. An unrelated `~/bin/harness` mention elsewhere in
    # commands/harness.md must not let this pass vacuously (reviewer note).
    blob = _section(text, "## /harness routine")
    assert blob, (
        "no `## /harness routine` parent section found in commands/harness.md — "
        "the routine surface must exist to carry the local-trigger note (CAL-705 AC-4)."
    )
    assert re.search(r"local[- ]trigger", blob, re.IGNORECASE), (
        "the `## /harness routine` section must document that routines are "
        "local-trigger only (a cloud routine cannot reach ~/bin/harness) "
        "(CAL-705 AC-4)."
    )
    assert "~/bin/harness" in blob, (
        "the local-trigger note in the `## /harness routine` section must name "
        "the local harness wrapper it cannot reach from the cloud (CAL-705 AC-4)."
    )
