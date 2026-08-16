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
* **B1 — de-drift the triggers** by keeping the trigger a thin caller of the
  versioned routine. The scheduled-task files live outside the repo, so that
  half is operational; ``commands/routine.md`` is the versioned half.
* **drift guard** — this module: it fails if the discovery-logic *signature*
  (the selection-criteria triad) is inlined into a trigger/caller surface (the
  routine command) instead of living solely in the
  ``work-discovery`` skill and being *invoked* from those surfaces.

Acceptance criteria (CAL-907):

* **AC-1** — a ``work-discovery`` skill exists and the routine invokes it; pick
  logic is single-homed there, not duplicated in command prose. Proven by
  :func:`test_work_discovery_skill_present`,
  :func:`test_work_discovery_skill_registered`,
  :func:`test_work_discovery_skill_owns_pick_criteria`,
  :func:`test_build_routine_invokes_work_discovery_skill`, and the single-home
  drift guard :func:`test_pick_criteria_not_inlined_into_command`.
* **AC-3** — a guard test fails when discovery logic is inlined into a trigger
  rather than invoked from the versioned surface. Proven by
  :func:`test_pick_criteria_not_inlined_into_command` and the detector-boundary
  pins :func:`test_inlines_detector_flags_the_full_triad` /
  :func:`test_inlines_detector_ignores_a_lone_token`.

