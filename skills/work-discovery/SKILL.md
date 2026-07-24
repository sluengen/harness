---
name: work-discovery
description: Use when an unattended routine must pick its own next ticket off the Build queue — how to read the queue, rank candidates, judge what is wholly actionable, and defer what is not. The discovery knowledge the routine invokes; the routine command owns the control flow, this skill owns the judgment.
---
<!-- guidance:work-discovery@0.6.0 -->
# Work Discovery

An unattended loop discovers its own work: it reads the task queue and decides,
without a human in the turn, which ticket to start next and whether that ticket
is ready to build. This skill is the single home of that judgment. A routine
(e.g. `/harness routine build`) **invokes** it; the routine command owns the
control flow (the pre-flight sweeps, which build surface to call, how to resume),
this skill owns the *discovery logic*. Keeping the logic here — not restated in
each trigger or command — is what lets *version the logic, not the schedule*
hold: every caller reads one home, so what runs cannot drift from what is
versioned.

## The queue

Work off the Build queue defined in `CONTEXT.md`. Its scope is set by the
**optional** `repo.project` — resolve it at runtime, never hardcode it:

- **`repo.project` set** — scope to that one project: the named Build queue.
- **`repo.project` unset** — the whole tracker queue. What "the whole queue"
  means is the backend's own natural full scope: for a `tracker: linear` repo,
  the team named in `repo.linear`; for a `tracker: github` repo, the board
  itself (which already *is* the full queue).

Consider only tickets marked **Todo**: an **In Progress** ticket is either live
or already handled by the routine's reclaim pre-flight, and **In Review** is
somebody's open handoff. Scope only bounds *which* tickets are in view — the
ranking and actionability below are the same either way.

## Ranking — pick the next most logical ticket

From the Todo list, pick the single next most logical ticket to start, weighing:

- **ID number.** Tickets are often filed in the order they need to be done, so a
  lower ID usually comes first — a weak default, overridden by the two below.
- **Dependencies.** A ticket blocked by unfinished work in Linear is not next,
  however low its ID. Prefer a ticket whose blockers are done.
- **Priority.** A higher-priority ticket outranks a lower one when neither is
  blocked.

These combine as judgment, not a strict sort: dependencies gate, priority
breaks ties, ID is the fallback order. Pick one ticket and evaluate it before
reaching for the next.

## Actionability — is this ticket ready to build?

A ticket is **wholly actionable** when an agent can start it cold and know what
done looks like: the goal is stated, the acceptance criteria are checkable, and
nothing it depends on is still open. Judge it against `spec-authoring` — a change
spec needs problem, approach, and acceptance criteria.

- If it **is** actionable, hand it to the routine's build surface.
- If it **cannot** be actioned yet — it needs a decision, missing detail, or an
  unfinished dependency — do not guess. Record the deferral three ways and move
  on to the next candidate: **a comment** naming what it needs; **a label** —
  one of three kinds, partitioning held work by what kind of human input the
  ticket waits on (ADR 0006): `decision` when a judgment call is needed (a
  direction or detail, clearable by answering from the ticket alone), `input`
  when the operator must supply something the run cannot (a work item, a
  credential, infrastructure stood up), or `operator` when an interactive,
  hands-on session is needed (setup, a visual check, anything requiring a human
  driving the tools) — **this meaning is narrower** than it once was, now that
  `input` exists for "the operator owes this ticket something"; and
  **assignment to the operator**, the machine-readable "a human holds this"
  signal the held-tickets skip rule reads (the label explains *why* it is held).
  The loop **skips all three** kinds the same way — the outbound hold semantics
  are unchanged by adding a kind; only the return path (e.g. `/decision`)
  distinguishes between them, selecting `decision` and nothing else.
  Where the routine provides a **`defer` verb** (as `/harness routine build`
  does: `harness defer <TICKET> --reason <text>`), call it — it posts the
  comment, applies the label, assigns the operator, and records the decision in
  the audit trail, so triage is an audited action like the lifecycle verbs
  rather than a hand-rolled tracker write. Where there is no such verb, make the
  comment + label + assignment through the `linear` skill directly.

