---
name: process-economy
description: Use when auditing what a repo spends to prove itself — vacuous tests, guards no occurrence justifies, ceremony that proves a stage ran rather than the property it protects, and gate or CI waste. The domain standard for the `/assess process` scope; load for that pass, not for routine task work.
---
# Process Economy

The domain standard for `/assess process`. The other scopes ask whether the system is right; this one asks **what the assurance machinery costs and what it buys**. Its subject is not the product but the apparatus around it — the test suite, the guards, the gate stages, the CI steps, the process steps every change pays, and the artifacts they generate. `assessment-craft` still owns the finding bar, the 2×2, and the insight test; this file is the lens, not the method.

A pass here is **subtractive**. Most of what it yields is a deletion or a simplification, which inverts the usual reading of a finding: the question is not "what else should we check?" but "what are we checking that nobody can justify?" Assurance grows monotonically by default — every piece of it was added for a reason that sounded good at the time, and nothing in a per-change review is positioned to see the total. That total is this pass's subject, and reading it is only useful if it happens again: leanness is a tracked quantity or it is a mood.

## The burden of proof sits on the check

`engineering` → *Verification* states it on the build side: **a new guard cites the occurrence it prevents, and a guard nobody can trace to an occurrence is speculative — an assessment may read it as a deletion candidate.** This is that assessment. For every guard-shaped test, name the defect that actually occurred: an incident, a red gate, a revert, a ticket. Silence is the finding, and the burden sits on the check rather than on whoever proposes to remove it.

The inverse is the pass's most valuable output and the one nobody goes looking for: **the incidents the suite still does not defend against.** Read the repo's reverts, hotfixes, and post-merge bug tickets; for each, name the test that would catch it today. Assurance spent where nothing ever broke, and absent where things did, is misallocation — a different problem from under-testing, and invisible to a coverage number.

## Ground 1 — vacuous checks

A check that cannot fail for the reason it claims. One detection method governs all of them: **name the edit that should fail it, make that edit, and watch.**

**The catalogue of these shapes lives in `review-discipline` → `references/craft.md`**, which carries each one with the falsifying example that makes it recognisable, and admits a new entry only by operator call at the drain. Read it before sweeping, and propose additions there rather than re-homing an entry here. The split between the two files is *audience*, not subject: `craft.md` is written to recognise a shape in the diff in front of you, one at a time; the list below is the sweep order for a whole suite, where the question is coverage of the shapes rather than depth on any one. Same defects, arranged for a pass that reads everything.

- **Green from birth** — asserts behaviour it never saw absent; no RED was ever observed for it.
- **Synthesized inputs** — driven by events no production path emits, so it exercises a branch the live system never reaches.
- **Terminal-state-only loop tests** — seed only the exit condition, so a loop that never iterates passes.
- **Uncovered conditions** — a guard with several independent trigger conditions where deleting one leaves the suite green: the guard is covered, that condition is not.
- **Empty subject sets** — a sweep whose subject set can silently go to zero passes, and reports a property nothing holds.
- **Self-agreeing fixtures** — both operands derived from one source, so the assertion cannot disagree with itself.
- **Dead exemptions** — an exclusion or allow-list naming a path that no longer exists: an unowned hole, not a rule.
- **Pinned prose** — asserting what prose *means* rather than its structure or negative space; brittle and vacuous at once.
- **Change detectors** — restating the constant they check, so they fail only when both are edited together anyway.
- **Permanent skips** — a skip added as temporary that nobody removed, and the sharper case: a runner whose environment silently skips a whole contract suite, so its absence reads as green.

## Ground 2 — theatre

Ceremony that proves a stage ran rather than the property it protects.

- Gating on an artifact **existing** rather than being **true**.
- Reports or logs nothing reads — name the reader, or record it as unread.
- Steps every change pays that have never once failed. Ask of each: when did this last go red, and what did that catch?
- Duplicated verification — the same suite run twice in one pipeline under two names, or a repo-local check restating something an installed plugin already enforces.
- Accumulating piles with no retention rule: reports, snapshots, fixtures, generated artifacts.
- A rule stated in three places, which has three chances to drift and one owner. Restatement is cost, not emphasis.

