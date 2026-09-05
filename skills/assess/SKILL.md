---
name: assess
description: "/assess — run a periodic assessment. Use when the operator invokes `/assess` or asks to run that workflow. Operator-triggered only; the model does not fire it."
disable-model-invocation: true
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /assess — run a periodic assessment

Usage: `/assess <scope>` — `code`, `architecture`, or `process` (e.g. `/assess code`, `/assess process`)

**Tracker operations follow the spine's contract** (`CLAUDE.md` → *Tracker dispatch* and *Filing*): the `tracker:` field names the backend, the matching provider skill (`github-issues` or `linear`) owns the API recipes, and `none` degrades to specs and session reports. Do not embed provider API calls here.

Runs the `steward` over the codebase, produces a dated report, files its findings as tickets, and drains the repo's proposals ledger. This is the periodic-review loop: it catches what accumulates across many changes, which no per-change review can see.

## One steward, scope selects the standards

There is **one** `steward` agent — the *process*. The scope you pass names the *what*, and the *domain standards* are skills the steward pulls just-in-time (the "Assessment layering" decision). The command does not pick an agent per domain; it parameterises the one steward.

| Scope | Domain skills (pulled JIT) | Audits |
|---|---|---|
| `code` | `engineering`, `architecture` (+ `design-system` when the layer is on) | The codebase: size/structure drift, duplication, dead code, stale TODOs, test health, cross-cutting security, architecture drift, dependencies, test-coverage quantity, design-system adherence (layer-gated), and spec/doc coherence. |
| `architecture` | `architecture`, `engineering` | The system *shape*: purpose fit, boundary integrity, domain-model coherence, change ergonomics, operational/efficiency fit, verification architecture, spec-record health, watchlist recommendations. A **holistic** judgement — a verdict plus what to preserve, change, or watch — not a finding sweep. |
| `process` | `process-economy`, `engineering`, `review-discipline` (for `references/craft.md`, the vacuity catalogue) | The **assurance machinery**, not the product: vacuous checks, guards no occurrence justifies, ceremony that proves a stage ran rather than the property it protects, and measured gate/CI waste. **Subtractive** — most of what it yields is a deletion, and it closes on a baseline the next pass measures against. |

## The scopes — split by target and by report contract

Reviews split by **axis, not dimension**. There are two surfaces: the per-change gate (`/review`, which *blocks* a merge) and this cumulative sweep (which *advises*). The sweep splits along two axes:

- **Target** — `code` and `architecture` both read the **product**; `process` reads the **machinery that proves it** — the test suite, the guards, the gate stages, the CI steps, and the process steps every change pays. Both targets are tracked in the same tree, which is why the split is by what the pass is *for*, not by directory. There is no third target.
- **Report contract** — `code` is a **finding engine**: accumulated defects and drift that clear the future-ticket bar become tickets, and a clean pass files nothing. `architecture` is a **holistic judgement**: *is the system shape still right for the product, and what should we preserve, change, or watch?* Its output is a verdict plus narrative — what is working, the architectural risks, a watchlist — and only the *actionable* risks become tickets. A useful architecture report can file zero tickets. `process` is a **subtractive slate**: its output is mostly deletion and simplification candidates, each carrying a measurement, and they go to the **ledger** rather than the queue — filing each as a ticket would grow the backlog in order to shrink the suite. Only the small tail that contradicts the tree today (a check asserting something false, an unowned hole over a live risk) is filed.

Structure and tests stay *lenses inside* `code` — folding them keeps the surface small. **Why `architecture` and `process` are scopes rather than lenses, and the test a fourth would have to pass, is recorded once in `specs/architecture-principles.md` → *Assessment layering*.** Split a lens into its own scope for one repo only as a per-repo escalation, when that codebase is large enough that a single run overflows context or misses findings — a question of size rather than of contract.

**Cadence.** `/assess code` is the broad periodic pass. `/assess architecture` is **on demand / low-cadence** (a milestone, or a periodic check): a holistic verdict that barely moves week to week would only pile up trivial reports, so do not put it on a frequent schedule. `/assess process` sits between them — often enough that accumulation stays visible, rarely enough that its baseline can move between runs; a monthly cadence, or after any stretch that added a batch of guards. It is the one scope whose value comes from the *series* rather than the run, so a pass that skips the baseline has skipped the point.

## Steps

### 1. Run the steward
Dispatch the `steward` for the scope; it pulls the scope's domain skills just-in-time. It writes a dated report following `assessment-craft`: a summary, findings (each with the four parts and its blocking call), and up to three systemic insights. Zero findings is a valid result.