(AC-2's runbook half lived in ``commands/harness.md``, which ADR 0015 deleted
along with the scheduled-task runbook it named. Its two functions went with
their subject; this docstring cited them for several releases after they were
gone — the class ``craft.md`` → *A docstring claiming coverage the code lacks*
names, corrected under #459.)

**What this module asserts (#459).** The detector and its two boundary
controls are unchanged — ``_inlines_discovery`` is an executable predicate, and
both the drift guard and the single-home claim call it. What changed is the
prose half: eleven section pins across four rule-homes collapse to one anchored
tripwire per home —

* ``## Held tickets`` — the skip rule, polarity bound to *pick*;
* ``## Actionability`` — the three-way deferral record and the three hold
  kinds, polarity bound to *label* (all three, **not** the label alone);
* ``## Return path`` — clearable / released / re-defer, polarity bound to
  *unassign*;
* ``## When a tracker write is refused`` — the posture lever, polarity bound to
  *skill* (fix the posture, **not** this skill). This one was previously read
  over the whole file, so it could be satisfied by a mention anywhere.

``test_work_discovery_version_is_0_9_0`` went: a literal version pin needs
hand-editing on every legitimate bump while tree-wide header⇄registry parity
(``test_guidance_source.py::test_surface_headers_match_registry``) already
holds the claim that matters. Whether the prose still means what it says is
the review gate's (``code-quality`` Part C → *A guard over prose owns structure
and negative space, never meaning*; ADR 0016).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SKILL = REPO_ROOT / "skills" / "work-discovery" / "SKILL.md"
ROUTINE_COMMAND = REPO_ROOT / "commands" / "routine.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def _section(text: str, heading_substr: str) -> str:
    """The body of the heading line containing ``heading_substr`` up to the next
    heading of the same-or-higher level."""
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


def _negation_bound_to(block: str, term: str) -> bool:
    """Does some sentence of *block* carry both *term* and a negation token?

    The binding is the point: a bare ``"not" in block`` over a paragraph is
    satisfied by almost any English prose, so the negation is asserted against
    the clause whose direction is the rule (ADR 0016; ``craft.md`` → *Mutate
    the rule into its opposite, not only out of existence*).
    """
    return any(
        _NEGATION.search(s) for s in _sentences(block.lower()) if term in s
    )


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
    body = ROUTINE_COMMAND.read_text()
    assert "work-discovery" in body, (
        "the routine must invoke the `work-discovery` skill for its pick "
        "step instead of inlining the discovery logic (CAL-907 AC-1)."
    )
    # It must still retain the pick step itself (the invocation point).
    assert "pick the next" in body.lower(), (
        "the routine must retain its pick step as the skill's invocation "
        "point (CAL-907 AC-1)."
    )


# --- AC-3: single-home drift guard — no inlined logic in the caller surfaces --


def test_pick_criteria_not_inlined_into_command() -> None:
    """AC-3 (core): the selection criteria are NOT duplicated into the routine
    command. The command is a *caller* of the versioned surface — if a future
    edit re-inlines the pick algorithm (the triad) into the Build routine section
    instead of invoking the skill, this guard fails."""
    body = ROUTINE_COMMAND.read_text()
    assert not _inlines_discovery(body), (
        "the routine command inlines the discovery-logic triad "
        "(dependencies + priority + decision) instead of invoking the "
        "`work-discovery` skill — the pick logic must be single-homed in the "
        "skill, not duplicated in command prose (CAL-907 AC-3)."
    )


# --- the four prose rule-homes, one anchored tripwire each --------------------


def test_actionability_records_a_deferral_three_ways() -> None:
    """Tripwire — the deferral step keeps all three writes and all three hold kinds.

    Terms: ``comment`` (what the ticket needs), ``assign`` + ``operator`` (the
    machine-readable hold signal and its holder), and the three hold labels
    ``decision`` / ``input`` / ``operator`` with the *skips all three* rule and
    the ``narrower`` note that ADR 0006 added.

    **No negation is asserted, and none is faked.** The rule here is an
    *obligation* — record the deferral three ways — not a prohibition, and the
    section's negation tokens attach to other clauses inside the same bullet
    (*something the run cannot supply*), so a bound negation would stay green
    with the obligation gutted. What carries the claim instead is the breadth:
    all three writes and all three hold kinds named in one window (ADR 0016).
    The direction — that the label alone is not enough — is the review gate's.
    """
    body = _section(SKILL.read_text(), "Actionability")
    assert body, "the skill must carry an 'Actionability' section (CAL-1108)."
    low = body.lower()
    for term in ("comment", "assign", "operator", "narrow"):
        assert term in low, (
            "work-discovery's deferral step must state the record in terms of "
            f"{term!r} — if a refusal prompted its removal, fix the posture "
            "instead (CAL-1108 / CAL-1166 / ADR 0006)."
        )
    for label in ("`decision`", "`input`", "`operator`"):
        assert label in body, (
            f"the deferral step must name the {label} hold kind (ADR 0006, #191)."
        )
    assert re.search(r"skips? all three", body, re.IGNORECASE), (
        "the deferral step must state that the loop skips all three hold kinds "
        "— the outbound semantics are unchanged by adding a kind (ADR 0006)."
    )
    assert re.search(r"all three", body, re.IGNORECASE), (
        "the deferral must require all three of comment, label and assignment — "
        "assignment is what the skip rule actually reads (CAL-1166 AC-2)."
    )


def test_refused_write_section_names_the_posture_lever() -> None:
    """Tripwire — a refused write routes to the configuration, not to this skill.

    Anchored on ``## When a tracker write is refused``; the version this
    replaces read the whole file, so a mention of ``autoMode`` anywhere in the
    skill satisfied it. Terms: ``automode`` (the allowlist), ``settings/``
    (where it lives), ``posture`` (what to change). Polarity: a sentence naming
    this skill carries a negation — *fix the posture, **not** this skill*.
    Without that binding the guard reads the same green on a section that told
    an agent the skill itself was the bug, which has been attempted twice.
    """
    body = _section(SKILL.read_text(), "When a tracker write is refused")
    assert body, "the skill must carry a refused-write section (CAL-1108)."
    low = body.lower()
    for term in ("automode", "settings/", "posture"):
        assert term in low, (
            "the refused-write section must name the lever in terms of "
            f"{term!r} — a refused write is a configuration gap (CAL-1108)."
        )
    assert _negation_bound_to(body, "skill"), (
        "the section must state the direction of the fix: change the posture, "
        "not this skill. Rewriting the deferral step into 'report it instead' "
        "reads like a fix and is not one (CAL-1108)."
    )


def test_held_tickets_section_keys_on_assignment() -> None:
    """Tripwire — the skip rule is keyed on assignment, with the label OR as bridge.

    Terms: ``assign`` (the signal), ``primary`` (its rank against the labels),
    and the three hold labels the transitional OR still covers. Polarity: a
    sentence naming what the loop picks carries a negation — a ticket a human
    holds is **not** the loop's to pick. The four-term co-occurrence this
    replaces reads identically on a section that told the loop to pick held
    tickets up.
    """
    section = _section(SKILL.read_text(), "Held")
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
    for label in ("`operator`", "`decision`", "`input`"):
        assert label in section, (
            f"the held section must name the transitional {label} label OR — the "
            "fallback until the queue backfill assigns held tickets (CAL-1166)."
        )
    assert _negation_bound_to(section, "pick"), (
        "the held section must say the loop does *not* pick a held ticket — "
        "without that negation the section reads the same whether held work is "
        "skipped or claimed (CAL-1166 AC-1)."
    )


def test_return_path_defines_clearable_and_released() -> None:
    """Tripwire — the return path defines both halves and its re-defer case.

    Terms: ``clearable`` and ``acceptance criteria`` (when a hold lifts),
    ``released`` with ``change spec`` / ``label removed`` / ``unassign`` (the
    three steps), ``load-bearing`` (why the third one is not optional), and a
    ``re-defer`` word (the incomplete-answer case). Polarity: a sentence naming
    the unassignment carries a negation — a sweep that records an answer
    *without* unassigning leaves the ticket held forever. Five separate
    functions over one section could not see that direction between them.
    """
    section = _section(SKILL.read_text(), "Return path")
    assert section, (
        "the skill must carry a return-path section naming when a held ticket "
        "is clearable and what releasing it means (#192)."
    )
    low = section.lower()
    for term in (
        "clearable",
        "acceptance criteria",
        "released",
        "change spec",
        "label removed",
        "unassign",
        "load-bearing",
    ):
        assert term in low, (
            f"the return-path section must define the release in terms of {term!r} "
            "(#192)."
        )
    assert re.search(r"re-?defer", section, re.IGNORECASE), (
        "the section must cover the re-defer case — a ticket released but "
        "still not actionable goes back through deferral, not left "
        "half-cleared (#192)."
    )
    assert _negation_bound_to(section, "unassign"), (
        "the unassignment must carry its negation — a sweep that records an "
        "answer *without* unassigning leaves the ticket held forever, which is "
        "the failure mode this section exists to name (#192)."
    )
