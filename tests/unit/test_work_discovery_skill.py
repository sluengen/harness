"""CAL-907 — work-discovery skill + scheduled-task de-drift + drift guard.

*Source:* ``specs/proposals/harden-loop-layer.md`` (WS2, B1 + B2); CAL-907.
Origin: the *Loop Engineering* field study, §VI (Manual/Blind loops).

The routine pick/discovery *logic* — how to read the queue and judge what is
actionable — lived as inline prose in ``commands/harness.md`` step 1, and the
operator's actual local scheduled tasks (``~/.claude/scheduled-tasks/
harness-work-pull`` / ``harness-code-assess``) had drifted: they still carried
pre-reclamation logic and said "use /build" instead of invoking the versioned
``/harness routine build`` / ``quality``. The logic that *ran* had diverged from
the logic that was *versioned* — a direct violation of the repo's own principle,
*version the logic, not the schedule*.

WS2 closes this three ways (proposal D2 → **B1 + B2**):

* **B2 — extract a** ``work-discovery`` **skill** that owns the discovery
  knowledge (what to read, how to judge actionable). Justified *here* — not the
  over-engineering "shrink" anti-pattern — because the harness is distributed
  guidance other repos self-host, so the skill has a real second consumer: every
  self-hosting repo's routine. The routine *invokes* the skill; the criteria are
  single-homed there, not duplicated in command prose.
* **B1 — de-drift the triggers** with a runbook (``RUNBOOK.md``) documenting how
  to re-sync the user-local scheduled tasks into thin callers of the versioned
  routine. The task files live outside the repo, so the fix is operational.
* **drift guard** — this module: it fails if the discovery-logic *signature*
  (the selection-criteria triad) is inlined into a trigger/caller surface (the
  routine command or the runbook's trigger spec) instead of living solely in the
  ``work-discovery`` skill and being *invoked* from those surfaces.

Acceptance criteria (CAL-907):

* **AC-1** — a ``work-discovery`` skill exists and the routine invokes it; pick
  logic is single-homed there, not duplicated in command prose. Proven by
  :func:`test_work_discovery_skill_present`,
  :func:`test_work_discovery_skill_registered`,
  :func:`test_work_discovery_skill_owns_pick_criteria`,
  :func:`test_build_routine_invokes_work_discovery_skill`, and the single-home
  drift guard :func:`test_pick_criteria_not_inlined_into_command`.
* **AC-2** — a runbook documents re-syncing the local scheduled tasks to call
  the versioned routine. Proven by
  :func:`test_runbook_documents_trigger_resync`.
* **AC-3** — a guard test fails when discovery logic is inlined into a trigger
  rather than invoked from the versioned surface. Proven by
  :func:`test_pick_criteria_not_inlined_into_command`,
  :func:`test_runbook_triggers_are_thin_callers`, and the detector-boundary pins
  :func:`test_inlines_detector_flags_the_full_triad` /
  :func:`test_inlines_detector_ignores_a_lone_token`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SKILL = REPO_ROOT / "skills" / "work-discovery" / "SKILL.md"
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness" / "routine-build.md"
RUNBOOK = REPO_ROOT / "RUNBOOK.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def _section(text: str, heading_substr: str) -> str:
    """The body of the heading line containing ``heading_substr`` up to the next
    heading of the same-or-higher level (mirrors ``test_routine_commands``)."""
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
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        body.append(line)
    return "\n".join(body)


#: The selection-criteria *triad* that constitutes "discovery logic": ranking by
#: dependencies, ranking by priority, and skipping the ``decision``-labelled
#: not-yet-actionable tickets. A surface that states all three is *encoding* the
#: pick logic; a surface that merely mentions one (e.g. the command's control
#: flow still *labels* a blocked ticket ``decision``) is not. Requiring the full
#: co-occurrence is what keeps the drift guard from false-positiving on an
#: incidental single-token mention.
_TRIAD = ("dependencies", "priority", "decision")


def _inlines_discovery(text: str) -> bool:
    """True iff *text* inlines the discovery-logic signature (the full triad)."""
    low = text.lower()
    return all(token in low for token in _TRIAD)


# --- detector boundary (keeps the drift guard honest / non-vacuous) -----------


def test_inlines_detector_flags_the_full_triad() -> None:
    """The detector fires when all three selection criteria co-occur."""
    assert _inlines_discovery(
        "rank by dependencies, then priority; skip decision-labelled tickets"
    )


def test_inlines_detector_ignores_a_lone_token() -> None:
    """The detector does not fire on an incidental single-criterion mention —
    e.g. a caller that merely labels a blocked ticket ``decision`` in its control
    flow without re-stating the whole pick algorithm."""
    assert not _inlines_discovery("comment on the ticket and label it `decision`")
    assert not _inlines_discovery("take the highest-priority item off the queue")


# --- AC-1: the skill exists, is registered, and owns the pick criteria --------


def test_work_discovery_skill_present() -> None:
    """AC-1: ``skills/work-discovery/SKILL.md`` exists with Agent-Skills
    frontmatter (``name`` / ``description``) and a ``guidance:`` version header."""
    assert SKILL.exists(), (
        "skills/work-discovery/SKILL.md must exist — the home of the routine "
        "pick/discovery logic (CAL-907 AC-1)."
    )
    text = SKILL.read_text()
    assert re.search(r"^name:\s*work-discovery\s*$", text, re.MULTILINE), (
        "the skill must declare `name: work-discovery` in its frontmatter."
    )
    assert re.search(r"^description:\s*\S", text, re.MULTILINE), (
        "the skill must declare a `description:` in its frontmatter."
    )
    assert re.search(r"guidance:work-discovery@[\d.]+", text), (
        "the skill must carry a `guidance:work-discovery@x.y.z` version header."
    )


def test_work_discovery_skill_registered() -> None:
    """AC-1: the skill is a registered distributed surface unit — listed in
    ``registry.yaml`` ``files:`` under the ``harness`` profile, in the
    Agent-Skills ``skills/<id>/SKILL.md`` shape."""
    reg = REGISTRY.read_text()
    entry = re.search(
        r"skills/work-discovery/SKILL\.md:\s*\{[^}]*id:\s*work-discovery[^}]*\}",
        reg,
    )
    assert entry, (
        "registry.yaml files: must list skills/work-discovery/SKILL.md with "
        "id: work-discovery (CAL-907 AC-1) — the footprint/parity guards require "
        "every surface file to be registered."
    )
    assert "harness" in entry.group(0), (
        "the work-discovery skill entry must be in the `harness` profile."
    )


def test_work_discovery_skill_owns_pick_criteria() -> None:
    """AC-1: the skill is the single home of the discovery *knowledge* — it
    enumerates the selection criteria (ID/number ordering, dependencies,
    priority, the ``decision``-label skip) and the actionability judgment."""
    text = SKILL.read_text()
    assert _inlines_discovery(text), (
        "the work-discovery skill must own the full selection-criteria triad "
        "(dependencies, priority, decision-label skip) — it is the home of the "
        "pick logic (CAL-907 AC-1)."
    )
    assert re.search(r"\bID\b|identifier|number", text), (
        "the skill must document ordering by the ticket ID/number (CAL-907 AC-1)."
    )
    assert re.search(r"actionab", text, re.IGNORECASE), (
        "the skill must document how to judge a ticket wholly actionable "
        "(CAL-907 AC-1)."
    )


def test_build_routine_invokes_work_discovery_skill() -> None:
    """AC-1: the Build routine *invokes* the skill by name rather than owning the
    logic — it delegates the pick to ``work-discovery``."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    assert "work-discovery" in body, (
        "the Build routine must invoke the `work-discovery` skill for its pick "
        "step instead of inlining the discovery logic (CAL-907 AC-1)."
    )
    # It must still retain the pick step itself (the invocation point).
    assert "pick the next ticket" in body.lower(), (
        "the Build routine must retain its pick step as the skill's invocation "
        "point (CAL-907 AC-1)."
    )


