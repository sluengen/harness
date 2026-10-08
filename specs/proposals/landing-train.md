---
proposal: landing-train
status: accepted
date: 2026-10-08
related: [specs/decisions/0024-landing-train.md, specs/decisions/0023-takt-landing-windows.md, specs/proposals/takt-landing-windows.md, skills/routine/SKILL.md, skills/promote/SKILL.md, skills/tracker/SKILL.md, skills/work-discovery/SKILL.md]
---

# Proposal: landing train

> Split the unattended loop into builders that never land and one train that lands everything, so landings cannot collide by construction, builders scale independently, and every landing runs in the cloud.

## Problem / motivation

ADR 0023 shipped in 26.3.0 (#756, #757, #758): a `cadence:` block divides each pitch into a routine landing window and an attended reserve, a routine waits in its session for its window, and a routine that misses it parks the ticket for the next tick. It solves the collision problem calibrate measured (93 pairs of landings within 30 minutes over 16 days), at a price the windows themselves set:

- **The cadence caps throughput.** One build per tick and a reserve in every pitch hold calibrate to about twelve tickets a day; a shorter pitch shrinks the reserve below the 30 minutes an attended landing needs.
- **Every run trusts its own clock**, and a session sleeps up to 45 minutes for its window. The wait is proven for the cloud runner only; the Mac runner's wake from a background `sleep` is still owed (the shipped proposal's banner).
- **The Mac lands its own work.** Each Mac tick spends its landing gate (20 to 25 minutes in calibrate) and any red-gate repair on the one machine that alone can run the simulator, so Mac capacity goes to work the cloud could do.
- **The same-host rule rests on a false premise.** `tracker` says a cloud container's hostname "changes per session" and so never matches its predecessor. Two calibrate cloud sessions on 2026-10-07 and 2026-10-08, with different kernel boot ids, both report `hostname -s` as `vm`. With a cadence on, a cloud tick would read another cloud session's fresh claim as a live run on its own machine and skip. No consumer runs a cadence yet, so nothing is skipping today.

The harness already splits building from landing at the command level: `/build` ends at PASS and `/promote` lands. The schedule does not follow that split, and the windows are what it costs to keep the two fused in one tick.

## Options

**Option A: keep the landing windows (status quo since 26.3.0).** Built and tested. Keeps the throughput cap, the clock trust, the in-session wait, the Mac's landing load, and the same-host defect, which needs fixing either way.

**Option B: a landing train.** Builders run `/build` and park at PASS; nothing a builder does touches the integration branch. One train routine, on its own schedule and always in the cloud, lands parked work oldest first through `/promote`. Attended work parks too. Only the train ever pushes, and a train that misses its window lands nothing, so landings serialise with one clock check per train; builders scale to as many runners as the queue and the review budget allow; and the Mac only builds what needs a Mac. The train lands everything parked in one batch behind one gate, so the gate is a cost per train rather than a limit on how many tickets it can land; every landing is cross-session, so that gate always runs in full, and a ticket waits up to one train interval after PASS.

**Option C: a landing lock.** Considered and rejected in the original proposal: shared state and stale-lease handling for a property the train gives by having one lander.

**Option D: a single-ticket train.** The train lands parked tickets one at a time, each behind its own gate. Simpler on the happy path, but it turns the gate into a capacity limit (about two tickets an hour at calibrate's gate time), so a long build or a slow train leaves work queuing behind it. Option B keeps this as its fallback when a batch goes red, rather than as its normal path.

## Recommendation

**Option B**, superseding ADR 0023's windows, reserve and in-place wait while keeping what it built that the train needs: the `parked` condition, `park` and `parked`, and land-parked-first. It traces to P0 (it deletes the window machinery rather than adding to it), P3 (one lander removes a serialised landing from every builder's path and lets builders fan out), and P4 (a ticket the train cannot land leaves the train rather than stopping it).

### How it works

