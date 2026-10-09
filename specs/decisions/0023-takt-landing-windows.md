# ADR 0023 — The unattended loop may run on a takt, with landing windows on the integration branch

> **Superseded in part 2026-10-09 by [ADR 0024](0024-landing-train.md).** Decision 1's routine windows and attended reserve, decision 4's warning outside the reserve, and decision 5's in-place wait are retired: builders park at PASS, and one train lands everything parked inside a window that runs from its departure to the next. Decision 2's parked limit goes with them: every builder now parks, so a limit would stop them all between trains, against ADR 0024's consequence that builders scale with the queue. What stands: the optional `cadence:` block, reduced to `timezone`, `anchor` and `pitch` and now the train's timetable; the grid it defines, daylight-saving rule included; the `parked` condition, now a reviewed ticket waiting for the train, with `park`, `parked` and land-parked-first; and decision 3's claim, which records a run identity rather than a host name (ADR 0024 decision 5). The sections below record the windows as decided on 2026-10-07.

- **Status:** Accepted; superseded in part 2026-10-09 by ADR [0024](0024-landing-train.md)
- **Date:** 2026-10-07
- **Source:** accepted proposal [`takt-landing-windows`](../proposals/takt-landing-windows.md)

## Context

`/routine` and an attended `/promote` each land whenever their ticket is ready. With one runner that is harmless. Calibrate, the first consuming repo to outgrow it, is moving to two unattended runners (a cloud tick and a Mac tick, alternating every two hours) and fewer attended sessions. Its tracker and git history for 21 September to 6 October 2026 show what concurrent landing already costs: 93 pairs of landings within 30 minutes of each other, and 1.30 merges of a moved `dev` per attended ticket against 0.70 per routine ticket, each one forcing a landing gate of 20 to 25 minutes. Nothing in the loop gives two runners, or a runner and the operator, a rule for sharing the integration branch.

## Decision

A consuming repo may declare a **cadence** in `harness.yaml`. With no `cadence:` block, every skill behaves as before.

1. **Windows from the clock.** Ticks fire every *pitch* minutes from a declared anchor. Within each pitch, a routine window belongs to the routine that fired it and an attended reserve belongs to attended sessions. Every run derives the windows from `harness.yaml` and the scheduled fire time, never from its own start time, so no shared state exists to go stale.
2. **Parked is a ticket condition beside held.** A routine that misses its window does not push. Its ticket stays In Review with its branch pushed, an explicit `parked` label, and a comment naming the branch and reviewed commit. The loop owns parked work and the next tick lands it, oldest first, before its own. A tick builds nothing while the parked count exceeds the declared limit.
3. **A claim records its host.** A tick that finds a fresh claim from a run on its own host skips, so two runs never contend for one machine.
4. **Attended landings outside the reserve warn.** `/promote` names the open routine window and the next reserve, and pushes on the operator's confirmation. No hook refuses a mistimed push.
5. **A cloud tick waits in place** with a background command until its window opens. A probe on 2026-10-07 proved this to 45 minutes with the container intact; a longer wait needs its own probe.

## Alternatives

- *Land when ready (status quo)* — costs nothing, keeps the rework measured above, and gives the operator no predictable time to land.
- *A landing lock or lease* — serialises landing at any cadence, but needs shared state and stale-lease handling, and gives attended work no reserved time.
- *Pipelined landing, where a tick lands only earlier ticks' work* — no clock arithmetic, but every landing becomes cross-session and pays a full gate, every ticket waits a pitch, and attended work still has no time of its own.
- *A rule in the consumer's own `AGENTS.md`* — rejected because the skills that change live in this repo, so a consumer-side rule would be a second copy overriding them from prose.

## Consequences

- The spine's contract gains the cadence and the parked condition; `tracker`, `promote`, `routine` and `work-discovery` change to match, through the tickets the proposal's breakdown files.
- Throughput is capped by the cadence: a consumer with twelve ticks a day closes at most about twelve tickets a day, and holds demand to that through `queue.wip_limit`.
- Parked work is landed by a session other than the one that reviewed it, so under *The two gates* it always pays a full landing gate.
- Every run trusts its own clock. The window placement leaves 15 minutes of overlap for skew, and nothing checks it.
- The windows for a given consumer are that consumer's configuration. The proposal records calibrate's values and the simulation that chose them; this ADR fixes the mechanism, not the numbers.
