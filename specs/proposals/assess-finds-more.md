---
proposal: assess-finds-more
status: shipped          # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-11-23
shipped: 2026-11-26
related: [specs/proposals/lifecycle-reset.md, specs/proposals/do-less-at-ingestion.md]
---

# Assessments that report future risk and say what they did not read

> **Shipped 2026-11-26.** All four items have landed: #818 took the first count, #819 added the future-risk door, #820 made the tree the subject, and #821 took the second count. All are children of umbrella #817. The as-built records in `specs/features/plugin-surface.md` describe what #819 and #820 delivered. *Counts* below gives both counts. The planted set did not exercise the door: the second run listed no risk to approve. None of the reopen triggers under *Not doing* is met.

## In brief

**So what.** `/assess` is the periodic health check an agent runs over a codebase. In Calibrate, and in the last passes on this repo, it reports almost nothing. Its instructions explain much of that. It may only raise what harms a user today, so a serious risk that has not gone wrong yet is treated like a typo. Nothing tells it to read the whole codebase, and recent runs seem to read mainly what changed. A defect that slipped past code review is nobody's to find.

**What changes.**

| Today | After |
|---|---|
| A serious risk that is fine for now is dropped or noted as a minor suggestion | The report lists it with what would trigger it, what it would damage and what fixing costs now. The ones you approve go on the board and are built without you |
| The check seems to read mainly recent changes, and need not say what it skipped | It also reads one area in depth, the one left unread longest, and lists what it did not read. Each run costs more |
| A defect that slipped past review is nobody's | Once merged, it is the health check's to find |
| Nobody knows how much the check misses | We plant known problems and count what it finds before and after |

**What we need from you.** Approve option B, reject it, or ask for smaller proposals. The risk: in September the test for what becomes a ticket was made yes-or-no to stop agents flooding the queue with suggestions. This puts judgment back, bounded by your approval before anything is filed.

## Settled already

| Question | Answer | Who, when |
|---|---|---|
| When a pass comes back clean, what is missing: visibility of what it found, attention to how the build loop runs, or more found in the code? | More found in the code. | Operator, 2026-11-23 |
| Should the September rule stay, under which only a harm to a user today becomes a ticket? | It needs a re-think. It is a good lens for risk and impact, but a large risk should not be ignored because it happens to be fine for now. | Operator, 2026-11-23 |
| Where does a qualifying future risk go? | Not to a ticket that waits on the operator. The report lists it. Once the operator approves the report and the fix, it goes on the board and is built autonomously. | Operator, 2026-11-23 |
| Which consequences qualify? | Protected areas, fixes that get more expensive over time, performance, and maintainability. "Sluggish apps cost users silently, and footguns for other agents slow us down." | Operator, 2026-11-23 |
| Where are an unattended pass's risks approved? | At the next `/drain`; an attended pass asks at its own end. Accepted as recommended. | Operator, 2026-11-23 |
| Is the planted-problem count a standing test? | No. It runs once before and once after. Accepted as recommended. | Operator, 2026-11-23 |
| Does per-change review's bar change too? | No. Accepted as recommended. | Operator, 2026-11-23 |
| Is the proposal accepted? | Yes: "Accept, file tickets". | Operator, 2026-11-23 |

## Why

The operator's observation: `/assess` returns mostly positive reports with at most a small to-do, on Claude and on Codex, in Calibrate and in this repo. In repos built entirely by agents, defects and inefficiency accumulate, so a run of clean reports is suspicious.

The reports bear the observation out.

- **Calibrate, code pass, 3 November.** 1,674 commits and 2,274 changed files had landed since the previous pass. One agent read them in one sitting. The verdict opens "Zero findings clear the bar." Four items went below the bar.
- **Calibrate, architecture pass, 10 November.** Zero findings.
- **Harness.** The three process passes logged since 31 August all read "findings: none". July and August code passes had filed between zero and seven findings each. No report has been written on any branch since 13 September, and the code scope last ran on 17 August.

