# ADR 0024 — Builders park and one cloud train lands, on the cadence's timetable

- **Status:** Accepted
- **Date:** 2026-10-08
- **Source:** accepted proposal [`landing-train`](../proposals/landing-train.md)
- **Supersedes, in part:** [ADR 0023](0023-takt-landing-windows.md): its routine landing windows, attended reserve and in-place wait. Its `parked` condition, `park` and `parked`, land-parked-first, and the cadence's anchor and pitch stand.

## Context

ADR 0023 shipped clock-derived landing windows so that two unattended runners and the operator could share one integration branch. It solved the collisions at costs the windows set: one build per tick and a reserve in every pitch cap throughput; every builder and attended session reads its own clock and a routine may sleep 45 minutes for its window; the Mac lands its own work on the one machine that alone runs the simulator. Its same-host rule also assumed cloud hostnames change per session, and two calibrate cloud sessions both report `vm`. The commands already split `/build` from `/promote`; the schedule did not.

## Decision

1. **Builders never land.** With a `cadence:` declared, `/routine` builds and parks at PASS. Attended `/promote` parks by default; the operator may still land directly.
2. **One train lands, in the cloud.** A separate land-only routine departs on the cadence's timetable and lands everything parked as one batch: merge oldest first, gate once, push once.
3. **A train that misses its window lands nothing.** Each train owns the interval to the next departure and pushes only inside it. A train that cannot push in time abandons its candidate and leaves everything parked. This is what serialises trains without shared state and keeps each batch atomic. Two consecutive missed windows pull the cord.
4. **The train repairs only mechanically.** A merge it cannot reconcile ejects that ticket; a red batch falls back to one ticket at a time, each gated on the last and each push checked against the window, ejecting the first that goes red. An ejected ticket returns to Todo with the reason, and a second ejection for the same cause holds it for the operator. A rebase that changes native code a cloud host cannot verify ejects the ticket back to its builder.
5. **A claim records a run identity that distinguishes cloud sessions**, so parallel cloud builders never read each other as a live run on one machine.

## Alternatives

- *Keep ADR 0023's windows* — built and tested, but keeps the throughput cap, clock trust in every run, the in-session wait and the Mac's landing load.
- *A single-ticket train* — one gate per ticket turns the gate into a capacity limit; kept only as the fallback for a red batch.
- *Bisecting a red batch* — more machinery than the one-at-a-time fallback, for a case expected to be rare.
- *A landing lock* — shared state for what one lander and one window give for free.

## Consequences

- Builders scale to as many runners as the queue and review budget allow, and the Mac only builds.
- Every landing is cross-session, so the batch gate always runs in full: dearer per ticket than ADR 0023's same-session reuse on a one-ticket train, cheaper on a larger one.
- A ticket lands up to one train interval after PASS, and a chain of dependent tickets pays that once per link.
- The train's judgement between a mechanical repair and a behavioural one is made without the build's context; the second-ejection hold bounds the loop, not the judgement.
- The clock still matters at one point: the train's window close before its push, on cloud hosts only.

## Amendment (2026-10-08, #762)

The build of decisions 1 to 4 settled three points the decision left open or stated too broadly. The operator accepted each.

- **Decision 1 applies under a `cadence:` only.** Declaring the block is what puts a repo on the train, so attended `/promote` parks by default only there. With no `cadence:` there is no train to land a parked ticket, and every run lands as it did before.
- **Decision 3's cord fires on two trains in a row that land nothing**, whether the window closed or the train stopped for another reason: an unrunnable gate, a refused push, a re-merge that would not resolve. A train wedged on its gate or its push is the same stopped line as one that keeps missing its window. Each train that lands nothing records why on the tickets it leaves parked, and the next one reads that line.
- **Decision 4's native-code ejection does not ship.** The plugin cannot tell what native code is, or which host can verify it, without a declaration no consumer makes, and a key built before any observed break guards an unobserved risk (P2). The train's gate is the consumer's own `commands.verify` on the train's host. A native interaction that gate cannot see reaches the integration branch and surfaces as a red base at the next build on a host that can run it, a defect the operating context accepts. Reopen on the first native break a train lands.

## Amendment (2026-10-16, #777)

**Decision 1 binds every writer, not only builders.**

**Why.** On calibrate (2026-10-14), writers outside `/promote` — a `/propose` acceptance, two `/assess` report commits — pushed to the integration branch while a train was gating. Each train's push was refused, and its one retry gate (30 to 41 minutes) could not fit a 60-minute pitch: two trains in a row landed nothing. The decision's premise that a direct landing costs the train only "a rebase and a gate, which it recovers from" holds only while two gates fit one window.

