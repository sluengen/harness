---
name: routine
description: "/routine — one unattended tick of the build loop: discover the next wholly actionable ticket on the Build queue, build it through `/build`, land it through `/promote` exactly as the repo's branch model declares, close it. Use when the operator says `/routine`, \"run a tick\", or \"work the queue\". It picks its own ticket, so reach for `/build <TICKET>` to build a named one. It pushes no branch but the integration branch, and holds the ticket rather than forcing past a red gate, a stuck review, or a merge a human owes. Reachable by an unattended scheduled run: this skill is the versioned home of the prompt such a run pastes, so `disable-model-invocation` is deliberately not set here — it would refuse the caller the command exists for (#564)."
model: inherit
effort: high
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /routine — one unattended build cycle

Usage: `/routine` (no arguments — discovery picks the ticket)

One tick of the unattended build loop: discover the next actionable ticket, build it, ship it, close it. This is the versioned home of the standing prompt that scheduled runs paste; a scheduled run should say no more than "run `/routine` in `<repo path>`". It is deliberately not a mode of `/build` — `/build` builds one named ticket; this command owns discovery, the standing branch authorisation, and the hold rule (ADR 0015).

## Steps

1. **Discover.** Invoke the `work-discovery` skill against this repo's Build queue and pick the next wholly actionable ticket. Its **Andon** rule runs first and can decide the pick on its own: while an open P1 bug exists, that bug is the only ticket this tick may start, and where it is held, the tick reports the stopped line and stops rather than reaching past it (spine P4). If nothing is actionable, report that in one line and stop — an empty queue is a clean outcome, not a failure.
2. **Build.** Run `/build <TICKET>` on the pick. It builds in the ticket's own worktree branched from the **integration branch** (`branches:` role `integration`) and ends at PASS with that branch pushed and the ticket In Review. A FAIL, DEFER or spent budget ends the tick there, held — see *The hold rule*.
3. **Ship.** Run `/promote <TICKET>` on the same pick. It rebases, gates over what will land, pushes and closes. The repo's branch model is the whole instruction: a direct push where it allows one, a PR where it requires one — and where the PR needs a human to merge it, that is a hold, not a failure. Do not substitute a merge mechanism this command names for the one the repo declares. **A tick that stops at a reviewed branch is not a finished tick**: the work is invisible to everyone but whoever reads the board, which is the outcome this step exists to prevent.

## On a cadence

Where `harness.yaml` declares a `cadence:` (ADR 0023), the tick runs on a takt and the steps above change in four places. With no `cadence:` block none of this applies, and the tick is exactly the three steps above.

- **Record the tick's start first**, as an RFC 3339 instant with `Z` (`date -u +%Y-%m-%dT%H:%M:%SZ`). It is the `--fired` every window check in this tick passes, and the window is the scheduled fire's, so a late start shortens the build rather than moving the window.
- **Skip on a fresh claim from this host.** Before discovery, read the claims on every In Progress and In Review ticket; where one is fresh from this host (`tracker` → *The andon cord*), another run is live on this machine. Report the ticket, its claim's age and its branch, and stop: two runs contending for one machine is the overlap the cadence exists to remove.
- **Parked work lands first.** Read `parked` (`tracker` → *`park` and `parked`*). Where it returns more than `cadence.parked_limit`, discovery and step 2 do not run and the tick only lands. Either way, once the window is open, land the parked tickets oldest first through `/promote <TICKET>`, then this tick's own.
- **Wait for the window, in place.** After PASS, and before landing anything, run the landing-window check as `/promote` → *The landing window* gives it. `not-yet` means wait: start a background `sleep` of the seconds until `opens`, with a timeout above that, end the turn, and on waking ask again. The probe ADR 0023 records proved a wait to 45 minutes with the container intact; a window further out than that is unproven, so report the gap rather than waiting past it. `closed` means `/promote` parks the ticket, which ends the tick cleanly: parked work is the next tick's, not a failure.

## Standing authorisation

This command carries the repo owner's standing, explicit authorisation to push directly to the integration branch, and to the ticket's own branch. It extends **only** there: never push to any other role branch (`staging`, `main`, or equivalents) — those move only through `/promote`'s release hop, which this tick never runs. That the integration push now happens inside `/promote`'s landing altitude does not widen the authorisation: it is the same push, by the same tick, onto the same declared role. Disregard any session-assigned `claude/*` branch: do not develop on it, and do not leave finished work stranded on it.

## The hold rule

A moved integration branch is not a hold — the `rebase` stage owns that rule, its unresolved-conflict bound, and what spending the bound means, and both `/build` and `/promote` load it from one reference; read it there. **Nor is a red gate at landing a hold:** `/promote`'s stage 3 is explicit that the builder fixes the red it meets, so that no tick stalls on another ticket's landing. Hold when the rebase escalates, when the review budget exhausts, when a red at landing turns out to need a design decision rather than a merge repair, or when the branch model leaves the merge to a human: keep the work on its own branch, push the branch, and hold the ticket for the operator per the spine's hold contract (comment the reason, apply the matching hold label, assign the operator). Never force it through, and never retry the same failure in a loop.