### 2. File the findings
For every finding, create an issue through the provider skill **in the Todo state**, with the repo's Build project attached (a project is mandatory when filing), labelled by source (`review-finding`), and carrying exactly one assurance level chosen per `spec-authoring` → *Choosing assurance*. Whether a finding blocks and how much verification its fix must buy are different axes: neither where the finding lands on the 2×2 nor how long it reads decides its assurance level. Filing to Todo — not Backlog — is deliberate: a finding is confirmed work, so a later unattended Build tick may pick one up without a human in between; the guards on that self-feeding loop are the assessment's finding bar at filing time and the merge-time review gate before anything ships. Triage happens in the tracker, not at report time. **If this repo has no tracker** (`CLAUDE.md` `tracker: none`): skip filing, keep the dated report, and surface the findings to the user directly — the report is the deliverable.

**A systemic insight is not filed.** An insight proposes an edit to the guidance to prevent a class of findings, which makes it an improvement rather than something the tree already contradicts (`review-discipline` → *bugs are filed; improvements are proposed*). Append each one to the repo's proposals ledger instead, in the entry shape `review-discipline` → *The proposal channel* defines, and let step 5 decide it alongside everything else the loop proposed. This is the steward's own output going through the same door it asks every other agent to use; a role that reports on the queue's growth cannot be exempt from the rule that bounds it.

**The `process` scope files the contradictions and proposes the rest.** Which result goes through which door is `process-economy` → *Filing*; its deletion and efficiency candidates carry their measurement to the ledger and are decided at step 5. They are **exempt from the three-insight cap** (`assessment-craft`) — they are the pass's ordinary output rather than guidance edits, and capping them would hide the accumulation the pass exists to measure.

**The `architecture` scope files only actionable risks.** An architecture report's value is largely narrative — the verdict, what is working, the trade-offs to preserve (`templates/assessment.md`, the architecture report shape). File **only** the actionable architecture risks and recommendations; do **not** file positive observations or stable trade-offs as tickets — they live in the report, not the backlog. A useful architecture pass may file **zero** tickets while still recording a verdict and a watchlist; that is a valid outcome, not a failed run.

### 3. Commit the report
A report is advisory evidence, not a code change, so it needs no merge gate. Commit the dated report directly to the integration branch (`CLAUDE.md`) — no branch, no PR. The findings already live in the tracker; a PR per run would carry nothing reviewable and, under a scheduled cadence, pile up trivial approvals. Surface the summary, the finding count, and the filed ticket IDs to the user. (When the tracker is off, the report file *is* the deliverable — commit it the same way.)

**Run the repo's verify gate on the committed tree before pushing** (`CLAUDE.md` `commands.verify`). No *merge* gate, as above — a report carries nothing reviewable — but this pass writes to a tracked directory, and step 4's retention deletes files from it, so "advisory" describes the content and not the blast radius. The push is refused without it in any repo that installs the enforcement hooks. If the gate is red on the integration branch before this run touched anything, say so and stop rather than pushing on top of it.

### 4. Apply retention
After committing the report, prune `assessments/` per the retention rule (`templates/assessment.md`): keep the latest report per scope plus any report with an open finding, and fold every superseded report into a one-line entry in the rolling `assessments/LOG.md`. This runs each pass so the directory stays a live index — the latest verdict per scope plus the open-finding tail — instead of accumulating a point-in-time file per run (at up to seven files a day, ~700 a year) whose findings are already fixed or ticketed. Never fold away a report with an open finding. Commit the compaction in the same step as the report.

### 5. Drain the proposals ledger
The ledger accumulates every improvement the loop proposed and nothing in it expires, so this pass is what clears it — the drain, and the only one. Read the accumulation (the provider skill owns how the ledger is found), then turn it into something answerable: **group** entries whose suggested home is the same file or surface, **abstract** several small ones into the pattern-level candidate they are really evidence for, **prioritise** what survives by the cost of leaving it, and present a short **slate** — what the operator can decide in one sitting, each with its case — rather than the raw list. Record every **verdict** back on the ledger thread as a comment, declines included with their reason, so the next drain does not re-present an answered entry. A promoted proposal becomes an operator-promoted ticket: create it through the provider skill in the Todo state, with the Build project attached and exactly one assurance level chosen per `spec-authoring` → *Choosing assurance*.

The slate needs somebody to answer it, so an unattended run does **not** drain: note the ledger's size in the report and stop there. Draining without an operator would mean the pass deciding its own proposals, which is the grant the whole split exists to close.

## When there are no findings
Still record the report (it is evidence the assessment ran) and say so plainly. Skip filing. Do not invent findings to justify the run.