**The rule.** Under a `cadence:`, only the train pushes the integration branch. A change with no ticket — a fix, a command's report, a back-merge, a consumer's own command — parks as a `park/<stamp>-<slug>` branch after its writer's own gate, and the branch is its whole record. The train lists `refs/heads/park/*`, lands those after the parked tickets under the batch's one gate, and deletes what it lands. It ejects nothing, because there is nobody to eject to: what it cannot land stays where it is, named in its report. The operator's in-session "land it now" remains the one exception, for any writer. With no `cadence:`, nothing changes.

**Rejected.**
- *Push only outside a train's gate interval* — `scripts/landing-window.js` gives every instant to some train's window, so "not gating" is not derivable without the landing lock this decision already rejected.
- *A ticket per writer, parked like any other* — a tracker write and a WIP slot per report, for cargo nobody reviews.
- *A park record on the tracker* — couples git cargo to a tracker parse, and is lost under `tracker: none`.
- *One shared park branch* — concurrent writers collide on it, which moves the collision rather than removing it.

**Recorded, not guarded.**
- A train carrying only park branches writes no `train:` line, so the two-in-a-row cord cannot see it.
- A park branch red in combination re-boards every train and forces the fallback until somebody repairs it. Never observed, because each writer gates before parking; reopen on the first train report naming one park branch `red` twice.
- `park/*` is a trust boundary equal to an integration push. A consumer restricting integration pushes to the train's identity protects `park/*` with its own branch rules.

## Amendment (2026-10-19, #785)

**Every gate the train runs must fit its window, the first included.**

**Why.** #778 checked step 10's retry and step 11's fallback gates against the window and started the first gate unconditionally. A train that departs late, or whose merges run long, then starts a gate its window cannot hold. The push is refused at `closes` whatever the gate reports, and the host has spent a full gate, 30 to 41 minutes against a 60-minute pitch on calibrate, for no landing.

**The rule.** Before each gate the train asks the window. A closed window runs no gate. An open one runs the gate unless the time left is no longer than the comparable gate: the latest gate the train knows that carried no ticket or park branch the candidate lacks. Before its first gate the train's one record is the first gate on the latest `train:` line of the oldest ticket in the candidate, which now names what that gate carried. A gate that does not fit leaves the batch parked as `missed` and writes no gate times. The next train therefore has no record and observes, so a record skips at most one train, and a gate that has outgrown the window is observed before the second empty train pulls the cord. With no comparable gate the gate runs, and an operator running the train may say to gate anyway. The host timeout is twice a comparable gate this train ran green over the same set, and the host's maximum otherwise. Decisions 2 and 3 stand.

**Rejected.**
- *The longest gate the train knows, as #778 sized it.* Under a gate that selects its checks from the diff (#784), a recorded duration measures that batch. A backend batch's record would skip a later docs-only one, so an unrelated record starves the train.
- *Only an identical batch.* Builders park between trains, so a missed batch seldom re-rides unchanged, and the check would almost never act.
- *A worst case, an average, or an estimate from the diff.* Each is a telemetry store or a prediction, and the cord already escalates a gate that has outgrown the window.
- *A new why, `missed: gate would not fit`.* Only the cord reads a why, and it counts both alike. The line beneath says no gate ran and why.
- *A margin above the comparable gate.* It would be an invented number, and the record is already a lower bound.

**Recorded, not guarded.**
- The containment rule assumes a gate that selects from the diff selects no fewer checks for more changes. Where a consumer's selection is not monotone, one train can skip wrongly; its line carries no times, so the next observes.
- A red gate held up by a hung check, or a gate the host killed after hanging, can run longer than the green gate would, and can skip one train the same way.
- A rebuild or fallback gate over fewer tickets than the train's earlier gate has no comparable gate, since a larger gate is no lower bound for a smaller one, and runs where #778 skipped it, with however little time is left. Its push still waits on the window. The cost is one gate's host time, on paths no train has been observed to take.
- A ticket left out of a train keeps its older line, so a later train can compare against a record that a skip has already used.
- A train carrying only park branches has no `train:` line to read, so its gate always runs, and the #777 residual stands: no cord sees it.
- A gate whose time left beats its comparable gate by seconds can still miss its push: stage 4, the re-read and the window check take time the record does not include.
