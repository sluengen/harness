---
name: assess
description: "/assess — run one periodic assessment: dispatch the steward for a scope (`code`, `architecture`, or `process`), write a dated report, file its findings as tickets, and drain the improvement ledger. Use when the operator invokes `/assess`, or asks for a periodic health check, a codebase sweep, an architecture review, or an audit of what the tests and gate cost. Not for reviewing one change (`/review`) and not for fixing anything — the pass is read-only. Reachable by an unattended run, which reports the ledger's size rather than draining it, so `disable-model-invocation` is deliberately not set here (#565)."
model: inherit
effort: high
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /assess — run a periodic assessment

Usage: `/assess <scope>` — `code`, `architecture`, or `process`.

Tracker operations follow the spine's contract (`AGENTS.md` → *Tracker dispatch* and *Filing*): `tracker` owns the semantics and its matching transport reference owns the API recipes. Do not embed provider API calls here.

## One steward, scope selects the standards

There is one `steward` agent — the *process*. The scope names the *what*; the standards are skills it pulls just-in-time. The command parameterises that steward, never picking an agent per domain.

| Scope | Standards, pulled just-in-time | Audits | Report contract |
|---|---|---|---|
| `code` | `engineering`, `architecture` (+ the repo's `.claude/rules/design-system.md` when the layer is on) | The codebase: size and structure drift, duplication, dead code, stale TODOs, test health, security, architecture drift, dependencies, coverage quantity, design-system adherence (layer-gated), spec and doc coherence | A **finding engine** — findings that clear the bar become tickets; a clean pass files nothing |
| `architecture` | `architecture`, `engineering` | The system *shape*: purpose fit, boundary integrity, domain-model coherence, change ergonomics, operational and efficiency fit, verification architecture, spec-record health, watchlist recommendations | A **holistic judgement** — a verdict plus narrative (what is working, the risks, a watchlist); only actionable risks are filed |
| `process` | [`references/process-economy.md`](references/process-economy.md), `engineering` | The assurance machinery, not the product: vacuous checks, guards no occurrence justifies, ceremony that proves a stage ran rather than the property it protects, measured gate and CI waste | A **subtractive slate** — deletion and simplification candidates, each with a measurement, to the ledger; contradictions to the queue |

This table is the only router: each scope's standards are named here once and not repeated below, and whatever they open is reached through them.

## Target and cadence

Product and machinery live in the same tree, so the split is by what the pass is *for*, not by directory; there is no third target. This sweep *advises*; `/review` is the per-change gate that *blocks*.

Structure and tests stay lenses *inside* `code`. Why `architecture` and `process` are scopes rather than lenses, and the test a fourth would have to pass, is `specs/architecture-principles.md` → *Assessment layering*. Split a lens out for one repo only when a single run overflows context — a question of size, not contract.

**Cadence.** `/assess code` is the broad periodic pass. `/assess architecture` is on demand or low-cadence: a verdict that barely moves only piles up trivial reports. `/assess process` sits between them: often enough that accumulation stays visible, rarely enough that its baseline can move. Its value is the *series*, so a pass that skips the baseline has skipped the point.

## Steps

### 1. Run the steward
Dispatch the `steward` for the scope. It writes a dated report in the `templates/assessment.md` shape, following [`references/finding-bar.md`](references/finding-bar.md): a summary, findings (each with the four parts and its blocking call), and up to three systemic insights. Zero findings is a valid result: record the report anyway — it is evidence the assessment ran — file nothing, and never invent findings.

### 1b. Close the baseline — the `process` scope only
`/assess process` owes three standing measurements; `code` and `architecture` owe none, and a baseline table in their reports invents a series nothing reads.

They are the rows of the Baseline table in `templates/assessment.md`, under those names and in that order: `assessments/LOG.md`'s fold field carries exactly those three past the one prior report retention keeps. [`references/process-economy.md`](references/process-economy.md) → *The baseline* owns what each measures. Record each command verbatim beside its value and reuse it next pass: a delta between two differently-derived numbers measures the measuring, not the suite.

| Row | Derivation |
|---|---|
| Assurance lines per product line | `git ls-files '<paths.tests>*.py' \| xargs wc -l \| tail -1` over the same command on the repo's product globs; state both globs, and put the module count (`git ls-files '<paths.tests>*.py' \| wc -l`) beside the ratio. **Two denominators, both reported** — see `references/process-economy.md` → *The baseline*, item 1 |
| Gate wall-clock | the wall-clock and the slowest stage from this pass's own gate run. #621 retired the marker that recorded a run's duration, so there is no history to take a median over: one run is one observation, and the report says so rather than implying a distribution |
| Checks with no nameable failure-reason | the ground-1 and burden-of-proof count from this pass's own sweep; state the subject set counted over, and hold it constant |

**One observation is not a distribution.** Report the number this pass measured and label it as one run. If gate wall-clock becomes a question worth a trend, the answer is to record it somewhere a run can append to — not to rebuild a marker whose duration field was a by-product of certifying trees (ADR 0022 point 3).

Take the previous column from the last `process` report's Baseline table or its `assessments/LOG.md` fold line; where neither exists, write `first recorded baseline`. No starting value lives in this file: a measurement is true of one tree on one day, and this guidance installs into repos whose product globs it cannot know.

### 2. File the findings
For every finding, create an issue through `tracker`, with the repo's Build project attached (mandatory when filing), the `review-finding` source label, and exactly one `assurance:` label (`AGENTS.md` → *Filing*). Whether a finding blocks and how much verification its fix must buy are different axes: neither its place on the 2×2 nor its length decides its assurance level. A finding is confirmed work, so it is placed like any other filing — Todo where the project has a free slot, Backlog where it has none (`tracker` → *The limit*) — and a later unattended tick may pick one up with no human in between; the guards on that loop are the finding bar at filing time and the merge-time review gate. Triage happens in the tracker, not at report time. Where `harness.yaml` sets `tracker: none`, skip filing and surface the findings to the user; the dated report is the deliverable.

A systemic insight is not filed: it proposes a guidance edit that would prevent a class of findings, which is an improvement rather than something the tree already contradicts. Append each to the improvement ledger (`tracker` → *`ledger`*) as one entry carrying its case, the work that raised it, and the file a fix would land in; step 5 decides it.

The `process` scope files the contradictions and proposes the rest; which result goes through which door is [`references/process-economy.md`](references/process-economy.md) → *Filing*. Its deletion and efficiency candidates carry their measurement to the ledger and are exempt from the three-insight cap: they are the pass's ordinary output rather than guidance edits, and capping them would hide the accumulation the pass exists to measure.

The `architecture` scope files only actionable risks and recommendations. Positive observations and stable trade-offs stay in the report, not the backlog. Zero tickets alongside a verdict and a watchlist is a valid outcome, not a failed run.

### 3. Commit the report
A report is advisory evidence, not a code change: **no PR and no merge gate**, since the findings already live in the tracker and a PR per run would carry nothing reviewable while piling up trivial approvals. Write it on **its own branch in its own worktree** all the same (`worktree-isolation`): law 5 is unconditional — *ticketed or not, every change* — and a branch is not a PR, so isolating the work costs nothing the paragraph above was protecting. Land it on the integration branch (`harness.yaml`) once the gate is green, the same landing every worktree makes. Surface the summary, finding count, and filed ticket IDs to the user.

Run the repo's verify gate (`harness.yaml` `commands.verify`) on the committed tree before landing. This pass writes to a tracked directory and step 4 deletes files from it, so "advisory" describes the content, not the blast radius; nothing downstream re-runs the gate for you, and law 3 is what stands behind the landing. If the gate is red on the integration branch before this run touched anything, say so and stop rather than land on top of it.

### 4. Apply retention
After committing the report, prune `assessments/` per the retention rule (`templates/assessment.md`): the latest report per scope and any with an open finding stay, and every superseded report folds into a one-line entry in the rolling `assessments/LOG.md`. Commit the compaction with the report. Running it every pass keeps the directory a live index, not a growing pile.

### 5. Drain the improvement ledger
The ledger accumulates every improvement the loop proposed and nothing in it expires, so a drain is the only thing that clears it. With the operator present, invoke `drain` for the ledger and report the outcomes it recorded. It owns the pass; this step owns the call and its place in the sequence — after the steward has reported, never inside it, because the agent that wrote an entry is the wrong one to decide it (law 4). A pass deciding its own proposals is the grant this split exists to close.

Unattended, do not drain: read the ledger's size (`tracker` → *`ledger`*), state it in the report, and stop there. The slate needs somebody to answer it.
