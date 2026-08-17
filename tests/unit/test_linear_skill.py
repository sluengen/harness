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
  not copied). Registry/header version parity is covered generically by
  ``tests/unit/test_guidance_source.py::test_surface_headers_match_registry``.
* **AC-2** — the skill leads with **type-based runtime state resolution**: resolve a
  state by its stable ``type`` enum (``unstarted`` / ``started`` / ``completed`` /
  ``canceled``), the two ``started`` states (In Progress / In Review) disambiguated
  **by name**; CONTEXT-cached UUIDs are demoted to an override-only exception.
* **AC-3** — **no command embeds raw Linear GraphQL** (``api.linear.app``). A
  documented, *shrinking* allowlist carries the pre-existing embeds (``build.md`` →
  CAL-715); an allowlisted
  file that no longer embeds GraphQL fails the guard, forcing the list toward the
  absolute invariant (no silent caps — ``code-quality`` Part C).
* **AC-4** — every **live** surface reference to the old ``linear-sync`` id is
  updated to ``linear``. Only the historical record (``assessments/``) and
  regression guards (``tests/``) keep the old id.

**What this module asserts (#459).** Identity and negative space, plus three
anchored tripwires.

*Unchanged* — the rename identity (path, ``name:`` frontmatter, header id, the
old directory gone), the ``api.linear.app`` embed sweep, the live-reference
sweep with its documented fold exemption, the ``issueCreate`` recipe fields,
and the two absence assertions (``"then cache them in `CONTEXT.md`"``,
``"**Blocked → Backlog with the question.**"``).

*Three tripwires, one per rule-home* — Linear's state-resolution section, the
tracker skill's ``## Filing and placement`` section, and the tracker skill's
deliberate-linking sync rule. The six term co-occurrences they replace read
the whole of two skill files: none was anchored, and none read a direction, so
each stayed green on prose that named every term while stating the opposite
(``craft.md`` → *Mutate the rule into its opposite, not only out of
existence*; ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*; ADR 0016).

*One guard retired.* ``test_embed_allowlist_shrinks`` iterated
``EMBED_ALLOWLIST``, which reached ``{}`` when the last embed was cleaned. An
empty loop cannot fail, so it read as a live forcing function while measuring
nothing (``craft.md`` → *The empty subject set*). The absolute invariant it
was driving toward is now the whole of ``test_no_command_embeds_linear_graphql``.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT

LINEAR_SKILL = REPO_ROOT / "skills" / "linear" / "SKILL.md"
#: #327 split the backend-neutral policy out of this skill into `tracker`. The
#: rules below (CAL-910, CAL-1165) are unchanged — they are pinned against the
#: file that now owns them, which is where a consumer will read them.
TRACKER_SKILL = REPO_ROOT / "skills" / "tracker" / "SKILL.md"
OLD_SKILL_DIR = REPO_ROOT / "skills" / "linear-sync"
COMMANDS_DIR = REPO_ROOT / "commands"

_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of this module's #459
    mutation table surfaced exactly that: an inverted clause survived on a
    negation belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


def _units(block: str) -> list[str]:
    """Sentences, **with markdown table rows carved out as units of their own**.

    A table row carries no sentence terminator, so a naive sentence split
    glues a whole table into one unit — wide enough that a negation in any
    cell satisfies a binding meant for another. The tracker skill's filing
    rules live half in a table and half in prose, so the unit boundary is part
    of the predicate here (``craft.md`` → *The text unit is part of the
    predicate*).
    """
    units: list[str] = []
    buffer: list[str] = []
    for line in block.splitlines():
        if line.lstrip().startswith("|"):
            if buffer:
                units.extend(_sentences("\n".join(buffer)))
                buffer = []
            units.append(" ".join(line.split()))
        else:
            buffer.append(line)
    if buffer:
        units.extend(_sentences("\n".join(buffer)))
    return units


def _section(path: Path, heading: str) -> str:
    """The body of the heading line *starting with* ``heading``, up to the next
    heading of the same-or-higher level.

    Anchored on the heading text rather than a line offset, so a correct
    insertion elsewhere in the file cannot move the window (``craft.md`` → *An
    ordinal reference into an enumeration is invalidated by a correct
    insertion*).
    """
    lines = path.read_text().splitlines()
    start = next(
        (
            i
            for i, line in enumerate(lines)
            if line.startswith("#") and line.lstrip("# ").startswith(heading)
        ),
        None,
    )
    assert start is not None, f"{path.name} must carry a heading '{heading}'."
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        body.append(line)
    return "\n".join(body)


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


def test_state_resolution_section_defaults_to_the_type_enum() -> None:
    """Tripwire — the state-resolution section resolves by ``type``, and demotes
    the cached-UUID path to an override.

    Terms: the four ``type`` enum values (the portable resolution), the two
    ``started`` state names (what has to be disambiguated), and ``override``
    (what a cached UUID becomes). Polarity: the sentence naming the override
    carries a negation — it is the exception, *not* the default. That is the
    rule CAL-714 shipped, and it is exactly what a term co-occurrence cannot
    see: the pre-change skill, which told consumers to cache the UUIDs as
    mandatory setup, named every term above.
    """
    section = _section(LINEAR_SKILL, "Resolving states by type")
    missing = [t for t in TYPE_ENUM if t not in section]
    assert not missing, (
        "the state-resolution section must document resolving a state by the "
        f"stable `type` enum; missing values: {missing} (CAL-714 AC-2)."
    )
    assert "In Progress" in section and "In Review" in section, (
        "the section must disambiguate the two `started` states (In Progress / "
        "In Review) by name (CAL-714 AC-2)."
    )
    override = [s for s in _sentences(section) if "override" in s.lower()]
    assert override, (
        "the section must frame a CONTEXT-cached state UUID as an override "
        "(CAL-714 AC-2)."
    )
    assert any(_NEGATION.search(s) for s in override), (
        "the override clause must carry its negation — cached UUIDs are the "
        "exception, not the default. Without it this guard is green on the "
        "pre-change skill that made caching mandatory setup (CAL-714 AC-2)."
    )


def test_skill_no_longer_instructs_caching_state_uuids() -> None:
    """Negative space — the retired mandatory-caching instruction is gone (AC-2)."""
    assert "then cache them in `CONTEXT.md`" not in LINEAR_SKILL.read_text(), (
        "the skill still tells consumers to cache state UUIDs in CONTEXT.md as a "
        "mandatory step — type-based resolution is the default now (CAL-714 AC-2)."
    )


# --- AC-3: no command embeds raw Linear GraphQL -------------------------------

#: Commands that still embed ``api.linear.app``, each with its cleanup disposition.
#: This list only ever shrinks, and it has reached empty — the invariant. build.md
#: was cleaned by CAL-715 (thin delegating driver) and harness.md by CAL-731
#: (ingest references the linear skill).
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


# --- AC-4: live references updated to the new `linear` id ---------------------

#: Live surface directories that must reference the skill by its new ``linear`` id.
_LIVE_DIRS = ("skills", "commands", "agents", "templates", "process", "specs")
#: Live root files in the same boat (historical assessments/ excluded).
#: ``SPEC.md`` sat here until #435 deleted it with the design it described;
#: ``CONTEXT.md`` takes its place as the repo's own live root record.
_LIVE_ROOT_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "BOOTSTRAP.md",
    "CONTEXT.md",
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

    Historical records (``assessments/``) and regression guards (``tests/``)
    legitimately keep the old id and are excluded by construction. The
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


def _deliberate_linking_rule() -> str:
    """The tracker skill's sync rule about a merged PR auto-transitioning.

    Anchored on the sync-rules section and then on the *content* of the numbered
    item — not on its ordinal — because a correct insertion renumbers the list
    (``craft.md`` → *An ordinal reference into an enumeration is invalidated by
    a correct insertion*).
    """
    section = _section(TRACKER_SKILL, "Sync rules")
    items = re.split(r"^\d+\.\s+", section, flags=re.MULTILINE)
    matching = [item for item in items if re.search(r"auto-?transition", item, re.I)]
    assert matching, (
        "the tracker skill's Sync rules must carry a numbered rule about a "
        "merged PR auto-transitioning the tickets it names (CAL-910)."
    )
    return " ".join(" ".join(matching).split())


def test_sync_rules_state_the_deliberate_linking_rule() -> None:
    """Tripwire — the sync rule names the trap and the surfaces it fires through.

    Terms the rule cannot be stated without: ``merged`` and ``auto-transition``
    (the integration behaviour), ``spawn`` and ``complete`` (the distinction the
    rule turns on), plus at least three of the four linking surfaces
    (``branch`` / ``title`` / ``body`` / ``commit``) a spawn-PR must keep ids out
    of.

    **This rule has no negation to bind to, and none is faked here.** It is
    stated as a restriction — *put an id in those surfaces only when the PR
    completes that ticket* — so the direction is carried by ``only`` and by the
    spawn/complete pair rather than by ``never``/``not``. Asserting a loose
    negation token over the item would be decoration (ADR 0016: where a rule
    genuinely has no polarity, say so rather than fake one). Whether the rule
    still points the right way is the review gate's.
    """
    rule = _deliberate_linking_rule().lower()
    for term in ("merge", "auto", "spawn", "complete"):
        assert term in rule, (
            "the tracker sync rule must state the deliberate-linking rule in "
            f"terms of {term!r} (CAL-910)."
        )
    surfaces = ("branch", "title", "body", "commit")
    present = [s for s in surfaces if s in rule]
    assert len(present) >= 3, (
        "the sync rule must name the PR surfaces that link an id to a PR — at "
        f"least three of branch / title / body / commit; found {present} (CAL-910)."
    )


# --- CAL-1165: codify the ticket protocol (placement, project, assignment) ----
# Source: accepted proposal `specs/proposals/ticket-protocol-hygiene.md` (2026-07-18,
# decision 1A + 2A + 3A). The `linear` skill defined only the pull side of
# Todo/Backlog; these guards pin the filing side, the assignment skip signal, the
# mandatory project on create, and the `operator` label.


def test_tracker_drops_the_retired_blocked_to_backlog_rule() -> None:
    """Negative space — the superseded sync rule is gone (CAL-1165 AC-1)."""
    assert "**Blocked → Backlog with the question.**" not in TRACKER_SKILL.read_text(), (
        "the old 'Blocked → Backlog with the question' sync rule must be replaced "
        "by the stay-in-Todo-assigned+labelled rule (CAL-1165 AC-1)."
    )


def test_filing_and_placement_section_states_the_ticket_protocol() -> None:
    """Tripwire — one section owns placement, the hold labels and the skip rule.

    Terms the protocol cannot be stated without: ``todo`` and ``backlog`` (the
    two filing destinations), ``input`` and ``operator`` (the two hold labels),
    and ``assign`` (the machine-readable hold signal). Polarity: a unit naming
    the unattended loop's pick carries a negation — it **never** picks a
    human-assigned ticket, in any state. That is the load-bearing direction of
    the whole section, and the three functions this replaces read it nowhere:
    every one of them was a whole-file word co-occurrence that stayed green on
    an inverted skip rule (CAL-1165 AC-1/AC-3/AC-4).
    """
    section = _section(TRACKER_SKILL, "Filing and placement")
    lowered = section.lower()
    for term in ("todo", "backlog", "input", "operator", "assign"):
        assert term in lowered, (
            "the tracker skill's Filing and placement section must state the "
            f"ticket protocol in terms of {term!r} (CAL-1165)."
        )
    picking = [s for s in _units(lowered) if "pick" in s]
    assert picking, (
        "the section must say what the unattended loop picks (CAL-1165 AC-3)."
    )
    assert any(_NEGATION.search(s) for s in picking), (
        "the skip rule must carry its negation inside the section — the loop "
        "never picks a ticket assigned to a human, in any state. Term "
        "co-occurrence reads the same green on the inverted rule (CAL-1165 AC-3)."
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


