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

Both are sections of ``commands/harness.md`` (alongside ``/harness run`` and
``/harness ingest``). That file became a **distributed surface unit** in CAL-764
— a ``registry.yaml`` ``files:`` entry under the ``harness`` profile carrying a
single ``guidance:harness@…`` header (``test_harness_command_distributed.py``) —
so the routine commands now ship into a consuming repo *with it* and need no
per-command ``guidance:`` header of their own (the file's one header covers them)
and no separate registry entry. The loop logic is *also* recorded through the
registered process doc that documents them — ``process/harness.md`` (and its
byte-identical ``AGENTS.md`` / ``CLAUDE.md`` / ``GEMINI.md`` mirrors) — whose
namespacing section lists the commands.

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
    """AC-3 boundary: the routine commands ride inside ``commands/harness.md`` as
    *sections* and gain no ``registry.yaml`` ``files:`` entry of their own.
    ``commands/harness.md`` is itself one registered surface unit since CAL-764
    (``test_harness_command_distributed.py``); the routines are documented inside
    that single file, not as separate distributable command files, so no
    ``routine``-keyed entry should appear in the copy-list."""
    offenders = [
        k
        for k in _registry_file_keys()
        if "routine" in posixpath.normpath(k)
    ]
    assert not offenders, (
        f"{offenders!r} add a separate routine command to registry.yaml's files: "
        "block — the routine commands are sections of commands/harness.md (one "
        "registered surface unit), not standalone distributable files, so they "
        "must not gain their own registry entry (CAL-705 AC-3; CAL-764)."
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


# --- CAL-737: the Build routine runs a reclaim pre-flight before picking work
#
# A run that dies mid-flight (a session that hits a usage/session limit just
# stops) leaves its ticket stranded **In Progress**; a fresh hourly Build run
# can observe nothing about the dead predecessor, so the queue wedges until a
# human intervenes. CAL-736 shipped the Linear-keyed ``harness reclaim --stale``
# sweep; CAL-737 (breakdown item 4 of ``specs/proposals/stale-run-reclamation``)
# wires it in as **step 0** of the Build routine — run before the pick step so
# each tick unblocks the queue first. These guards pin that wiring.


def test_build_routine_runs_reclaim_preflight() -> None:
    """CAL-737 AC-1: the Build routine runs the Linear-keyed
    ``harness reclaim --stale`` sweep (scoped to a ``--project``, default 90m)
    as its pre-flight, before picking work."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    assert "harness reclaim --stale" in body, (
        "the Build routine must run `harness reclaim --stale` as its pre-flight "
        "step 0, before picking the next ticket (CAL-737 AC-1)."
    )
    assert "--project" in body, (
        "the `--stale` sweep is required to be scoped to a project; the Build "
        "routine must pass `--project` (CAL-737 AC-1)."
    )
    assert re.search(r"90\s*(m|min)", body, re.IGNORECASE), (
        "the Build routine must note the default 90-minute staleness threshold "
        "for the reclaim pre-flight (CAL-737 AC-1)."
    )


def test_build_routine_reclaim_runs_first_with_rationale() -> None:
    """CAL-737 AC-2: the reclaim pre-flight is documented BEFORE the pick step,
    with its rationale (unblock the backlog) and its idempotency (safe each tick)."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    reclaim_at = body.find("harness reclaim --stale")
    pick_at = body.lower().find("pick the next ticket")
    assert reclaim_at != -1, (
        "the reclaim pre-flight command must appear in the Build routine "
        "(CAL-737 AC-1)."
    )
    assert pick_at != -1, "the Build routine must retain its pick step."
    assert reclaim_at < pick_at, (
        "the reclaim pre-flight must be documented BEFORE the pick step — it "
        "runs first so the queue is unblocked before work is chosen (CAL-737 AC-2)."
    )
    assert re.search(r"unblock", body, re.IGNORECASE), (
        "the Build routine must document WHY the reclaim runs first — to unblock "
        "the backlog (CAL-737 AC-2)."
    )
    assert re.search(r"idempotent", body, re.IGNORECASE), (
        "the Build routine must document that the reclaim pre-flight is "
        "idempotent / safe to run each tick (CAL-737 AC-2)."
    )


def test_build_routine_fallback_documents_equivalent_preflight() -> None:
    """CAL-737 AC-3: where the harness tool is unavailable (the ``/build``
    fallback), the routine documents the equivalent Linear-keyed pre-flight,
    routed through the ``linear`` skill (no embedded GraphQL — CAL-731)."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    low = body.lower()
    assert "equivalent" in low and "pre-flight" in low, (
        "the Build routine must document the *equivalent* pre-flight for the "
        "`/build` fallback where the harness tool is unavailable (CAL-737 AC-3)."
    )
    assert "`linear` skill" in body, (
        "the fallback pre-flight must route through the `linear` skill rather "
        "than embedding Linear GraphQL (CAL-737 AC-3; CAL-731 invariant)."
    )


# --- CAL-739: the Build pick logic resumes a reclaimed ticket from its WIP branch
#
# Item 6 of ``specs/proposals/stale-run-reclamation`` (D4 preserve/resume): once
# a stranded ticket is back in Todo carrying a checkpoint-pushed WIP branch, the
# next Build run continues from that branch (``harness start --resume``) instead
# of restarting cold — recovering the dead run's work rather than redoing it.
# These guards pin that the pick logic documents the resume path and its clean
# fallback.


def test_build_routine_resumes_reclaimed_ticket_from_preserved_branch() -> None:
    """CAL-739 AC-1: the Build pick logic resumes a `reclaimed` ticket from its
    preserved WIP branch via `harness start --resume`, instead of a clean branch
    off `dev`."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    assert "--resume" in body, (
        "the Build routine must wire `harness start --resume` so a re-picked "
        "`reclaimed` ticket continues from its preserved WIP branch (CAL-739 AC-1)."
    )
    assert "reclaimed" in body.lower(), (
        "the resume wiring must key on the `reclaimed` ticket the reclaim "
        "pre-flight produces (CAL-739 AC-1)."
    )


def test_build_routine_resume_documents_clean_fallback() -> None:
    """CAL-739 AC-2: the routine documents that with no durable WIP, `--resume`
    falls back to a normal clean start."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    low = body.lower()
    assert "fall back" in low or "fallback" in low or "falls back" in low, (
        "the resume wiring must document the clean-restart fallback when no "
        "durable WIP exists (CAL-739 AC-2)."
    )