Three causes sit in the instructions.

**1. A future risk has no way to count.** The finding bar says: "No hypotheticals. If it might not be a problem under normal conditions, do not file it." The rule it rests on, in the review skill, says a "defect in a case no user reaches for a year" is an improvement and not a bug. An improvement goes to the improvement ledger (the standing list of suggestions the operator decides in one sitting) as one line. So a design that will lose user data once a second account type exists gets the same treatment as a stale comment. The operator's question was whether a massive risk is ignored because it is fine for now. By the letter of the rule, yes.

This rule was a deliberate decision. Two proposals accepted in September made the line between bug and improvement mechanical, because agents filing improvements freely had grown the queue without bound. The rule did that job. Its cost is that it measures one thing, whether something is broken today, and never asks how bad the consequence is or how much dearer the fix becomes with time.

**2. Each pass reads the window, and nothing brings old code back.** The assess skill tells the steward (the agent that runs a pass) to report "the repeated and the cumulative". It does not say whether the subject is the whole tree or the changes since the last pass. The 3 November report says it "concentrates on the repeated and cumulative patterns this window could have produced". A log line from 24 July reads "tree clean, zero findings" because the package and its tests were "unchanged since the prior pass". Code that passed once is not read again unless it changes. The same report lists what it did not do: no full test run, no exhaustive endpoint authorisation audit, no dependency advisory audit, no migration run against a copy of production. The code report template does not ask for that list; this steward volunteered it.

**3. A defect that review missed has no owner.** The skill says "a single instance in the latest change belongs to review". Once the change has merged, review is over. A one-off defect that slipped through is excluded from the health check by that sentence and seen by nobody else.

**Cost of doing nothing.** The health check keeps certifying a window. Risks that will be expensive later stay invisible until they bite, and at that point the product may have users whose data is involved. A clean report keeps reading as "healthy" when it means "nothing in the recent changes is broken today".

## Options

**Option A — Measure only.** Plant a known set of problems on a throwaway branch, run `/assess code`, count what it finds, and change nothing until the count is in. · Cheapest, and it answers "is it blind or is the tree clean" with a number. · It cannot fix cause 1: a steward that finds a planted future risk is still told not to raise it.

**Option B — A door for future risk, a deep read that rotates, and a count before and after. Recommended.** Three edits to the assess instructions and its report template, bracketed by the planted-problem count. · Addresses all three causes and measures whether it worked. · Puts judgment back into the bar, and each pass costs more because it reads an area in depth.

**Option C — A longer checklist.** Add lenses to the code scope: performance, failure handling, concurrency, simplification. · Simple to write. · The same single agent reads the same window with more to look for, so each lens gets less attention. It does not touch causes 1 to 3.

**Option D — Several stewards.** Run one steward per lens or per area and merge their reports. · The most thorough reading. · Several times the token cost on every pass, and a merge step to build. The planted-problem count has not yet shown that one steward reading the right area is not enough.

**Option E — Lower the bar for everything.** Let each pass file a capped number of improvement tickets. · Improvements get built without waiting for the operator. · Reverses the September decision outright and brings back the queue growth it stopped. Most of what sits below the bar is small, and the operator's concern was the large risk, not the small item.

## Recommendation

Option B. It is the smallest change that answers both of the operator's points, and it leaves the September rule intact for everything except the case the operator named.

**A second door through the bar, for future risk.** A risk that harms nobody today is a finding when the steward can state three things:

1. **The trigger.** The concrete condition under which it goes wrong: a second tenant, a table past a stated size, a token that expires, a dependency's next major version.
2. **The consequence, which must be one of four kinds.**
    - It lands in a protected area: user data, credentials or money.
    - The fix gets more expensive with every change built on it. This uses the four tests the authoring skill already applies to a breakdown: stored data would have to be transformed, the change fans out across call sites, it decides how data can be queried, or the operator cannot steer without seeing it.
    - Performance: something a user waits on is slow, or will become slow as data grows. The report shows it with a measurement or a named pattern, such as a query per row or a list with no upper bound.
    - Maintainability: a trap the next agent is likely to fall into. The report names the trap and the ordinary change that would spring it.
