# Assessment Craft

**Load this at the start of every `/assess` pass, whatever the scope.**

Shared knowledge for the `steward` whenever it periodically audits a codebase. Defines the finding bar, the second door a future risk comes through, how a finding is placed on the blocking×size 2×2, and the insight-vs-finding test. This is the methodology for every scope; the per-scope domain standards are named by the scope table in `skills/assess/SKILL.md`.

## Posture — signal, not noise

Your report becomes work items. Every finding is a unit of someone's future time. Treat finding count like money.

- **Specific or silent.** Every finding names a file, line, or concrete pattern. "Could be improved" is not a finding.
- **Evidence leads.** State what you found before proposing a fix.
- **A hypothetical states its trigger, its consequence and its cost, or it is dropped.** A risk that harms nobody today is never a finding. It is listed for the operator when it passes *Future risk — the second door* below, and otherwise it is not written at all.
- **Material or ledger.** Every finding names the user outcome or consumer behaviour its contradiction breaks. One that cannot is not filed. A risk that passes the second door below goes under the report's *Risks to approve*. Anything else is an improvement: write it under the report's *Below the floor*, apart from the findings, and `/assess` appends it to the improvement ledger instead of filing it. The floor is `review-discipline` → *Bugs are filed; improvements are proposed*, applied here where a finding becomes an issue; its reasoning lives there. The second door leaves that floor whole: a listed risk is an improvement too, and the pass files it no more than any other. The consequence is the point of the rule: a stale comment, a wording mismatch, or a defect no user reaches becomes no ticket of the pass's own, however specific its evidence. Only the operator's approval turns a listed risk into one.

If you write "could benefit from", "might be worth considering", or "it would be nice to" — delete the finding.

## Every finding has four parts

1. **What** — the specific issue.
2. **Where** — file:line (code) or section (docs).
3. **Why** — the rule, principle, or standard it violates, and the user outcome or consumer behaviour that breaks.
4. **How** — a concrete fix, not "this is wrong".

Missing any of these means it is not a finding yet.

## Future risk — the second door

A risk that harms nobody today is not a finding, and most such risks are not worth a line. One earns the operator's attention when the report states all three of these:

1. **The trigger.** The concrete condition under which it goes wrong: a second tenant, a table past a stated size, a token that expires, a dependency's next major version. "As usage grows" is not a trigger; a number or a named event is.
2. **The consequence, of one of four kinds.**
   - **Protected area.** It would lose user data, leak a credential, or move money wrongly: the protected areas the spine's *Lanes* names, at the stage the repo's *This repo* line declares.
   - **Dearer with every change.** Its fix costs more with each change built on it. Name which of the four tests in `authoring` → *Proposal spec* fires for the fix (migration, blast, access or comprehension), and why.
   - **Performance.** Something a user waits on is slow, or will become slow as data grows. Show it with a measurement, or with a named pattern such as a query per row or a list with no upper bound.
   - **Maintainability trap.** A trap the next agent is likely to fall into. Name the trap and the ordinary change that would spring it. A trap no named change springs is a preference.
3. **The cost of fixing it now.** The change it takes today, set against what it would cost after the trigger.

A risk missing any of the three is dropped. One that states all three goes under the report's *Risks to approve*, with the ID `{SCOPE}-RISK-{n}`, its three parts, its *where* and its *how*. The pass files nothing for it: `/assess` hands it to the operator, who approves or declines it (`skills/assess/SKILL.md`, step 2).

**A risk is listed once.** Before listing one, read the *Risks to approve* of every report still in `assessments/` and the `risks:` fields of `assessments/LOG.md`. A risk already there is not listed again, whether it is waiting, approved or declined. If a declined risk's trigger has since occurred, it harms someone today, so it comes back as a finding through the ordinary bar, not as a risk.

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
- **Name a specific file and the exact edit.** Not "update the skill" — "add a section to `engineering` stating X, so the developer catches Y before review."
- **Cite at least one finding as evidence.** No insight without a pattern behind it.
- **Zero insights is legitimate.** Say "no insights this cycle" rather than inventing one.
- **An insight is proposed, not filed.** It is an improvement — an edit that would make the guidance better, not a place the tree contradicts itself today — so it goes to the improvement ledger and is decided when `/assess` drains it (`review-discipline` → *bugs are filed; improvements are proposed*). The cap above still binds what you write; the ledger decides what is built.

## When a report is not just a finding list

Most scopes are finding engines: the report *is* the list of findings, and a clean pass files nothing. The `architecture` scope (`/assess architecture`) is different — it is a **holistic judgement**, and its report carries narrative sections that are **not** findings and are **not** filed as tickets: the verdict, what is working, the positive bets and trade-offs to preserve (`templates/assessment.md`, the architecture report shape). Recording them is the point of the pass. The finding bar above still governs the *actionable* part: every architecture **risk** you do file still needs the **four parts** — evidence first, a concrete fix, an honest blocking call. A narrative section is exempt from the four-part bar; a filed risk is not. A useful architecture pass can file **zero** tickets while still delivering a verdict and a watchlist.

The `process` scope (`/assess process`) departs in the opposite direction: it is **subtractive**, and most of what it produces is a deletion or simplification candidate. Those are improvements, not contradictions, so they are **ledger entries rather than tickets** — and the *three-insight cap above does not bind them*. The cap exists so a pass prioritises its guidance edits; a deletion candidate is not a guidance edit but the pass's ordinary output, and capping it would hide the accumulation the scope exists to measure. Its finding tail — a check asserting something false, an unowned hole over a live risk — is filed and still needs the four parts. `skills/assess/SKILL.md` owns which door each result goes through.

## What you are not looking for

Style preferences, formatting nits, complexity that is justified by the problem, intentional deviations that are improvements, or "future work" that cannot name its trigger, a consequence of the four kinds, and its cost now. A risk that can name all three comes through the second door above.

When unjustified complexity *is* a finding, the `code` scope names it with the `review-discipline` over-engineering taxonomy — that skill is its one canonical home; cite the tag and what replaces the cut, rather than restating the tags here.

## Output

Write a dated report in the `templates/assessment.md` format. The `assess` command files the **findings** and nothing else — an insight and a below-floor entry are improvements, so each is appended to the improvement ledger instead of being filed (above). A listed risk is appended there too, to wait for the operator's answer. For each finding use an ID prefixed by the steward's domain (`CODE-`, `ARCH-`, `PROC-`); insights append `-INSIGHT`, and risks append `-RISK`. Zero findings is a legitimate, stated outcome — do not invent findings, or risks, to fill the report.
