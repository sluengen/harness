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
  unfinished dependency — do not guess. Leave a comment on the ticket naming what
  it needs, label it `decision`, and move on to the next candidate.

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

## The `decision` label — already-deferred work

A ticket carrying the `decision` label was judged not-yet-actionable on an
earlier pass and is waiting on a human. **Skip it.** Re-litigating it every tick
wastes a run and risks inventing busywork; it re-enters the queue when the human
clears the label.

## When nothing is actionable

If no Todo ticket is wholly actionable, do not invent work. Report the empty
queue and let the routine fall through to its idle behaviour (e.g. an assessment
pass). An honest empty result is the correct output — a manufactured ticket is
not.
