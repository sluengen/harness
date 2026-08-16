<!-- guidance:routine@0.2.0 -->
# /routine — one unattended build cycle

Usage: `/routine` (no arguments — discovery picks the ticket)

One tick of the unattended build loop: discover the next actionable ticket, build it, ship it, close it. This is the versioned home of the standing prompt that scheduled runs paste; a scheduled run should say no more than "run `/routine` in `<repo path>`". It is deliberately not a mode of `/build` — `/build` builds one named ticket; this command owns discovery, the standing branch authorisation, and the hold rule (ADR 0015).

## Steps

1. **Discover.** Invoke the `work-discovery` skill against this repo's Build queue and pick the next wholly actionable ticket. If nothing is actionable, report that in one line and stop — an empty queue is a clean outcome, not a failure.
2. **Build.** Run `/build <TICKET>` on the pick.
3. **Ship.** Follow `CONTEXT.md`'s branch model exactly as `/build`'s ship step describes: build in the ticket's own worktree branched from the **integration branch** (`branches:` role `integration`), merge back by direct push, close the ticket.

## Standing authorisation

This command carries the repo owner's standing, explicit authorisation to push directly to the integration branch. It extends **only** there: never push to any other role branch (`staging`, `main`, or equivalents) — those move only through `/promote`. Disregard any session-assigned `claude/*` branch: do not develop on it, and do not leave finished work stranded on it.

## The hold rule

A moved integration branch is not a hold — follow `/ship`'s *base-drift rule*: reconcile, re-gate, re-review, ship. Hold only when that rule escalates (a genuine functional conflict, or reconciliation fails twice), the gate is red, or the review budget exhausts: keep the work on its own branch, push the branch, and hold the ticket for the operator per the `tracker` skill (comment the reason, apply the matching hold label, assign the operator). Never force it through, and never retry the same failure in a loop.
