"""CAL-714 — rename ``linear-sync`` → ``linear``; type-based state resolution;
no embedded Linear GraphQL in commands.

Source: ``assessments/2026-06-15-system-and-code.md`` SYSTEM-2 / SYSTEM-INSIGHT-2
(Medium) — the enabling foundation for thinning ``/build`` (CAL-715, the blocked
sibling).

Linear's workflow-state IDs are **per-team UUIDs** — not portable across repos or
trackers — yet the old skill told consumers to *cache the UUIDs in CONTEXT.md* as a
mandatory setup step (``skills/linear-sync/SKILL.md:75``). Commands also re-derived
their own GraphQL instead of referencing the one skill that already holds the
canonical recipes. These guards pin the fix:

* **AC-1** — the skill lives at ``skills/linear/SKILL.md`` with a ``name: linear``
  frontmatter and a ``guidance:linear@<version>`` header (the directory was *moved*,
  not copied). Registry/header/CHANGELOG version parity is covered generically by
  ``tests/unit/test_guidance_source.py::test_surface_headers_match_registry``.
* **AC-2** — the skill leads with **type-based runtime state resolution**: resolve a
  state by its stable ``type`` enum (``unstarted`` / ``started`` / ``completed`` /
  ``canceled``), the two ``started`` states (In Progress / In Review) disambiguated
  **by name**; CONTEXT-cached UUIDs are demoted to an override-only exception.
* **AC-3** — **no command embeds raw Linear GraphQL** (``api.linear.app``). A
  documented, *shrinking* allowlist carries the pre-existing embeds (``build.md`` →
  CAL-715, ``harness.md`` → the repo-owned ``/harness`` ingest flow); an allowlisted
  file that no longer embeds GraphQL fails the guard, forcing the list toward the
  absolute invariant (no silent caps — ``code-quality`` Part C).
* **AC-4** — every **live** surface reference to the old ``linear-sync`` id is
  updated to ``linear``. Only the historical record (``CHANGELOG.md``,
  ``assessments/``) and regression guards (``tests/``) keep the old id.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LINEAR_SKILL = REPO_ROOT / "skills" / "linear" / "SKILL.md"
OLD_SKILL_DIR = REPO_ROOT / "skills" / "linear-sync"
COMMANDS_DIR = REPO_ROOT / "commands"


# --- AC-1: the skill is renamed linear-sync → linear --------------------------


def test_skill_renamed_to_linear() -> None:
    """The skill is at ``skills/linear/SKILL.md`` with name/header ``linear`` (AC-1)."""
    assert LINEAR_SKILL.exists(), (
        "skills/linear/SKILL.md is missing — the skill must be renamed from "
        "linear-sync to linear (CAL-714 AC-1)."
    )
    assert not OLD_SKILL_DIR.exists(), (
        "skills/linear-sync/ still exists — the rename must MOVE the directory to "
        "skills/linear/, not copy it (CAL-714 AC-1)."
    )
    text = LINEAR_SKILL.read_text()
    assert re.search(r"^name:\s*linear\s*$", text, re.MULTILINE), (
        "skills/linear/SKILL.md frontmatter must declare `name: linear` (CAL-714 AC-1)."
    )
    assert re.search(r"<!--\s*guidance:linear@[\d.]+\s*-->", text), (
        "skills/linear/SKILL.md must carry a `guidance:linear@<version>` header "
        "(not linear-sync) (CAL-714 AC-1)."
    )


# --- AC-2: type-based runtime state resolution is the default -----------------

#: Linear's stable, portable workflow-state ``type`` enum.
TYPE_ENUM = ("unstarted", "started", "completed", "canceled")


def test_skill_documents_type_based_resolution() -> None:
    """The skill resolves state by the stable ``type`` enum (AC-2).

    All four enum values must appear, and the two ``started`` states must be named
    so they can be disambiguated at runtime.
    """
    text = LINEAR_SKILL.read_text()
    missing = [t for t in TYPE_ENUM if t not in text]
    assert not missing, (
        "skills/linear/SKILL.md must document resolving a state by the stable "
        f"`type` enum; missing values: {missing} (CAL-714 AC-2)."
    )
    assert "In Progress" in text and "In Review" in text, (
        "the skill must disambiguate the two `started` states (In Progress / In "
        "Review) by name (CAL-714 AC-2)."
    )


def test_skill_demotes_context_uuids_to_override() -> None:
    """CONTEXT-cached UUIDs are an override-only exception, not mandatory setup (AC-2)."""
    text = LINEAR_SKILL.read_text()
    assert "override" in text.lower(), (
        "the skill must frame CONTEXT-cached state UUIDs as an override-only "
        "exception (custom/renamed states), not mandatory setup (CAL-714 AC-2)."
    )
    assert "then cache them in `CONTEXT.md`" not in text, (
        "the skill still tells consumers to cache state UUIDs in CONTEXT.md as a "
        "mandatory step — type-based resolution is the default now (CAL-714 AC-2)."
    )


# --- AC-3: no command embeds raw Linear GraphQL -------------------------------

#: Commands that still embed ``api.linear.app``, each with its cleanup disposition.
#: This list must SHRINK: when a command is cleaned, ``test_embed_allowlist_shrinks``
#: fails until the entry is removed, driving the guard toward the absolute invariant.
#: Now **empty** — the invariant is reached: build.md was cleaned by CAL-715 (thin
#: delegating driver) and harness.md by CAL-731 (ingest references the linear skill).
#: A new embed in any command now fails ``test_no_command_embeds_linear_graphql``
#: outright; there is no documented gap left.
EMBED_ALLOWLIST: dict[str, str] = {}


def _commands_embedding_graphql() -> set[str]:
    """Names of command files that embed a raw Linear GraphQL endpoint."""
    return {
        p.name for p in COMMANDS_DIR.glob("*.md") if "api.linear.app" in p.read_text()
    }


def test_no_command_embeds_linear_graphql() -> None:
    """No command embeds raw Linear GraphQL beyond the documented allowlist (AC-3).

    A command must reference the ``linear`` skill for Linear operations, not
    re-encode ``api.linear.app`` calls — the duplication-drift class SYSTEM-2
    flagged.
    """
    new = _commands_embedding_graphql() - set(EMBED_ALLOWLIST)
    assert not new, (
        f"command(s) {sorted(new)} embed raw Linear GraphQL (api.linear.app). "
        "Reference the `linear` skill instead of re-encoding the API (CAL-714 AC-3)."
    )


def test_embed_allowlist_shrinks() -> None:
    """Every allowlisted command still embeds GraphQL — drop it once cleaned (AC-3).

    The allowlist is a shrinking known-gap list. When CAL-715 thins ``build.md``,
    this fails until ``build.md`` is removed from ``EMBED_ALLOWLIST`` — the forcing
    function that keeps the gap honest.
    """
    stale = {
        name
        for name in EMBED_ALLOWLIST
        if not (COMMANDS_DIR / name).exists()
        or "api.linear.app" not in (COMMANDS_DIR / name).read_text()
    }
    assert not stale, (
        f"allowlisted command(s) {sorted(stale)} no longer embed Linear GraphQL — "
        "remove them from EMBED_ALLOWLIST (CAL-714 AC-3)."
    )


# --- AC-4: live references updated to the new `linear` id ---------------------

#: Live surface directories that must reference the skill by its new ``linear`` id.
_LIVE_DIRS = ("skills", "commands", "agents", "templates", "process", "specs")
#: Live root files in the same boat (historical CHANGELOG.md / assessments/ excluded).
_LIVE_ROOT_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "BOOTSTRAP.md",
    "SPEC.md",
    "README.md",
    "registry.yaml",
)


def _live_surface_files() -> list[Path]:
    files: list[Path] = []
    for d in _LIVE_DIRS:
        files.extend((REPO_ROOT / d).rglob("*.md"))
    for name in _LIVE_ROOT_FILES:
        p = REPO_ROOT / name
        if p.exists():
            files.append(p)
    return files


#: The documented rename form is a *fold reference*, not a live pointer: the
#: Mode-2 migration docs (CAL-750) name ``linear-sync`` -> ``linear`` so a repo
#: migrating off pre-merge guidance recognises the rename. Stripping this exact
#: form leaves any *bare* mention — a genuine live pointer — to still fail.
_ALLOWED_OLD_ID_FOLD = "linear-sync` → `linear"


def test_no_live_reference_to_old_skill_id() -> None:
    """No live surface file points at the old ``linear-sync`` id as a live skill (AC-4).

    Historical records (``CHANGELOG.md``, ``assessments/``) and regression guards
    (``tests/``) legitimately keep the old id and are excluded by construction. The
    documented rename ``linear-sync`` -> ``linear`` in the migration docs (CAL-750)
    is a fold reference, not a live pointer, and is exempt.
    """
    offenders = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in _live_surface_files()
        if "linear-sync" in p.read_text().replace(_ALLOWED_OLD_ID_FOLD, "")
    )
    assert not offenders, (
        f"live surface file(s) still reference the old `linear-sync` id: {offenders}. "
        "Update them to `linear`, or (in a migration doc) use the documented fold "
        "form ``linear-sync` → `linear`` (CAL-714 AC-4; CAL-750)."
    )


# --- CAL-910: externalise the PR-id auto-transition trap ----------------------


def test_skill_warns_pr_id_auto_transition_on_merge() -> None:
    """The skill documents that a merged PR auto-transitions every ticket it names.

    Linear's GitHub integration links an issue when its id appears in the PR
    branch / title / body / commit and moves it to **Done** on merge — even when
    the PR only *spawned* the ticket rather than completing it. A spawn-PR (e.g.
    proposal acceptance listing its breakdown) that names those ids therefore
    falsely closes the tickets it just created. The skill is the single home for
    Linear behaviour, so this trap must live there, not only in session memory
    (CAL-910).
    """
    text = LINEAR_SKILL.read_text().lower()

    # the integration behaviour: id in a PR surface -> auto-Done on merge
    assert "merge" in text and ("auto" in text) and "done" in text, (
        "the linear skill must document that a *merged* PR *auto*-transitions a "
        "linked ticket to *Done* (CAL-910)."
    )
    # the actionable rule turns on whether the PR completes vs only spawns the ticket
    assert "spawn" in text and ("complete" in text), (
        "the linear skill must state the spawn-vs-complete rule: a ticket id goes in "
        "the PR only when the PR completes that ticket; a PR that merely spawns / "
        "references tickets must keep their ids out (CAL-910)."
    )
    # it must name the linking surfaces a spawn-PR has to keep ids out of
    surfaces = ("branch", "title", "body", "commit")
    present = [s for s in surfaces if s in text]
    assert len(present) >= 3, (
        "the linear skill must name the PR surfaces that link an id to a PR — at "
        f"least three of branch / title / body / commit; found {present} (CAL-910)."
    )


# --- CAL-1165: codify the ticket protocol (placement, project, assignment) ----
# Source: accepted proposal `specs/proposals/ticket-protocol-hygiene.md` (2026-07-18,
# decision 1A + 2A + 3A). The `linear` skill defined only the pull side of
# Todo/Backlog; these guards pin the filing side, the assignment skip signal, the
# mandatory project on create, and the `operator` label.


def test_skill_documents_todo_backlog_filing_semantics() -> None:
    """Todo = confirmed work, Backlog = existence-uncertain; blocked-on-detail stays Todo (AC-1)."""
    text = LINEAR_SKILL.read_text()
    low = text.lower()
    assert "confirmed work" in low, (
        "the skill must state Todo receives confirmed work (review follow-ups and "
        "findings file straight there) (CAL-1165 AC-1)."
    )
    assert "existence" in low and "uncertain" in low, (
        "the skill must state Backlog holds existence-uncertain work (CAL-1165 AC-1)."
    )
    assert "stays in todo" in low or "stay in todo" in low, (
        "the skill must replace 'blocked → Backlog' with: a ticket blocked on a "
        "detail of confirmed work stays in Todo, assigned + labelled (CAL-1165 AC-1)."
    )
    assert "**Blocked → Backlog with the question.**" not in text, (
        "the old 'Blocked → Backlog with the question' sync rule must be replaced "
        "by the stay-in-Todo-assigned+labelled rule (CAL-1165 AC-1)."
    )


def test_issue_create_recipe_carries_project_and_assignee() -> None:
    """`issueCreate` sets `projectId`/`assigneeId`; project is mandatory on create (AC-2)."""
    text = LINEAR_SKILL.read_text()
    low = text.lower()
    assert "issueCreate" in text and "projectId" in text, (
        "the `issueCreate` recipe must carry `projectId` — a project-less issue is "
        "invisible to the Build queue (CAL-1165 AC-2)."
    )
    assert "assigneeId" in text, (
        "the `issueCreate` recipe must carry `assigneeId` (assignment is the human-hold "
        "signal) (CAL-1165 AC-2)."
    )
    assert "mandatory" in low and "project" in low, (
        "the skill must state a project is mandatory on every create (CAL-1165 AC-2)."
    )


def test_skill_documents_assignment_protocol() -> None:
    """Assignment is the skip signal; In Review assigned/unassigned disambiguated (AC-3)."""
    low = LINEAR_SKILL.read_text().lower()
    assert "assigned to a human" in low, (
        "the skill must state a ticket assigned to a human is held by that human "
        "(the unattended loop's skip signal) (CAL-1165 AC-3)."
    )
    assert "never pick" in low, (
        "the skill must state the unattended loop never picks a human-assigned "
        "ticket, in any state (CAL-1165 AC-3)."
    )
    assert "in review" in low and "unassigned" in low, (
        "the skill must disambiguate In Review: assigned = human/visual review of a "
        "closed run; unassigned = agent review inside a live run (CAL-1165 AC-3)."
    )


def test_label_table_includes_operator_label() -> None:
    """The label table adds `operator` with the decision/operator distinction (AC-4)."""
    text = LINEAR_SKILL.read_text()
    low = text.lower()
    assert "`operator`" in text, (
        "the label table must include the `operator` label beside `decision` "
        "(CAL-1165 AC-4)."
    )
    assert "interactive" in low, (
        "the skill must define `operator` as needing an interactive/hands-on "
        "session (CAL-1165 AC-4)."
    )
    assert "decision" in low and ("judgment" in low or "judgement" in low), (
        "the skill must define `decision` as needing a judgment call, distinct "
        "from `operator` (CAL-1165 AC-4)."
    )