# --- AC-3: single-home drift guard — no inlined logic in the caller surfaces --


def test_pick_criteria_not_inlined_into_command() -> None:
    """AC-3 (core): the selection criteria are NOT duplicated into the routine
    command. The command is a *caller* of the versioned surface — if a future
    edit re-inlines the pick algorithm (the triad) into the Build routine section
    instead of invoking the skill, this guard fails."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    assert not _inlines_discovery(body), (
        "the Build routine section inlines the discovery-logic triad "
        "(dependencies + priority + decision) instead of invoking the "
        "`work-discovery` skill — the pick logic must be single-homed in the "
        "skill, not duplicated in command prose (CAL-907 AC-3)."
    )


# --- AC-2: the runbook documents the scheduled-task re-sync --------------------


# --- CAL-1108: a refused write is a config gap, not a bug in this skill -------


def test_work_discovery_still_instructs_the_deferral_write() -> None:
    """CAL-1108 (the regression guard proper): the deferral step must keep
    instructing the tracker write — a comment naming what the ticket needs, and
    the ``decision`` label.

    This is pinned because it was once removed. A CAL-1087 build rewrote the step
    to "surface it in the run's report" on the premise that an unattended runner
    cannot write to a tracker; the premise was false (the refusal names writes
    *the task file requests* — a **configuration** gap), and the rewrite would
    have shipped, auto-pulling, to every consuming repo whose posture already
    permits the write, telling a capable runner to go quiet. Reverted whole; this
    guard is what makes the reversion stick."""
    body = _section(SKILL.read_text(), "Actionability")
    assert "comment" in body.lower(), (
        "work-discovery's deferral step must still instruct a comment naming "
        "what the ticket needs. If a refusal prompted its removal, fix the "
        "posture instead — the write is sanctioned in settings, not disowned "
        "here (CAL-1108)."
    )
    assert "`decision`" in body, (
        "work-discovery's deferral step must still instruct the `decision` "
        "label — it is what removes the ticket from the next tick's candidate "
        "set (CAL-1108)."
    )


def test_work_discovery_names_the_posture_lever() -> None:
    """CAL-1108: the skill must name the lever, so an agent whose write is
    refused fixes the configuration rather than concluding this skill is wrong.

    Without this, the refusal reads as a guidance bug — and the agent's next move
    is to hand-edit its *installed* guidance, which the process doc forbids, or
    to file an upstream ticket against a step that was never broken. It has gone
    that way twice."""
    text = SKILL.read_text()
    assert "autoMode" in text, (
        "work-discovery must name `autoMode.allow` — the natural-language "
        "allowlist that sanctions an unattended run's writes — as the lever to "
        "reach for when a write is refused (CAL-1108)."
    )
    assert "settings/" in text, (
        "work-discovery must name where the posture lives (the profile's "
        "settings file), not merely that one exists (CAL-1108)."
    )
    assert re.search(r"configuration|posture", text, re.IGNORECASE), (
        "work-discovery must state the direction of the fix: a refused write is "
        "a configuration gap, so change the posture, not this skill (CAL-1108)."
    )


# --- CAL-1166: skip rule keyed on assignment; deferral assigns the operator ---


def test_held_tickets_section_keys_on_assignment() -> None:
    """CAL-1166 AC-1: the skip rule names a ticket **assigned to a human** as the
    *primary* held signal (any state), with the transitional ``decision`` /
    ``operator`` label OR that keeps existing deferred tickets safe until the
    queue backfill assigns them. This replaces the label-only "The ``decision``
    label" skip section — assignment is the machine-readable human-hold signal,
    the label is the human-readable explanation of *why*."""
    text = SKILL.read_text()
    section = _section(text, "Held")
    assert section, (
        "the skill must carry a 'Held tickets' section naming what the loop "
        "skips — it replaces the label-only skip section (CAL-1166 AC-1)."
    )
    low = section.lower()
    assert "assign" in low, (
        "the held section must name a ticket assigned to a human as the skip "
        "signal (CAL-1166 AC-1)."
    )
    assert "primary" in low, (
        "the held section must name assignment as the *primary* signal, the "
        "label OR as transitional (CAL-1166 AC-1)."
    )
    assert "`operator`" in section and "`decision`" in section, (
        "the held section must name the transitional `decision`/`operator` label "
        "OR — the fallback until the queue backfill assigns held tickets "
        "(CAL-1166 AC-1)."
    )


def test_deferral_instruction_assigns_the_operator() -> None:
    """CAL-1166 AC-2: the deferral step assigns the ticket to the operator — in
    addition to the comment and label — because assignment is the signal the
    held-tickets skip rule now reads. (The `defer` *verb* performing the
    assignment write, and its `autoMode.allow` clause, are CAL-1167's scope; this
    skill instructs it, and the transitional OR covers the gap in between.)"""
    body = _section(SKILL.read_text(), "Actionability")
    low = body.lower()
    assert "assign" in low, (
        "the deferral step must assign the held ticket to the operator "
        "(CAL-1166 AC-2)."
    )
    assert "operator" in low, (
        "the deferral must name the operator as the assignee — the human who "
        "then holds the ticket (CAL-1166 AC-2)."
    )


def test_work_discovery_version_is_0_8_0() -> None:
    """Bumped by ADR 0015 for the hold-label consolidation; the registry row agrees."""
    text = SKILL.read_text()
    assert "guidance:work-discovery@0.8.0" in text, (
        "the skill stamp must be work-discovery@0.8.0 (ADR 0015 — hold labels)."
    )
    reg = REGISTRY.read_text()
    assert re.search(
        r"skills/work-discovery/SKILL\.md:\s*\{[^}]*version:\s*0\.8\.0[^}]*\}", reg
    ), "the registry files: row for work-discovery must be version 0.8.0 (ADR 0015)."


# --- ADR 0006 / #191: the third hold kind, `input` --------------------------


def test_work_discovery_names_three_hold_kinds() -> None:
    """ADR 0006 (#191): the skill names all three hold kinds — `decision`,
    `input`, `operator` — partitioning held work by what kind of human input a
    ticket waits on, and states that the loop skips all three (the outbound
    hold semantics are unchanged; only the return path distinguishes them)."""
    text = SKILL.read_text()
    assert "`decision`" in text and "`input`" in text and "`operator`" in text, (
        "the skill must name all three hold kinds — decision, input, operator "
        "(ADR 0006, #191)."
    )
    assert re.search(r"skips? all three", text, re.IGNORECASE), (
        "the skill must state that the loop skips all three hold kinds — the "
        "outbound skip semantics are unchanged by adding a kind (ADR 0006, #191)."
    )


def test_work_discovery_states_operator_label_narrowed_meaning() -> None:
    """ADR 0006 (#191): the skill states that `operator`'s meaning narrows to an
    interactive session only — it no longer also covers "the operator owes this
    ticket something" now that `input` exists for that case."""
    text = SKILL.read_text()
    assert re.search(r"narrow", text, re.IGNORECASE), (
        "the skill must state that the `operator` label's meaning narrows now "
        "that `input` exists as its own kind (ADR 0006, #191)."
    )


# --- #192: the return path — when a held ticket is clearable + released ------


def test_return_path_section_present() -> None:
    """#192: the skill states the return-path test — the inverse of the
    deferral test — so `/decision` (#193) delegates the judgment here instead
    of restating it."""
    section = _section(SKILL.read_text(), "Return path")
    assert section, (
        "the skill must carry a return-path section naming when a held ticket "
        "is clearable and what releasing it means (#192)."
    )


def test_return_path_defines_clearable() -> None:
    """#192: a held ticket is clearable when the only thing missing is input
    the operator has now supplied — for a `decision` hold, an answer that
    makes the acceptance criteria checkable."""
    section = _section(SKILL.read_text(), "Return path")
    low = section.lower()
    assert "clearable" in low, "the section must define 'clearable' (#192)."
    assert "acceptance criteria" in low, (
        "clearable must be tied to the acceptance criteria becoming checkable "
        "(#192)."
    )


def test_return_path_defines_released_three_steps() -> None:
    """#192: released means all three of: the resolution written into the
    change spec, the hold label removed, and the operator unassigned — with
    the unassignment called out as load-bearing."""
    section = _section(SKILL.read_text(), "Return path")
    low = section.lower()
    assert "released" in low, "the section must define 'released' (#192)."
    assert "change spec" in low, (
        "released must require the resolution written into the change spec, "
        "not left only in a comment thread (#192)."
    )
    assert "label removed" in low, (
        "released must require the hold label removed (#192)."
    )
    assert "unassign" in low, "released must require the operator unassigned (#192)."
    assert "load-bearing" in low, (
        "the unassignment must be called out as load-bearing — a sweep that "
        "records an answer without unassigning leaves the ticket held forever "
        "(#192)."
    )


def test_return_path_covers_re_defer_case() -> None:
    """#192: a ticket released but still not wholly actionable is re-deferred,
    not left half-cleared."""
    section = _section(SKILL.read_text(), "Return path")
    assert re.search(r"re-?defer", section, re.IGNORECASE), (
        "the section must cover the re-defer case — a ticket released but "
        "still not actionable goes back through deferral, not left "
        "half-cleared (#192)."
    )