## When a tracker write is refused

The host can refuse a write this skill instructs — the comment, the label, a
transition — in an unattended run. **That is a configuration gap, not a bug in
this skill.** The refusal names its own condition: an action no human named in
the turn and no configuration sanctioned. The lever is the profile's settings
(`settings/<profile>.json` → `autoMode.allow`), a natural-language allowlist
whose clauses name what an autonomous run may do and state the bound that makes
each one safe. Where the posture names the deferral write, the same routine in
the same guidance makes it without trouble.

So **fix the posture, not this skill.** Rewriting the deferral step into "report
it instead" reads like a fix and is not one: this skill ships to every repo on
this guidance, including those whose posture already permits the write, so the
rewrite tells a capable runner to go quiet and wedges the queue wherever it
lands. That has been tried; it is why this section exists.

When the posture cannot be changed from this run — the settings are the
operator's call, and granting yourself a permission is rightly refused — surface
the deferral in the run's output and name the clause that is missing. The report
reaches a human, and a human can grant it.

## Held tickets — work a human holds

A ticket a human holds is not the loop's to pick. **The primary signal is
assignment: skip any ticket assigned to a human, in any state.** Agents
authenticate with the operator's API key and have no Linear identity of their
own, so an assignee at all means a person has taken the ticket — a first-class
field every Linear view surfaces, and the operator's "my issues" is their
worklist for free. A held ticket re-enters the queue when the human unassigns it.

The labels say *why* it is held, not *whether* to skip: `decision` — a judgment
call is pending; `input` — the operator must supply something the run cannot;
`operator` — an interactive session is needed (this meaning is narrower than
it once was — it no longer also covers "the operator owes this ticket
something", which is `input`'s job now). They are the operator's three filters
("to think about", "to go do", "to sit down at the keyboard for"), not the
loop's skip lever.

**Transitional rule.** Until the queue backfill assigns every already-deferred
ticket, also skip any ticket carrying `decision`, `input`, **or** `operator`
even if it is not yet assigned — so tickets deferred under the old label-only
rule stay safe. Skip on **assignment OR one of the three labels**; the
assignment is authoritative, the label OR is the bridge.

Do not re-litigate a held ticket every tick — it wastes a run and risks
inventing busywork.

> The queue pull may filter `assignee: null` (and exclude `decision`/`input`/
> `operator`) as an optimisation, so held tickets never reach the ranking step.
> That filter is a convenience; **this judgment rule is authoritative** — if an
> assigned or held-labelled ticket does reach you, skip it.

## Return path — when a held ticket is clearable

The Actionability and Held-tickets sections above are the outbound half: defer
what cannot be actioned, skip what a human holds. This is the inverse — what
makes a held ticket ready to come back, and what "released" means once it is.
`/decision` (the versioned sweep that drains `decision`-held tickets) delegates
this judgment here rather than restating it; this section owns the test, that
command owns only its control flow.

A held ticket is **clearable** when the only thing missing is input the
operator has now supplied — for a `decision` hold, an answer that makes the
acceptance criteria checkable. (An `input` or `operator` hold clears the same
way, once its own missing piece has been supplied.)

**Released** means all three of:

- the resolution **written into the ticket's change spec**, not left only in a
  comment thread — so an agent that starts the ticket cold sees the answer in
  the spec it builds from, not buried in a thread it has to go dig up;
- the hold **label removed**;
- the operator **unassigned** — this is **load-bearing**: assignment is the
  authoritative skip signal (Held tickets, above), so a sweep that records an
  answer without unassigning leaves the ticket held forever. That is the exact
  failure mode of the ad-hoc prompt this replaces.

A ticket released but still not wholly actionable — the answer supplied did
not fully resolve it — is **re-deferred** through the normal Actionability
step (a fresh comment + label + assignment), not left half-cleared.

## When nothing is actionable

If no Todo ticket is wholly actionable, do not invent work. Report the empty
queue and let the routine fall through to its idle behaviour (e.g. an assessment
pass). An honest empty result is the correct output — a manufactured ticket is
not.
