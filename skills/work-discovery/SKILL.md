---
name: work-discovery
description: Use when an unattended routine must pick its own next ticket off the Build queue — how to read the queue, rank candidates, judge what is wholly actionable, and defer what is not. The discovery knowledge the routine invokes; the routine command owns the control flow, this skill owns the judgment.
---
<!-- guidance:work-discovery@0.2.0 -->
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

Work off one Linear project — the Build queue named in `CONTEXT.md` →
`repo.project`. Resolve it at runtime; never hardcode it. Consider only tickets
marked **Todo**: an **In Progress** ticket is either live or already handled by
the routine's reclaim pre-flight, and **In Review** is somebody's open handoff.

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
  unfinished dependency — do not guess. Defer it: **surface it in the run's
  report**, naming the ticket and what it needs, and move on to the next
  candidate.

### Deferring without a tracker write

An unattended runner **cannot write to the tracker**. The host refuses an
autonomous write to an external system that no human named — correctly — and this
skill's audience is that runner. So a deferral is a *report*, not a comment on
the ticket: name the ticket and what it needs, plainly enough that a reader who
was not here can act on it.

This is the fallback `/assess` already uses. The condition is not "does this repo
have a tracker" but **"is the tracker available to this run"**, and it has two
causes: the repo has none (`layers.linear: false`) or the run is unattended. Both
land in the same place — keep the report, surface the finding.

**Where the deferral lands: the routine's final output.** Be precise about this,
because it is weaker than `/assess`'s fallback and the difference matters. An
assessment commits a dated report to the integration branch, so its findings
outlive the run in the repo. A deferral **carries no code change** — nothing was
built — so there is no commit for it to ride on and no repo artifact holding it.
Its only surface is what the routine reports back to whatever triggered it, and
its durability is that trigger's, not the repo's. That path does work: this
skill's own gap reached a human exactly that way and became a ticket. But state
the deferral in the output as though it is the only record, because it is.

**Re-picking the deferred ticket next tick is acceptable**, and is the accepted
cost of this path rather than an oversight. A deferral you cannot record on the
ticket leaves it in the candidate set, so the next tick considers it again. That
is cheap — re-reading one ticket costs seconds, and the tick is not burned: it
continues to the next candidate, or falls through to the quality arm. It is also
safer than the alternative. Re-deriving the judgment from current data each tick
means a ticket a human has since fixed is picked up immediately, where a durable
local "skip this" note would park it for as long as the note outlived the
problem.

## The `decision` label — already-deferred work

A ticket carrying the `decision` label is waiting on a human who already knows:
someone with tracker access judged it not-yet-actionable and recorded that on the
ticket. **Skip it** — the record exists, so re-judging it adds nothing, and it
re-enters the queue when the human clears the label.

The label is set by whoever *can* write to the tracker: a human triaging, or an
attended session acting on a surfaced deferral. An unattended runner reads it and
never sets it. That is why a labelled ticket is skipped while the runner's own
deferrals are re-picked — the label means "recorded and waiting", and an
unattended deferral has no record beyond the run's report.

## When nothing is actionable

If no Todo ticket is wholly actionable, do not invent work. Report the empty
queue and let the routine fall through to its idle behaviour (e.g. an assessment
pass). An honest empty result is the correct output — a manufactured ticket is
not.
