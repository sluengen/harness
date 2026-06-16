<!-- guidance:assess@0.4.0 -->
# /assess — run a periodic assessment

Usage: `/assess <scope>` — `code` or `system`, optionally with `--deep` (e.g. `/assess code --deep`)

Runs the `steward` over the codebase (or the guidance itself), produces a dated report, and files its findings as tickets. This is the periodic-review loop: it catches what accumulates across many changes, which no per-change review can see.

## One steward, scope selects the standards

There is **one** `steward` agent — the *process*. The scope you pass names the *what*, and the *domain standards* are skills the steward pulls just-in-time (`specs/architecture-principles.md`, "Assessment layering"). The command does not pick an agent per domain; it parameterises the one steward.

| Scope | Domain skills (pulled JIT) | Audits |
|---|---|---|
| `code` | `code-quality`, `test-driven-development`, `architecture`, `engineering-principles` (+ `design-system` when the layer is on) | The codebase: size/structure drift, duplication, dead code, stale TODOs, test health, cross-cutting security, architecture drift, dependencies. |
| `system` | `guidance-coherence` | The guidance and process: universal/repo boundary, version integrity, references, duplication, lean, profile coherence, CONTEXT currency. |
| `code --deep` | the `code` skills, plus coverage and spec-coherence lenses | The `code` lenses **plus** test-coverage quantity, design-system adherence (layer-gated), and spec/doc coherence — the broad weekly pass. |

## Why only two scopes

Reviews split by **axis, not dimension**. There are two surfaces: the per-change gate (`/review`, which *blocks* a merge) and this cumulative sweep (which *advises*). The sweep then splits only by *target* — `code` (the work) and `system` (the guidance that governs the work). Structure, tests, and architecture are *lenses inside* `code`, not separate scopes; folding them keeps the review surface small without dropping checks. `--deep` widens the `code` scope for the weekly arm rather than adding a third target. Split a lens into its own scope only as a per-repo escalation, when one repo's codebase is large enough that a single `code` run overflows context or misses findings.

## Steps

### 1. Run the steward
Dispatch the `steward` for the scope; it pulls the scope's domain skills just-in-time. It writes a dated report following `assessment-craft`: a summary, findings (each with the four parts and a severity), and up to three systemic insights. Zero findings is a valid result.

### 2. File the findings
For every finding and every insight, create a Linear issue (`linear`), labelled by source (`review-finding` / `review-insight`) and severity-mapped to priority. Insights — which propose edits to the guidance to prevent a class of findings — are the high-value output; file them prominently. Triage happens in Linear, not at report time. **If this repo has no tracker** (`CONTEXT.md` `layers.linear: false`): skip filing, keep the dated report, and surface the findings to the user directly — the report is the deliverable.

### 3. Commit the report
A report is advisory evidence, not a code change, so it needs no merge gate. Commit the dated report directly to the integration branch (`CONTEXT.md`) — no branch, no PR. The findings already live in the tracker; a PR per run would carry nothing reviewable and, under a scheduled cadence, pile up trivial approvals. Surface the summary, the finding counts by severity, and the filed ticket IDs to the user. (When the tracker is off, the report file *is* the deliverable — commit it the same way.)

## When there are no findings
Still record the report (it is evidence the assessment ran) and say so plainly. Skip filing. Do not invent findings to justify the run.