## Ground 3 — waste

Measured, then ranked. Estimates are not findings here.

- Wall-clock the gate's stages and the ten slowest tests.
- Flag contention-sensitive checks: a subprocess timeout within 2× of its quiet-run duration passes on an idle host and fails under load.
- Serial stages with no data dependency between them.
- Setup repeated per file that could be per suite.
- CI steps fetching or building what no surviving check consumes.

Rank every candidate by **cost per run × runs per week**, so the report is ordered by minutes actually recoverable rather than by how wasteful something looks.

## The baseline — what makes this ongoing

Close every pass with three numbers and the delta against the previous one. **A number is comparable only if its derivation is fixed, so the derivation is part of the number**: record the command beside the value, and reuse that command next pass. Where a repo's layout makes a different command right, record *that* one and hold it stable — a delta between two hand-rolled measurements measures the measuring, not the suite. This repo has already produced the failure: ADR 0017 and `specs/features/plugin-surface.md` state the same assurance-lines figure computed two ways, one including the suite's helper modules and one excluding them.

1. **Assurance lines per product line**, by area — e.g. `git ls-files 'tests/**/*.py' | xargs wc -l` against the equivalent over the product globs. State the treatment of shared helper modules explicitly and keep it constant.
2. **Gate wall-clock**, from this pass's own runs on an otherwise idle host: the total, plus the slowest stage. Record the host and worker count, because Ground 3 is precisely about the contention that moves this number on its own.
3. **Checks whose failure-reason nobody could name** — the ground-1 and burden-of-proof count, over the same subject set each pass.

The series outlives the reports: retention folds a superseded report into `assessments/LOG.md`, whose entry shape carries these three numbers for a `process` pass (`templates/assessment.md`) so the trend survives past the one prior report the directory keeps.

A pass whose numbers have not moved since the last one is reporting on the drain, not on the suite: the candidates were raised and never decided. Say that plainly rather than re-raising them.

## What is not cruft

- **Frozen records** — assessments, proposals, retired specs, vendored snapshots. History carries no maintenance load.
- **A slow check that is load-bearing.** Slow is a cost to reduce, not evidence of waste.
- **A guard that has fired.** It has its occurrence; that is the whole bar.
- **Recorded redundancy** — defence in depth with a decision behind it.
- **A risk that has not yet materialised but is named in a decision.** The decision is the citation.

## Filing — two doors

Per `review-discipline` → *bugs are filed; improvements are proposed*:

- **Finding (filed as a ticket).** The tree contradicts itself today: a check asserting something false, an unowned hole over a live risk, a guard whose subject is gone, a permanent skip hiding a contract suite. Four parts, one assurance level.
- **Proposal (appended to the ledger).** Every deletion candidate and every efficiency win, one entry each, carrying its measurement. The operator decides at the drain.

The split carries more weight here than in any other scope: a pass that filed each deletion candidate as a ticket would grow the backlog in order to shrink the suite, and each shrink would then buy its own review round. The ledger lets one operator sitting decide fifty deletions together.

## Proving a candidate

Before proposing a deletion, perform the mutation: name the edit that should fail the check, make it in a scratch tree, and record what happened. "I could not see what this covers" is not evidence; "deleting the condition it guards leaves the suite green" is. `scripts/mutate.py` mechanises this where a repo has it (usage in `CONTRIBUTING.md`). The discipline itself — what counts as a killing mutation, and why mutating a rule into its opposite beats deleting it out of existence — is `craft.md` → *Mutation discipline*, and is not restated here. A candidate you could not disprove stays, and the report says so.

## Boundaries

- Plugin-owned skills, commands, agents, and hooks are upstream and out of scope — except to note where a repo-local check duplicates one, which is a finding for this repo. **This binds a *consuming* repo.** In the repo that **sources** the plugin those directories are the product, not upstream — `hooks/` in particular is the largest block of executable assurance machinery it owns — and they are swept like anything else.
- Read-only. Do not delete, fix, or tidy anything; the report and its filings are the deliverable.
- Work already in flight — open tickets, an active migration — is not re-found.
