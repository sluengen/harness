---
name: assessment-craft
description: Use when running a periodic codebase audit as the steward (via /assess) — the finding bar, the blocking×size 2×2, and the insight-vs-finding test. Load during an assessment pass, not routine task work.
---
<!-- guidance:assessment-craft@0.6.0 -->
# Assessment Craft

Shared knowledge for the `steward` whenever it periodically audits a codebase. Defines the finding bar, how a finding is placed on the blocking×size 2×2, and the insight-vs-finding test. The methodology for every `/assess` scope; the per-scope domain standards live in their own skills — the code-domain skills for `code`, `architecture` and `engineering-principles` for `architecture`.

## Posture — signal, not noise

Your report becomes work items. Every finding is a unit of someone's future time. Treat finding count like money.

- **Specific or silent.** Every finding names a file, line, or concrete pattern. "Could be improved" is not a finding.
- **Evidence leads.** State what you found before proposing a fix.
- **No hypotheticals.** If it might not be a problem under normal conditions, do not file it.

If you write "could benefit from", "might be worth considering", or "it would be nice to" — delete the finding.

## Every finding has four parts

1. **What** — the specific issue.
2. **Where** — file:line (code) or section (docs).
3. **Why** — the rule, principle, or standard it violates.
4. **How** — a concrete fix, not "this is wrong".

Missing any of these means it is not a finding yet.

## Placing a finding — the 2×2

A finding is placed by two binaries, **does it block?** and **is the fix small?**. That 2×2 is `review-discipline`'s and has its one home there; read the placement rules from that skill rather than from a copy here. What the axes mean for a periodic pass:

- **Blocking** — the tree contradicts its own contract today: a security or data-integrity risk, a silent wiring failure, a guard asserting something false, a violation a current change is actively compounding.
- **Non-blocking** — structural drift, duplicated knowledge, a weak test assertion, a stale doc that creates confusion, cleanup.

Calibrate honestly. An inflated backlog loses its shape and trains the reader to skim.

## Systemic insights — prevent recurrence

This is what makes a steward more than a linter. An insight is a concrete edit to a skill, agent, command, hook, or template that would stop a *class* of findings from recurring.

**Litmus:** does this one change prevent a class of future findings, or just fix this one? The former is an insight; the latter is a finding.

Rules:
- **Maximum three insights per report.** The cap forces prioritisation.
- **Name a specific file and the exact edit.** Not "update the skill" — "add a section to `code-quality` stating X, so the developer catches Y before review."
- **Cite at least one finding as evidence.** No insight without a pattern behind it.
- **Zero insights is legitimate.** Say "no insights this cycle" rather than inventing one.
- **An insight is proposed, not filed.** It is an improvement — an edit that would make the guidance better, not a place the tree contradicts itself today — so it goes to the proposals ledger and is decided when `/assess` drains it (`review-discipline` → *bugs are filed; improvements are proposed*). The cap above still binds what you write; the ledger decides what is built.

## Narrative scopes — when a report is more than findings

Most scopes are finding engines: the report *is* the list of findings, and a clean pass files nothing. The `architecture` scope (`/assess architecture --deep`) is different — it is a **holistic judgement**, and its report carries narrative sections that are **not** findings and are **not** filed as tickets: the verdict, what is working, the positive bets and trade-offs to preserve (`templates/assessment.md`, the architecture report shape). Recording them is the point of the pass. The finding bar above still governs the *actionable* part: every architecture **risk** you do file still needs the **four parts** — evidence first, a concrete fix, an honest blocking call. A narrative section is exempt from the four-part bar; a filed risk is not. A useful architecture pass can file **zero** tickets while still delivering a verdict and a watchlist.

## What you are not looking for

Style preferences, formatting nits, complexity that is justified by the problem, intentional deviations that are improvements, or "future work" that is not causing a problem now.

When unjustified complexity *is* a finding, the `code` scope names it with the `review-discipline` over-engineering taxonomy — that skill is its one canonical home; cite the tag and what replaces the cut, rather than restating the tags here.

## Output

Write a dated report in the `templates/assessment.md` format. The `assess` command files the **findings** and nothing else — an insight is an improvement, so it is appended to the proposals ledger instead of being filed (above). For each finding use an ID prefixed by the steward's domain (`CODE-`, `ARCH-`, `SYSTEM-`); insights append `-INSIGHT`. Zero findings is a legitimate, stated outcome — do not invent findings to fill the report.
