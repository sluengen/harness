---
name: work-discovery
description: Use when an unattended routine must pick its own next ticket off the Build queue — how to read the queue, rank candidates, judge what is wholly actionable, and defer what is not. The discovery knowledge the routine invokes; the routine command owns the control flow, this skill owns the judgment.
---
# Work Discovery

An unattended loop discovers its own work: it reads the task queue and decides,
without a human in the turn, which ticket to start next and whether that ticket
is ready to build. This skill is the single home of that judgment. A routine
(`/routine`) **invokes** it; the routine command owns the control flow (what to
run before picking, how to ship, when to hold), this skill owns the *discovery
logic*. Keeping the logic here — not restated in
each trigger or command — is what lets *version the logic, not the schedule*
hold: every caller reads one home, so what runs cannot drift from what is
versioned.

## The queue

Work off the Build queue defined in `CLAUDE.md`. Its scope is set by the
**optional** `repo.project` — resolve it at runtime, never hardcode it:

- **`repo.project` set** — scope to that one project: the named Build queue.
- **`repo.project` unset** — the configured provider's natural full queue.
  Resolve that scope through the configured provider skill rather than naming a backend
  address here.

Consider only tickets marked **Todo**: an **In Progress** ticket is somebody's
live run, and **In Review** is somebody's open handoff. Scope only bounds *which* tickets are in view — the
ranking and actionability below are the same either way.

## Ranking — pick the next most logical ticket

From the Todo list, pick the single next most logical ticket to start, weighing:

- **ID number.** Tickets are often filed in the order they need to be done, so a
  lower ID usually comes first — a weak default, overridden by the two below.
- **Dependencies.** A ticket blocked by unfinished tracker work is not next,
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
  on to the next candidate: **a comment** naming what it needs; **a hold
  label**, partitioning held work by what the ticket waits on — `input` when
  the operator must supply something the run cannot (an answer, a judgment
  call, a credential, infrastructure stood up), or `operator` when an
  interactive, hands-on session is needed (setup, a visual check, anything
  requiring a human driving the tools). There are exactly two, and `tracker`
  owns what each one means — read the kinds there rather than re-deciding them
  here. And **assignment to the operator**, the machine-readable "a human holds
  this" signal the held-tickets skip rule reads (the label explains *why* it is
  held). The loop **skips both** kinds the same way — the outbound hold
  semantics do not depend on which label was applied; only the return path
  (e.g. `/decision`) distinguishes between them, selecting `input` and nothing
  else.
  Make all three — comment, label, assignment — through the provider skill's
  provider-neutral hold operation. All three, not the label alone: assignment is
  what the skip rule below actually reads, and the comment is what `/decision`
  presents to the operator. The tracker issue *is* the audit trail; a deferral
  recorded nowhere else is still fully recorded.

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
assignment: skip any ticket assigned to a human, in any state.** Assignment is
the provider-neutral ownership signal; a held ticket re-enters the queue when
the human unassigns it.

The labels say *why* it is held, not *whether* to skip: `input` — the operator
must supply something the run cannot (an answer, a judgment call, a credential,
a fact); `operator` — an interactive session is needed. (`decision` is the
retired third label — it merged into `input`, ADR 0015; treat it as `input`
where it survives.) They are the operator's two filters ("to answer / go do",
"to sit down at the keyboard for"), not the loop's skip lever.

**Transitional rule.** Until the queue backfill assigns every already-deferred
ticket, also skip any ticket carrying a hold label — either live one, or a
surviving **retired** `decision` — even if it is not yet assigned, so tickets
deferred under the old label-only rule stay safe. Skip on **assignment OR any
hold label**; the assignment is authoritative, the label OR is the bridge.

Do not re-litigate a held ticket every tick — it wastes a run and risks
inventing busywork.

> The queue pull may filter `assignee: null` (and exclude the hold labels) as
> an optimisation, so held tickets never reach the ranking step.
> That filter is a convenience; **this judgment rule is authoritative** — if an
> assigned or held-labelled ticket does reach you, skip it.

## Return path — when a held ticket is clearable

The Actionability and Held-tickets sections above are the outbound half: defer
what cannot be actioned, skip what a human holds. This is the inverse — what
makes a held ticket ready to come back, and what "released" means once it is.
`/decision` (the versioned sweep that drains `input`-held tickets) delegates
this judgment here rather than restating it; this section owns the test, that
command owns only its control flow.

A held ticket is **clearable** when the only thing missing is what the operator
has now supplied — for an `input` hold, the answer, judgment call, credential
or fact the run could not produce, once it makes the acceptance criteria
checkable; for an `operator` hold, the hands-on session it was waiting on.

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