3. **What fixing it costs now.**

A risk that cannot state all three stays where it goes today. One that can goes in a *Risks to approve* section of the report, and the pass files nothing for it. When the operator approves the report, each approved risk is filed as an ordinary ticket, placed on the board like any other, and built by the unattended loop. A risk the operator declines is recorded as declined, so the next pass does not raise it again. No ticket waits on the operator. The sentence "No hypotheticals" becomes: a hypothetical states its trigger, its consequence and its cost, or it is dropped.

This traces to the risk appetite in the spine, which says the repos do not accept losing user data, leaking a credential or moving money wrongly, and to *Build quality in*: a risk caught while the fix is cheap costs less than one caught after it bites. Performance and maintainability are the operator's additions: a sluggish app costs users without any of them reporting it, and a trap left for the next agent slows every later change.

**The subject of a code pass is the tree.** The skill says so in words. Each code pass keeps its sweep of recent change and adds one area read in depth, chosen as the area the earlier reports left unread longest. The report lists what it read in depth and what it did not assess. When a report is folded into the log, its line keeps the area it read, so the next pass can choose.

**A merged one-off defect is in scope.** The sentence about single instances changes to: a single instance in a change that has not merged is review's; once merged, it is the pass's.

**Count before and after.** Plant a fixed set of problems on a branch that is never merged, in three classes: broken today, future risk, and a one-off that review would have missed. Run `/assess code` before the edits and after. The two counts go into this proposal. This is a measurement taken twice and not a standing test, because the repo's own rule is that a permanent check needs an observed failure behind it.

## Not doing

- **A longer lens checklist (Option C)** — more to look for in the same reading spreads attention thinner. Reopen if the second count shows a whole class of planted problem missed although its area was read in depth.
- **Several stewards per pass (Option D)** — several times the cost, unproven need. Reopen if the second count shows the deep read still misses most of what was planted.
- **Improvement tickets filed by assess (Option E)** — the September decision stands for everything except stated future risk. Reopen if the ledger is drained and most entries are being built, which would show the operator's sitting has become a formality.
- **A lens on how the build loop itself runs** (review failures, rework, waiting, token spend) — the operator did not choose it on 2026-11-23. Reopen on request.
- **Putting below-the-bar items in the report headline** — the operator did not choose it. Reopen on request.
- **Changing the bar for per-change review** — review blocks a change and should stay mechanical. Hunting future risk is the periodic pass's job.
- **A schedule for assess** — the harness has had no pass since 13 September, and that is a matter of when it runs, not what it looks for. Reopen as its own capture.

## Open decisions

None. Each was answered on 2026-11-23 and moved to *Settled already*.

## Breakdown

Filed 2026-11-23 under umbrella #817: item 1 is #818, item 2 is #819, item 3 is #820, item 4 is #821.

1. **Count what assess finds today** — plant the fixed set of problems on a never-merged branch, run `/assess code` against it without filing or landing anything, record what was found and how each was routed, and write the count into this proposal. · shares none · orphans none · `assurance:simple` · separable
2. **Add the future-risk door** — the three-part test in the finding bar, a *Risks to approve* section in the report template, the routing in the assess skill, and the hand-over to `/drain` for an unattended pass's risks: the pass files nothing for a risk, and each risk the operator approves is filed as an ordinary ticket and placed on the board. The door admits a risk only when it states its trigger, a consequence of one of the four kinds (a protected area; one of the authoring skill's four expensive-to-unpick tests; performance shown by a measurement or a named pattern; a maintainability trap with the change that springs it), and the cost of fixing now. Anything else stays an improvement. · shares `skills/assess/references/finding-bar.md`, `templates/assessment.md` and `skills/assess/SKILL.md` with item 3 · orphans none · `assurance:complex` · separable
3. **Make the tree the subject** — state that a code pass reads the tree, add the rotating deep read chosen from what earlier reports left unread, require the read-in-depth and not-assessed lists in the code report shape, carry the area read into the log line, and move a merged single instance into the pass's scope. Depends on item 2, which writes the same three files. · shares those three files with item 2 · orphans none · `assurance:simple` · separable
4. **Count again and close** — rerun item 1's branch and set after items 2 and 3 land, record both counts side by side here, and reopen whichever *Not doing* line its trigger names. Depends on items 1, 2 and 3. · shares this proposal file with item 1 · orphans none · `assurance:simple` · separable

