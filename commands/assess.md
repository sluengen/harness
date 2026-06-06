<!-- guidance:assess@0.1.1 -->
# /assess — run a periodic assessment

Usage: `/assess <domain>` — `code` or `harness`

Runs a steward over the codebase (or the guidance itself), produces a dated report, and files its findings as tickets. This is the periodic-review loop: it catches what accumulates across many changes, which no per-change review can see.

## Domains

| Domain | Agent | Audits |
|---|---|---|
| `code` | `code-steward` | The codebase: size/structure drift, duplication, dead code, stale TODOs, test health, architecture drift, dependencies. |
| `harness` | `harness-steward` | The guidance: universal/repo boundary, version integrity, references, duplication, lean, profile coherence. |

## Steps

### 1. Branch
Create a review branch off the integration branch (`CONTEXT.md`). Assessment is exception work and goes through review surface, not a direct push.

### 2. Run the steward
Dispatch the agent for the domain. It writes a dated report following `assessment-craft`: a summary, findings (each with the four parts and a severity), and up to three systemic insights. Zero findings is a valid result.

### 3. File the findings
For every finding and every insight, create a Linear issue (`linear-sync`), labelled by source (`review-finding` / `review-insight`) and severity-mapped to priority. Insights — which propose edits to the guidance to prevent a class of findings — are the high-value output; file them prominently. Triage happens in Linear, not at report time.

### 4. Open the report for review
Commit the report and open a PR (or hand it to the user) carrying the summary, the finding counts by severity, and the filed ticket IDs.

## When there are no findings
Still record the report (it is evidence the assessment ran) and say so plainly. Skip filing. Do not invent findings to justify the run.
