---
name: assessment-craft
description: Use when running a periodic codebase or guidance audit as the steward (via /assess) — the finding bar, severity scale, and the insight-vs-finding test. Load during an assessment pass, not routine task work.
---
<!-- guidance:assessment-craft@0.2.1 -->
# Assessment Craft

Shared knowledge for the `steward` whenever it periodically audits a codebase or the guidance itself. Defines the finding bar, severity, and the insight-vs-finding test. The methodology for every `/assess` scope; the per-scope domain standards live in their own skills (`guidance-coherence` for `system`, the code-domain skills for `code`).

## Posture — signal, not noise

Your report becomes work items. Every finding is a unit of someone's future time. Treat finding count like money.

- **Specific or silent.** Every finding names a file, line, or concrete pattern. "Could be improved" is not a finding.
- **Evidence leads.** State what you found before proposing a fix.
- **Err toward lower severity.** A borderline High is a Medium.
- **No hypotheticals.** If it might not be a problem under normal conditions, do not file it.

If you write "could benefit from", "might be worth considering", or "it would be nice to" — delete the finding.

## Every finding has four parts

1. **What** — the specific issue.
2. **Where** — file:line (code) or section (docs).
3. **Why** — the rule, principle, or standard it violates.
4. **How** — a concrete fix, not "this is wrong".

Missing any of these means it is not a finding yet.

## Severity

| Severity | Definition |
|---|---|
| **Critical** | Security/data-integrity risk, a silent wiring failure, or a violation a current change is actively compounding. |
| **High** | A clear principle/decision/contract violation not yet causing problems but that will before the next touch in that area. |
| **Medium** | Structural drift, duplicated knowledge, a weak test assertion, a stale doc that creates confusion. |
| **Low** | Cleanup: minor drift, cosmetic inconsistency, an unused file, a dependency a minor version behind with no security reason. |

Calibrate honestly. An inflated backlog loses its shape and trains the reader to skim.

## Systemic insights — prevent recurrence

This is what makes a steward more than a linter. An insight is a concrete edit to a skill, agent, command, hook, or template that would stop a *class* of findings from recurring.

**Litmus:** does this one change prevent a class of future findings, or just fix this one? The former is an insight; the latter is a finding.

Rules:
- **Maximum three insights per report.** The cap forces prioritisation.
- **Name a specific file and the exact edit.** Not "update the skill" — "add a section to `code-quality` stating X, so the developer catches Y before review."
- **Cite at least one finding as evidence.** No insight without a pattern behind it.
- **Zero insights is legitimate.** Say "no insights this cycle" rather than inventing one.

## What you are not looking for

Style preferences, formatting nits, complexity that is justified by the problem, intentional deviations that are improvements, or "future work" that is not causing a problem now.

## Output

Write a dated report (the `assess` command handles filing). For each finding use an ID prefixed by the steward's domain (`CODE-`, `SYSTEM-`); insights append `-INSIGHT`. Zero findings is a legitimate, stated outcome — do not invent findings to fill the report.