## Counts

### Before (item 1, #818, 2026-11-24)

**Set.** Nine problems were planted on `spike/assess-finds-more`, cut from `dev` at `2ccac313`, tip `ddc6421a`, never merged. Each is one commit with an ordinary message and a backdated date, in a file untouched for at least a month. The list, with class, file and commit, is on #818.

**Run.** One `code` steward, dispatched with the role's one-line body and told nothing about the plants. It read the skill text of the branch's own tree. The assess skill, the steward profile and the report template were byte-identical to installed plugin 37.2.0. The two planted guidance files, `reconcile.md` and `size-guard.md`, differed by construction. It filed nothing, appended nothing to the ledger and landed no report. Its report is attached to #818.

| Class | Planted | Found | Routing of each found problem |
|---|---|---|---|
| Broken today | 3 (P1 test lock, P2 promotion, P3 reconcile prose) | 3 | all findings: CODE-1, CODE-3, CODE-6 |
| Future risk | 4 (P4 credential, P5 parser copy, P6 performance, P7 maintainability) | 4 | P4, P5 and P6 as findings (CODE-2, CODE-5, CODE-4), each because the gate proved a harm today. P7 below the floor: "no caller hits the bug today" |
| One-off slip | 2 (P8 usage flag, P9 cross-reference) | 2 | both below the floor |
| **Total** | **9** | **9** | 6 findings, 3 below the floor, 0 dropped, 0 insight |

**Read these numbers narrowly.**

- **The plants were handed to it as a diff.** The subject was a branch nine commits ahead of `dev`, and the steward read `origin/dev..HEAD` commit by commit. Its *Why this pass* says the nine commits "have no review record". So this count measures a pass whose window is exactly the planted set. It does not measure one that has to find old code in the tree. Cause 2 (the pass reads the window) is therefore untested by this run. #821 must rerun under the same condition to compare like with like, and should say so.
- **The gate did half the work.** It is red on the spike: 23 failed, 690 passed. Five plants (P1, P2, P4, P5, P6) break existing tests. The steward ran the gate over the branch and over `dev`, and attributed every failure. The four that pass the gate (P3, P7, P8, P9) were found by reading the diff.
- **Cause 1 shows even here.** None of the four future risks was routed as a future risk:
  - P4, P5 and P6 were routed as findings only because a test turned each into a harm today. P6's performance cost appears as a side remark inside a correctness finding.
  - P7, the one future risk no test caught, went below the floor on exactly the September rule. The report gives no trigger, no consequence kind and no cost.

  This is the behaviour item 2 targets.
- **It also found real problems outside the set.** It found one real finding on the shared tree (CODE-7: `specs/features/plugin-surface.md` at 834 KB, too large for the architect it is handed to), four real below-floor items, and three insights. None was filed, because this run files nothing. They are listed on #818 for the operator.

### After (item 4, #821, 2026-11-26)

**Set.** The same nine plants were replayed in order onto `dev` at `24b77df3`, after #819 and #820 had landed. The branch is `spike/assess-finds-more-rerun`, tip `e021eb86`, never merged. Each commit keeps its original backdated date. `git patch-id --stable` gives the same nine ids for this branch as for the first one. The branch was again nine commits ahead of `dev`, so the window condition matched #818's.

