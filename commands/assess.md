<!-- guidance:assess@0.6.1 -->
# /assess — run a periodic assessment

Usage: `/assess <scope>` — `code`, `architecture`, or `system`, optionally with `--deep` (e.g. `/assess code --deep`, `/assess architecture --deep`)

Runs the `steward` over the codebase (or the guidance itself), produces a dated report, and files its findings as tickets. This is the periodic-review loop: it catches what accumulates across many changes, which no per-change review can see.

## One steward, scope selects the standards

There is **one** `steward` agent — the *process*. The scope you pass names the *what*, and the *domain standards* are skills the steward pulls just-in-time (the "Assessment layering" decision). The command does not pick an agent per domain; it parameterises the one steward.

| Scope | Domain skills (pulled JIT) | Audits |
|---|---|---|
| `code` | `code-quality`, `test-driven-development`, `architecture`, `engineering-principles` (+ `design-system` when the layer is on) | The codebase: size/structure drift, duplication, dead code, stale TODOs, test health, cross-cutting security, architecture drift, dependencies. |
| `architecture` | `architecture`, `engineering-principles` | The system *shape*: purpose fit, boundary integrity, domain-model coherence, change ergonomics, operational/efficiency fit, verification architecture, spec-record health, watchlist recommendations. A **holistic** judgement — a verdict plus what to preserve, change, or watch — not a finding sweep. Canonical form `/assess architecture --deep`. |
| `system` | `guidance-coherence` | The guidance and process: universal/repo boundary, version integrity, references, duplication, lean, profile coherence, CONTEXT currency. |
| `code --deep` | the `code` skills, plus coverage and spec-coherence lenses | The `code` lenses **plus** test-coverage quantity, design-system adherence (layer-gated), and spec/doc coherence — the broad weekly pass. |

## The scopes — split by target and by report contract

Reviews split by **axis, not dimension**. There are two surfaces: the per-change gate (`/review`, which *blocks* a merge) and this cumulative sweep (which *advises*). The sweep splits along two axes:

- **Target** — `code` and `architecture` read the **codebase**; `system` reads the **guidance** that governs the work.
- **Report contract** (within the codebase target) — `code` is a **finding engine**: accumulated defects and drift that clear the future-ticket bar become tickets, and a clean pass files nothing. `architecture` is a **holistic judgement**: *is the system shape still right for the product, and what should we preserve, change, or watch?* Its output is a verdict plus narrative — what is working, the architectural risks, a watchlist — and only the *actionable* risks become tickets. A useful architecture report can file zero tickets.

Structure and tests stay *lenses inside* `code` — folding them keeps the surface small. Architecture is not folded the same way: the architecture-drift **lens** inside `code` still catches a crossed boundary or a contradicted decision *as a finding*, but the finding-engine contract squeezes out the holistic question — positive bets to preserve and trade-offs to keep are not findings, so they fall out at the "every finding is a ticket" bar. The holistic review needs a **different report contract**, not a different lens, so it is its own scope. `--deep` widens the codebase scopes (the broad weekly/periodic arm) rather than adding a target. Split any other lens into its own scope only as a per-repo escalation, when one repo's codebase is large enough that a single run overflows context or misses findings.

**Routine cadence.** The weekly Quality arm stays `/assess code --deep` to avoid churn; `/assess architecture --deep` is **on demand / low-cadence** (a milestone or a periodic check), run by a human or a slower routine — not added to the weekly loop. A holistic verdict that barely moves week to week would only pile up trivial reports.

## Steps

### 1. Run the steward
Dispatch the `steward` for the scope; it pulls the scope's domain skills just-in-time. It writes a dated report following `assessment-craft`: a summary, findings (each with the four parts and a severity), and up to three systemic insights. Zero findings is a valid result.

### 2. File the findings
For every finding and every insight, create a Linear issue (`linear`), labelled by source (`review-finding` / `review-insight`) and severity-mapped to priority. Insights — which propose edits to the guidance to prevent a class of findings — are the high-value output; file them prominently. Triage happens in Linear, not at report time. **If this repo has no tracker** (`CONTEXT.md` `layers.linear: false`): skip filing, keep the dated report, and surface the findings to the user directly — the report is the deliverable.

**The `architecture` scope files only actionable risks.** An architecture report's value is largely narrative — the verdict, what is working, the trade-offs to preserve (`templates/assessment.md`, the architecture report shape). File **only** the actionable architecture risks and recommendations; do **not** file positive observations or stable trade-offs as tickets — they live in the report, not the backlog. A useful architecture pass may file **zero** tickets while still recording a verdict and a watchlist; that is a valid outcome, not a failed run.

### 3. Commit the report
A report is advisory evidence, not a code change, so it needs no merge gate. Commit the dated report directly to the integration branch (`CONTEXT.md`) — no branch, no PR. The findings already live in the tracker; a PR per run would carry nothing reviewable and, under a scheduled cadence, pile up trivial approvals. Surface the summary, the finding counts by severity, and the filed ticket IDs to the user. (When the tracker is off, the report file *is* the deliverable — commit it the same way.)

### 4. Apply retention
After committing the report, prune `assessments/` per the retention rule (`templates/assessment.md`): keep the latest report per scope plus any report with an open finding, and fold every superseded report into a one-line entry in the rolling `assessments/LOG.md`. This runs each pass so the directory stays a live index — the latest verdict per scope plus the open-finding tail — instead of accumulating a point-in-time file per run (at up to seven files a day, ~700 a year) whose findings are already fixed or ticketed. Never fold away a report with an open finding. Commit the compaction in the same step as the report.

## When there are no findings
Still record the report (it is evidence the assessment ran) and say so plainly. Skip filing. Do not invent findings to justify the run.