- **Builders.** `/routine` with a train configured runs discover and build as today and, at PASS, parks the ticket through `tracker` instead of running `/promote`. A builder never waits and never pushes the integration branch.
- **The train.** A separate scheduled routine, in the cloud only, that builds nothing. **Each train owns a window: from its scheduled departure to the next train's.** A train that cannot push before its window closes lands nothing: it abandons the candidate, leaves every ticket parked for the next train, and reports why. That rule is what makes one train at a time hold without any shared state: a late or slow train never pushes after its successor departs, so two trains never land over each other. It also keeps the batch atomic, since a train that misses its window leaves no half-landed batch. Each run lands **everything parked as one batch**:
  1. Read `parked` and merge each parked branch into one candidate on top of the integration branch, oldest first.
  2. A merge the train cannot reconcile mechanically names its own culprit: eject that ticket, keep the candidate as it stood before it, and carry on with the rest. The older ticket keeps its place.
  3. Gate the candidate once. Green, and the window still open: push once, and close every ticket in the batch. Green but the window closed: push nothing; the batch rides the next train.
  4. Red: the batch gate cannot say which ticket broke it, since tickets can pass alone and fail together. Fall back to landing this train's tickets one at a time, oldest first, each gated on top of the ones landed before it. The first that goes red is ejected; the rest land. No bisection: the worst case is one gate per ticket, and only on a train whose batch went red. Each of these single landings checks the window before its push, so a fallback that runs out of window stops there: what already landed stays landed, and the rest stays parked.
- **What the train repairs, and what it ejects.** `/promote` today makes a red landing gate "this builder's to fix". The train is not the builder and has none of the build's context, so it repairs only a mechanical merge conflict. Anything else (a red gate needing a code change, a conflict that changes behaviour, or a rebase that changes native code a cloud host cannot verify on a simulator) **ejects** the ticket: unpark it, return it to Todo with a comment saying why, and move on to the next. A ticket ejected twice for the same cause is held for the operator instead, so the loop never retries a failure forever.
- **Attended work.** `/promote` from an attended session parks by default, and the operator can still say "land it now"; that direct landing is the one exception to a single lander, and a collision with the train costs the train a rebase and a gate, which is recoverable.
- **Missed trains.** A train that misses its window costs one interval of latency and nothing else. Two consecutive trains that both miss theirs are a stopped line, not bad luck: the gate has outgrown the interval, or something is wedging the train. The second miss pulls the cord: it reports the gate's duration against the window and holds for the operator rather than letting every later train miss too.
- **Capacity.** The gate is a cost per train, not a cap per ticket: one 20 to 25 minute gate lands however many tickets are parked, so a builder that runs long simply puts two tickets on the next train. The cap reappears only on a train whose batch goes red, which falls back to one gate per ticket. Compute per ticket falls as batches grow; at one ticket per train it equals a full landing gate, against the windows' median 12 minutes on an unmoved `dev`.
- **Run identity.** A claim records a run identity that distinguishes cloud sessions (the session id where the host provides one, or the kernel boot id), alongside the host name. Two cloud builders then never mistake each other for a live run on one machine, and the Mac still sees its own previous run.

For calibrate this means: cloud builders as often as wanted, a Mac builder that takes `mac` tickets one at a time, and an hourly cloud train.

## Not doing

- Bisecting a red batch: the one-at-a-time fallback finds the culprit with no extra machinery. Reopen if red batches become common enough that the fallback's extra gates matter.
- A single-ticket train as the normal path (Option D): it makes the gate a capacity limit. It stays only as the fallback for a red batch.
- Keeping the routine windows and the attended reserve as a second mode: two landing models doubles what every skill must describe. Reopen if a consumer needs builders that land their own work under a schedule.
- A claim check between trains: the window already guarantees a train never pushes after its successor departs, and a second defence on a different operand buys nothing the clock does not.
- A landing lock (Option C): one lander already serialises.
- Managing the schedulers: the consumer's lane, as before.
- Retrying an ejected ticket inside the train: a train that rebuilds is a builder.
- Office hours for held tickets: separate, as before.

## Open decisions

Accepted by the operator on 2026-10-08, which settles the first four as this proposal recommends. The fifth was a design question for the build, and #761's design settled it.