**Run.** One `code` steward was dispatched with the role's one-line body and told nothing about the plants. It read the branch's own skill text: the assess skill, the finding bar, the report template and the steward profile, all byte-identical to installed plugin 37.4.0. It filed nothing, appended nothing to the ledger and landed no report. Its report is attached to #821. It chose `hooks/` as its area to read in depth, because no earlier report records an area. Four plants sit there: P1, P4, P5 and P6.

| Class | Planted | Found, before (`ddc6421a`) | Found, after (`e021eb86`) | Routing after |
|---|---|---|---|---|
| Broken today | 3 (P1, P2, P3) | 3 | 3 | all findings: CODE-1, CODE-3, CODE-6 |
| Future risk | 4 (P4, P5, P6, P7) | 4 | 4 | P4, P5 and P6 as findings (CODE-2, CODE-5, CODE-4); P7 below the floor |
| One-off slip | 2 (P8, P9) | 2 | 2 | both below the floor |
| **Total** | **9** | **9** (6 findings, 3 below the floor) | **9** (6 findings, 3 below the floor) | 0 risks listed to approve |

**The difference.**

- **Found and routed: no change.** Every plant was found both times and went to the same place. The gate caught the same five plants: 23 failed and 690 passed both times.
- **The future-risk door was not used.** The second pass listed **no** risk to approve.
  - P4, P5 and P6 became findings again because a failing test made each one a harm today. P6's performance cost is not mentioned at all this time. CODE-4 reports only what the plant broke.
  - P7 was the one plant that could show a change, as #818's review warned. It went below the floor again, this time as "a speculative cache resting on a false premise". The report names the trap (a second caller in one process gets no notice when the file is unreadable), but it gives no trigger, no consequence kind and no cost. It was not offered as a risk.
  - So on this set the door changed nothing. One plant is too small a base to say whether the door is too narrow or the steward does not reach for it.
- **The tree as subject: some effect, outside the set.** Both passes read the nine commits as a diff, so the planted set still cannot test cause 2. But the second pass had to choose an area and list what it did not read, and it did both. Its read of `hooks/` found a defect in merged code that the first pass did not report: CODE-7, the test lock does not apply when an edited path runs through a symlink. It also gave a nine-bullet *Not assessed* list, including the 848 `dev` commits it did not sweep. This is the behaviour item 3 asked for, seen once.

**Not doing, against the triggers.** None is met.

- **Option C.** Its trigger is a whole class missed in an area read in depth. Every class was found, and all four plants under `hooks/` were found.
- **Option D.** Its trigger is the deep read still missing most of what was planted. It missed none of the four plants in its area.
- **Option E.** Its trigger is about how the ledger is drained, which a count does not measure.
- **The other lines** reopen only when the operator asks.

The door not being used is not a trigger under any line. Read it with *Risks* → *Judgment returns to a rule built to have none*: a door that lists nothing every pass is the opposite of that risk, and it is worth a second look after a real pass, not another planted count.

**Found outside the set, and not filed here.** These were reported to the operator on #821. CODE-7 is a merged defect in the test lock (`hooks/test-lock-guard.js` `relativeTo`). `scripts/plugin-version.js` is 523 lines, over the 500-line hard limit, with no `size:` marker. The report also gives three systemic insights.

## Risks

