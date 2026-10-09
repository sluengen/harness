---
proposal: takt-landing-windows
status: superseded       # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-10-07
shipped: 2026-10-07
related: [specs/decisions/0023-takt-landing-windows.md, skills/routine/SKILL.md, skills/promote/SKILL.md, skills/work-discovery/SKILL.md, skills/tracker/SKILL.md]
---

# Proposal: takt landing windows

> Run the unattended loop on a fixed cadence and give each tick, and the operator, its own window on the integration branch, so that two or more runners can work one queue without landing over each other.

> **Superseded in part 2026-10-09 by [ADR 0024](../decisions/0024-landing-train.md).** The landing windows, the attended reserve, the in-place wait and the parked limit are retired; the `parked` condition and the cadence's anchor and pitch stand, now the landing train's timetable.

> **Shipped 2026-10-07.** Every change spec this proposal spawned has landed on the integration branch: #756, #757, #758, audited against ADR 0023 on the umbrella #755. The as-built records in `specs/features/plugin-surface.md` are the canonical account of what each delivered; this file is the record of the decision, not of the behaviour. Two checks no build could carry remain the operator's: #758's AC-5, a no-cadence `/routine` tick in a consumer once 26.3.0 is released, and a probe that the Mac runner wakes from a background `sleep`, since ADR 0023's probe covered the cloud runner only. Everything below describes the tree as it was on 2026-10-07 and is history.

## Problem / motivation

`/routine` lands whenever its ticket is ready, and so does an attended `/promote`. With one runner that is harmless. The first consuming repo to outgrow it is calibrate, which wants to move from mostly attended sessions to two unattended runners: a cloud tick every four hours and a Mac tick every four hours offset by two, twelve ticks a day, with the Mac runner taking the tickets that need macOS tooling. Nothing in the loop today stops those two runners, or either of them and the operator, from landing on `dev` at the same moment.

Calibrate's tracker and git history for 21 September to 6 October 2026 (16 days, 266 closed tickets) show what concurrent landing costs now:

| Measure | Value |
|---|---|
| Throughput | 16.6 closed a day: 6.1 by the cloud routine, 10.6 by attended sessions |
| Arrivals | 16.2 filed a day |
| Pairs of landings within 30 minutes of each other | 93, of which 4 routine with routine, 39 routine with attended, 50 attended with attended |
| Merges of `dev` into a ticket branch before it landed | 0.70 per routine ticket, 1.30 per attended ticket |
| Routine ticket, start to Done | median 43 minutes, 90% within 2.1 hours |
| Routine ticket, start to the reviewer's record commit | median 27 minutes, 88% within 60 minutes |
| Routine landing (record commit to Done), `dev` unmoved | median 12 minutes, 90% within 26 |
| Routine landing, `dev` moved | median 23 minutes, 90% within 187 |

