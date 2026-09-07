---
name: routine
description: "/routine — one unattended tick of the build loop: discover the next wholly actionable ticket on the Build queue, build it, integrate it exactly as the repo's branch model declares, close it. Use when the operator says `/routine`, \"run a tick\", or \"work the queue\". It picks its own ticket, so reach for `/build <TICKET>` to build a named one. It pushes no branch but the integration branch, and holds the ticket rather than forcing past a red gate, a stuck review, or a merge a human owes. Reachable by an unattended scheduled run: this skill is the versioned home of the prompt such a run pastes, so `disable-model-invocation` is deliberately not set here — it would refuse the caller the command exists for (#564)."
model: inherit
effort: high
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /routine — one unattended build cycle

Usage: `/routine` (no arguments — discovery picks the ticket)

One tick of the unattended build loop: discover the next actionable ticket, build it, ship it, close it. This is the versioned home of the standing prompt that scheduled runs paste; a scheduled run should say no more than "run `/routine` in `<repo path>`". It is deliberately not a mode of `/build` — `/build` builds one named ticket; this command owns discovery, the standing branch authorisation, and the hold rule (ADR 0015).

## Steps

1. **Discover.** Invoke the `work-discovery` skill against this repo's Build queue and pick the next wholly actionable ticket. Its **Andon** rule runs first and can decide the pick on its own: while an open P1 bug exists, that bug is the only ticket this tick may start, and where it is held, the tick reports the stopped line and stops rather than reaching past it (spine P4). If nothing is actionable, report that in one line and stop — an empty queue is a clean outcome, not a failure.
2. **Build.** Run `/build <TICKET>` on the pick.
3. **Ship.** Build in the ticket's own worktree branched from the **integration branch** (`branches:` role `integration`), then integrate exactly as `harness.yaml`'s branch model declares and close the ticket. The model is the whole instruction: a direct push where it allows one, a PR where it requires one — and where the PR needs a human to merge it, that is a hold, not a failure. Do not substitute a merge mechanism this command names for the one the repo declares.

## Standing authorisation

This command carries the repo owner's standing, explicit authorisation to push directly to the integration branch. It extends **only** there: never push to any other role branch (`staging`, `main`, or equivalents) — those move only through `/promote`. Disregard any session-assigned `claude/*` branch: do not develop on it, and do not leave finished work stranded on it.

## The hold rule

A moved integration branch is not a hold — `/build`'s *Reconcile with the integration branch* step owns that rule, its two-attempt bound, and what spending the bound means; read it there. Hold when it escalates, when the gate is red, when the review budget exhausts, or when the branch model leaves the merge to a human: keep the work on its own branch, push the branch, and hold the ticket for the operator per the spine's hold contract (comment the reason, apply the matching hold label, assign the operator). Never force it through, and never retry the same failure in a loop.
