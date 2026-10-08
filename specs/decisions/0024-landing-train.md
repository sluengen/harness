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