Each merge of a moved `dev` changes the tree, and under *The two gates* a changed tree means the landing gate runs again. In calibrate the full suite takes 20 to 25 minutes, so every collision costs a gate run and some cost a red-gate repair. CAL-2129 (a second worktree's Compose stack could not bind the port) is the same-host form of the problem: two runs on one machine contend for its resources as well as for the branch.

The operator's stated goal is fewer attended sessions, because running them is no longer sustainable. That makes the unattended loop the main producer, and the loop has no rule for sharing the integration branch.

## Options

**Option A: status quo, land when ready.** Each run merges a moved `dev` and gates again, as `skills/build/references/reconcile.md` already describes. Costs nothing to build. Leaves the rework in the table above, and gives the operator no predictable time to land attended work without racing a routine.

**Option B: a landing lock.** A run takes a lease (a ref, a tracker claim, a file) before rebasing and releases it after the push. Serialises landing exactly, at any cadence. Needs shared state, stale-lease handling and a rule for a run that dies holding the lease, and gives the operator no reserved time: an attended session still waits on whoever holds the lease.

**Option C: a fixed cadence with landing windows.** Ticks fire every *pitch* minutes. Each pitch is divided into a window in which only the routine that fired it may land, and a reserve in which only attended sessions may land. Every run derives the windows from `harness.yaml` and the clock, so there is no shared state to go stale. A routine that misses its window parks its reviewed ticket, and the next tick lands it. The reserve is deliberate spare capacity: it absorbs attended work and variance without disturbing the cadence.

**Option D: pipelined landing.** A tick never lands its own ticket. It starts by landing every ticket the previous ticks left reviewed, then builds one and leaves it In Review. No clock arithmetic, and each tick builds on a `dev` it just settled. Every landing is cross-session, so under *The two gates* every ticket pays a full landing gate (20 to 25 minutes in calibrate), every ticket waits a whole pitch to land, and there is still no reserved time for attended work.

## Recommendation

Option C. It is the only option that gives attended work a time of its own, and it needs no shared state, which a lock does (P0, P2: no second defence, no stale-lease machinery). It serialises landing across hosts with arithmetic each run can do alone.

### Window placement

A replay of calibrate's 90 unheld routine tickets over 20,000 simulated two-hour ticks fixed the placement. The model: a ticket is ready at its record commit, lands no earlier than its window opens, must finish before it closes, and otherwise parks; the next tick lands the parked ticket first with a full gate, and builds nothing while two are parked.

| Routine window (minutes after the tick fires) | Attended reserve | Parked | Mean wait, ready to landing | Start to Done, median / 90% |
|---|---|---|---|---|
| 0 to 90 | the 30 minutes before the tick fires | 17.0% | 1 min | 44 / 141 min |
| 30 to 120 | 0 to 30 | 11.3% | 10 min | 49 / 158 min |
| **45 to 135** | **15 to 45** | **8.5%** | **20 min** | **63 / 122 min** |
| 60 to 150 | 30 to 60 | 8.3% | 33 min | 77 / 127 min |

The window's close drives the park rate and its open drives the wait. Closing at 135 minutes, 15 minutes into the next tick, takes the park rate from 11.3% to 8.5%. The next tick is never landing then (its own window opens at 45), so the overlap costs at most a re-run of that tick's gate when it had already finished review, which happens on about 1% of ticks. Opening later than 45 minutes buys 0.2 points of park rate for 13 more minutes of waiting.

The reserve has a floor: an attended landing on a device is a 20 to 25 minute suite plus the push, so 30 minutes is the least that fits. An attended session can push at the reserve's start without re-running the suite whenever it gated after the current routine landed and `dev` has not moved since. That is *The two gates* as written, applied to a session that gates early.

For calibrate that gives: pitch 120 minutes, attended reserve 15 to 45, routine window 45 to 135, one parked ticket at most. With ticks firing at :57, a 10:57 tick opens the reserve at 11:12, the routine window at 11:42, and closes it at 13:12.

### What changes

- `harness.yaml` gains an optional `cadence:` block. Absent, every skill behaves as it does today.
- **Parked** is a new ticket condition beside held: In Review, branch pushed, a `parked` label and a comment naming the branch and reviewed commit, no assignee and no live claim. It is not a hold: the loop owns it, and the next tick lands it.
- `/promote` checks the window before its rebase stage and again before its push stage. A routine outside its window parks rather than pushes. An attended run outside the reserve warns, names the open routine window and the next reserve, and pushes only on the operator's confirmation.
- `/routine` waits for its window after PASS with a background command, lands the oldest parked ticket first, builds nothing while the parked count exceeds the limit, and skips the tick when a run from the same host still holds a fresh claim.
- `work-discovery` names parked tickets as landable work instead of reporting them as stranded, and counts them in the queue as it already counts In Review.

The cadence is a takt: the operator sets demand to it, so `queue.wip_limit` sized to about one day of ticks is the consumer's lever for holding arrivals to the cadence, and Backlog growth is the signal that demand has outrun it.

## Not doing

- A landing lock or lease (Option B): shared state for a property the clock already gives. Reopen if clock skew or window overruns put two pushes in one window more than once a week.
- Pipelined landing (Option D): every ticket pays a full landing gate and a pitch of latency. Reopen if parks exceed three a day.
- A hook that refuses a push outside the window: a mistimed push costs a merge and a gate, which is recoverable, and the spine reserves refusal for the unrecoverable or the silent and consequential. Reopen if attended pushes outside the reserve recur after the `/promote` check ships.
- Creating or managing the schedulers that fire ticks: the consumer's lane. The harness reads the cadence; the repo owns its cron entries.
- A tick that builds a second ticket when it finishes early: it reintroduces overlap with the next tick. Reopen if Backlog grows while most ticks are idle after landing.
- Office hours, where a tick may take a held `input` ticket while the operator can answer from a phone: a change to the hold contract, for its own proposal.
- Variable or demand-driven pitch: the point of a takt is that it does not move. Reopen if a consumer's demand changes by a factor of two.

## Open decisions

Every decision below was answered by the operator on 2026-10-07. The answers settle what this proposal says; they are not its acceptance.

| Decision | Resolution | Recorded in |
|---|---|---|
| Ship the cadence as an optional `harness.yaml` block for every consumer, or as a rule in calibrate's own `AGENTS.md` | **Harness-wide and optional.** The skills it changes live here, so a consumer-side rule would be a second copy overriding them from prose; with no `cadence:` block nothing changes. | `specs/architecture-principles.md` (ADR, since it changes the spine contract) |
| Mark parked work with a `parked` label, or infer it from In Review plus a stale claim | **An explicit `parked` label**, written by the run that missed its window with a comment naming the branch and reviewed commit. Inference would land on a guess, which `work-discovery` already refuses to do. | `skills/tracker/SKILL.md` |
| How a tick knows a run on the same host is still live | **The claim records the host.** A tick that finds a fresh claim from its own host skips. It uses state every run already writes and needs nothing from the consumer's scheduler. | `skills/tracker/SKILL.md` |
| Whether an attended `/promote` outside the reserve stops, or warns and lets the operator push | **It warns, and the operator decides.** `/promote` names the open routine window and the next reserve, then pushes on the operator's confirmation. A collision costs a merge and a gate, which is recoverable, and the spine refuses only the unrecoverable. | `skills/promote/SKILL.md` |
| How a cloud session waits up to 45 minutes for its window | **A background command** (`sleep N` with `run_in_background`, its timeout above N), resolved by probe. See *Risks / unknowns*. | `skills/routine/SKILL.md` |

## Breakdown

1. **Cadence shape.** The `cadence:` block (anchor time, pitch, attended reserve, routine window, parked limit), its reader in `scripts/harness-config.js`, and one script that answers "may this run land now, and when does its window open and close" with an exit code, with tests over the slot arithmetic including the overlap into the next pitch and a DST change. Held `input` for the operator: the key names fan out across four skills and the consumers' configs (Blast, Comprehension). · separable
2. **Parked condition.** `tracker`'s `park` and `parked` operations: label, comment, claim release, and the read that returns parked tickets oldest first; the claim records the host. · separable, depends on 1
3. **Landing inside the window.** `/promote` calls the item 1 script before its rebase and push stages, parks a routine that falls outside, and warns an attended run outside the reserve, pushing only on the operator's confirmation. · separable, depends on 1 and 2
4. **The tick on a cadence.** `/routine` waits for its window, lands parked work first, stops building over the parked limit, and skips on a same-host live claim; `work-discovery` names parked tickets as landable; the spine's *The contract* and *The lifecycle* gain the cadence and the parked condition, mirrored in `templates/spine.md`. · sequential with 3

## Risks / unknowns

- **The simulation is pessimistic and small.** 90 tickets over 16 days, with landing times measured under today's contention. Landings on an unmoved `dev` should be faster than modelled, so the park rate is more likely to fall than rise. A two-week measurement after rollout settles it: parks a day (expect about one), extra gate runs, attended landings inside the reserve, and Backlog growth.
- **Waiting is proven to 45 minutes, not beyond.** A probe on 2026-10-07, run in a finished calibrate routine session, started a background `sleep` and ended its turn: the session woke itself 5 seconds after a 10-minute sleep and 12 seconds after a 45-minute one, and a marker file and the kernel boot id were unchanged both times, so the container survived. `send_later` is not available in a routine session, so the background command is the mechanism. The longest wait this design asks for is 45 minutes, a ticket ready the moment its tick fires. A background command runs for at most two hours, and an idle session longer than the probe could still lose its container; a window further out than 45 minutes needs its own probe. The probe ran in a resumed routine session rather than a fresh scheduled firing.
- **Clock trust.** Every run computes windows from its own clock. Cloud containers and a Mac on NTP should agree within seconds, and the 15-minute overlap absorbs more than that, but nothing checks it.
- **Cron runs late.** A tick that starts late still owns the window its scheduled fire time defines, so a late start shortens its build time rather than shifting the window.
- **Throughput is capped by the cadence.** Twelve ticks a day closes at most about twelve tickets. Calibrate closed 16.6 a day with attended sessions; holding demand to twelve is the operator's choice, and the queue limit is how it is held.
- **Mac-only gate arms.** A ticket parked by the Mac runner may be landed by the cloud runner. In calibrate the default gate never runs the iOS release arm, so this works; a consumer whose default gate needs a host-specific arm would have to keep parked work on its host.