- **Judgment returns to a rule built to have none.** The September rule says "nothing in the split is a judgement call, on purpose". The three-part test bounds the judgment, and nothing is filed until the operator approves, but a steward can still write a plausible trigger for a risk that will never arrive. The counts will show how many risks a pass lists; a long list every pass means the door is too wide.
- **Maintainability is the widest of the four kinds.** Almost any code can be called a trap for the next agent. Naming the change that springs it is the bound. If most listed risks are of this kind and most are declined, narrow it.
- **Unapproved risks sit in reports.** An unattended pass lists its risks and waits. If the operator does not read the report, the risks are as invisible as they are today.
- **A deeper read costs more per pass** and may overflow one agent's context on a large repo. The skill already allows splitting a pass for size.
- **The planted set measures the planted set.** A steward that finds seven of nine planted problems has not been shown to find seven of nine real ones. The count compares before with after and should be read no further.
- **The window reading may not be the cause.** It is inferred from what two reports say about themselves. If the first count finds everything planted in old code, cause 2 is wrong and item 3 shrinks to the coverage lists.
- **This guidance runs in other repos.** Calibrate and nano-erp load the same skill with a different tracker. Filing goes through the tracker skill, so the routing is portable, but the first approved risk there should be checked by hand.

## For the builder

Read against `360ce622` on `dev`, 2026-11-23.

- **The bar.** `skills/assess/references/finding-bar.md` → *Posture — signal, not noise*: the bullets **No hypotheticals** and **Material or ledger**; *What you are not looking for* ends with `"future work" that is not causing a problem now`, which item 2 must reconcile with the door.
- **The rule the bar rests on.** `skills/review-discipline/SKILL.md` → *Bugs are filed; improvements are proposed*. Not edited by this proposal (*Not doing*). The assess bar cites it, so item 2 states the door as an addition in the assess reference and leaves the review text alone.
- **The single-instance sentence and the unstated subject.** `skills/assess/SKILL.md`, the paragraph beginning **The steward reads and reports**. The `code` row of the scope table lists the lenses.
- **Filing.** `skills/assess/SKILL.md` → *2. File the findings*; a listed risk files nothing; an approved one goes through `tracker`'s `create` with ordinary placement, never a hold (*Settled already*). Record approved risks on the report's *Filed* line so the process baseline's tickets-per-finding row still reads correctly. Retention must keep a report that still lists an undecided risk.
- **Report shape.** `templates/assessment.md`: the default shape has no *Not assessed* section, the architecture and process shapes each have one. The retention paragraph defines the `LOG.md` line and its appended fields; item 3 adds one for the area read.
- **Scope admission.** `specs/architecture-principles.md` → *Assessment layering*: a scope is admitted by its report contract. Nothing here adds a scope. The door is a second route inside the existing finding contract.
- **The four tests.** `skills/authoring/SKILL.md` → *Proposal spec*, the Migration / Blast / Access / Comprehension table. Cite it from the finding bar; do not copy it.
- **Protected areas.** `AGENTS.md` → *The contract* → *Lanes*, and the risk appetite in *Principles*.
- **Use evidence.** `skills/assess/evals/evals.json` holds two cases, `process-scope-measurements-and-doors` and `architecture-scope-may-file-nothing`. Law 2 puts guidance outside measuring tests; a case for the door is the builder's call.
- **The September decisions.** `specs/proposals/lifecycle-reset.md` (accepted 2026-09-04) and `specs/proposals/do-less-at-ingestion.md` (accepted 2026-09-07).
- **Evidence quoted in *Why*.** the Calibrate repo's code report dated 2026-11-03, at its commit `48261b268` (*Filed* line, *Why this pass*, *Not assessed*), and its architecture report dated 2026-11-10; this repo's `assessments/LOG.md` (the 2026-07-24 code line and the three process lines from 2026-08-31) and `assessments/2026-09-13-process.md`. `git log --all --since=2026-09-14 --diff-filter=A -- 'assessments/*.md'` after `git fetch --all` returned nothing.
- **Version.** Items 2 and 3 are shipped guidance; `/build` step 7 raises the plugin version. Item 2 adds an approval step and a new filing route to a pass, so run the compatibility grammar over it.
- **Planted set.** Items 1 and 4 use one branch and one set. Name the branch `spike/assess-finds-more`, push it, never merge it, and list each planted problem with its class in the item 1 ticket so item 4 reruns the same set.
