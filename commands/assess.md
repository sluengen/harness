<!-- guidance:assess@0.2.0 -->
# /assess — run a periodic assessment

Usage: `/assess <domain>` — `code` or `system`

Runs a steward over the codebase (or the guidance itself), produces a dated report, and files its findings as tickets. This is the periodic-review loop: it catches what accumulates across many changes, which no per-change review can see.

## Domains

| Domain | Agent | Audits |
|---|---|---|
| `code` | `code-steward` | The codebase: size/structure drift, duplication, dead code, stale TODOs, test health, cross-cutting security, architecture drift, dependencies. |
| `system` | `system-steward` | The guidance and process: universal/repo boundary, version integrity, references, duplication, lean, profile coherence, CONTEXT currency. |

## Why only two domains

Reviews split by **axis, not dimension**. There are two surfaces: the per-change gate (`/review`, which *blocks* a merge) and this cumulative sweep (which *advises*). The sweep then splits only by *target* — `code` (the work) and `system` (the guidance that governs the work). Structure, tests, and architecture are *lenses inside* `code`, not separate stewards; folding them keeps the review surface small without dropping checks. Split a lens into its own steward only as a per-repo escalation, when one repo's codebase is large enough that a single `code` run overflows context or misses findings.

## Steps

### 1. Branch
Create a review branch off the integration branch (`CONTEXT.md`). Assessment is exception work and goes through the review surface, not a direct push.

### 2. Run the steward
Dispatch the agent for the domain. It writes a dated report following `assessment-craft`: a summary, findings (each with the four parts and a severity), and up to three systemic insights. Zero findings is a valid result.

### 3. File the findings
For every finding and every insight, create a Linear issue (`linear-sync`), labelled by source (`review-finding` / `review-insight`) and severity-mapped to priority. Insights — which propose edits to the guidance to prevent a class of findings — are the high-value output; file them prominently. Triage happens in Linear, not at report time. **If this repo has no tracker** (`CONTEXT.md` `layers.linear: false`): skip filing, keep the dated report, and surface the findings to the user directly — the report is the deliverable.

### 4. Open the report for review
Commit the report and open a PR (or hand it to the user) carrying the summary, the finding counts by severity, and the filed ticket IDs.

## When there are no findings
Still record the report (it is evidence the assessment ran) and say so plainly. Skip filing. Do not invent findings to justify the run.