| Decision | Resolution | Recorded in |
|---|---|---|
| Supersede ADR 0023's windows, or keep both modes | **Supersede in place**, with a dated note on ADR 0023 (item 4) | `specs/decisions/0024-landing-train.md` |
| The configuration shape | **The reshaped `cadence:` block is the switch.** It carries only the train's timetable (`timezone`, `anchor`, `pitch`), and declaring it puts the repo on the train; no separate key. This replaces the earlier draft's `landing: train`, which predates the window rule that made the cadence the train's timetable. | `templates/harness.yaml` |
| Where an ejected ticket goes | **Back to Todo with the reason**, held for the operator on a second ejection for the same cause | `skills/promote/SKILL.md` |
| Attended `/promote` default | **Park**, with "land it now" as the operator's override | `skills/promote/SKILL.md` |
| The run identity a claim records for cloud sessions | **The kernel boot id beside the host name**, on the claim's one `host:` line; a line without one never matches (#761) | `skills/tracker/SKILL.md` |

## Breakdown

1. **Run identity on claims.** Fix the same-host rule's false premise: a claim records an identity that differs per cloud session, and "fresh from this host" compares it. Needed whatever this proposal decides. · separable
2. **The train configuration and the builder's park at PASS.** A declared `cadence:` puts the repo on the train, and `/routine`'s builder path parks at PASS under it; attended `/promote` parks by default with the operator's override; the spine's *Parked* entry in *The contract* redefined for the train (a reviewed ticket waiting for the train, not one that missed a window). · separable, depends on 1
3. **The train routine.** A land-only tick: merge everything parked into one candidate oldest first, eject a ticket whose merge cannot be reconciled mechanically, gate once and push once, only inside the train's window; land nothing once the window has closed; on a red batch, fall back to one ticket at a time, each push checked against the window, and eject the first that goes red; hold on a second ejection; pull the cord on a second consecutive missed window. `/promote` gains the batch landing this needs. · sequential with 2
4. **Reshape the cadence into the train's timetable.** Keep the `cadence:` block's `timezone`, `anchor` and `pitch`, now the train's departures, and `scripts/landing-window.js`'s slot arithmetic, now answering one question for a `--run train`: is this train's window still open. Delete the `attended` and `routine` windows and the `parked_limit` from the block, the `--run routine` and `--run attended` paths and their tests, *The landing window*'s routine and attended cases in `promote`, the wait-in-place and window steps in `routine`'s *On a cadence*, and the reserve. Add the superseding note to ADR 0023, and rewrite the cadence sentence in the spine's *The lifecycle* in `AGENTS.md` and `templates/spine.md`. This item owns every deletion. · separable, depends on 3

## Risks / unknowns

- **The clock still matters, at one point.** The train trusts its host's clock for one thing, its window's close before the push. That is narrower than the windows' design, where every builder and attended session read the clock, and only cloud hosts make the check; it still has no guard against a skewed clock beyond the margin the window leaves.
- **Untested in use.** Neither design has run in a consumer yet: calibrate has no `cadence:` block. The capacity figure is arithmetic from calibrate's gate time, not a measurement.
- **The batch gate is a full gate.** On a train carrying one ticket it costs more than the windows' same-session reuse; on a train carrying several it costs less per ticket. No builder waits for it either way.
- **A red batch costs extra gates.** The fallback re-gates each ticket in that train. If tickets that pass alone often fail together, trains slow down; watch the red-batch rate in the first two weeks.
- **Ejection quality.** The train's line between a mechanical repair and a behavioural one is a judgement made without the build's context. A train that repairs too much lands unreviewed changes; one that ejects too much sends work round the loop. The second ejection's hold bounds the loop, not the judgement.
- **Latency.** A ticket lands up to one train interval after PASS, and a chain of dependent tickets pays that once per link, because a ticket is not ready to build until its blocker lands.
- **Native changes at landing.** A rebase that touches native code ejects a Mac-built ticket back to the Mac, so a busy integration branch can bounce `mac` tickets more than others. Watch the ejection rate for `mac` tickets in the first two weeks.
