# Assessment log

A rolling one-line record of every **superseded** assessment report — those
folded out of `assessments/` under the retention convention
(`templates/assessment.md`, `commands/assess.md`). The directory itself keeps
only the **latest report per scope** plus **any report with an open finding**;
when a report is neither, it folds into a line here and its file is removed, so
`assessments/` stays a live index rather than a growing pile.

Entries are chronological (oldest first); each new fold appends below. Format:

`- <YYYY-MM-DD> · <scope> · <one-clause verdict> · findings: <resolved / ticketed>`

**Each entry preserves the scope vocabulary in force when that pass ran**, so
`system`, `code-deep`, and the same-day `-am` / `-pm` / `-eve` stems appear below
even though ADR 0015 narrowed `/assess` to `code | architecture`. They are
records of passes that really happened, not instructions — restating them in
today's vocabulary would falsify the audit, so a stem here is read as history and
never as a scope you can still run.

Every report folded below had **no open finding** at fold time — verified against
the tracker, not assumed. (First fold, CAL-1089: AC-3 named `2026-07-02-code.md`
as a keep "while CAL-937 is open", but that report's own finding is CAL-866, and
both CAL-866 (Done) and CAL-937 (Canceled) are closed — so by the rule as written
it folds too, and the kept set is exactly the latest report per scope. All 85
findings referenced across the folded reports were confirmed completed/canceled.)

---

- 2026-06-11 · code · initial adversarial steward pass (post PR #70); caught the close-gate dirty-worktree bypass and a README/CONTEXT/engine-spec doc-drift cluster · findings: CAL-586–603 ticketed, resolved
- 2026-06-11 · code-verify · verification sweep confirming the 06-11 findings and their fixes · findings: ticketed, resolved
- 2026-06-12 · code-initial · first 06-12 pass over the hardening tree · findings: ticketed, resolved
- 2026-06-12 · code · clean on the dimensions recent tickets hardened (CLI-surface lock, git-helper dedup, query split) · findings: ticketed, resolved
- 2026-06-12 · code-reassessment · reassessment after the day's fixes · findings: ticketed, resolved
- 2026-06-12 · code-reassessment-3 · CODE-1/CODE-2 filed and actioned in the same change · findings: CAL-625/626, resolved
- 2026-06-12 · code-reassessment-4 · CAL-625 reopened and re-actioned in the same change · findings: CAL-625, resolved
- 2026-06-12 · code-reassessment-5 · one Low finding found and actioned in the same change · findings: CAL-620, resolved
- 2026-06-12 · code-reassessment-6 · fifth pass of the day; tree genuinely healthy (ruff/mypy clean) · findings: ticketed, resolved
- 2026-06-13 · code · a CODE-1 finding actioned; an insight decision-flagged (CAL-633) · findings: CAL-632/633, resolved
- 2026-06-13 · code-reassessment · further findings actioned, one deferred to preserve atomicity · findings: CAL-634/635, resolved
- 2026-06-13 · code-reassessment-d · steward pass on the assess/code branch; gate green · findings: ticketed, resolved
- 2026-06-13 · code-reassessment-e · gate PASS (598 tests) · findings: ticketed, resolved
- 2026-06-15 · code · gate PASS (771 tests) · findings: ticketed, resolved
- 2026-06-15 · code-reassessment · gate PASS (924 tests) · findings: ticketed, resolved
- 2026-06-15 · code-reassessment-2 · gate PASS (927 tests); zero findings · findings: none
- 2026-06-15 · system-and-code · broad pre-deploy read before onboarding the surface into another repo · findings: CAL-574, resolved
- 2026-06-16 · code · tree clean; all eight refactors landed with no dangling references · findings: CAL-712–719/731, resolved
- 2026-06-16 · code-reassessment · reclamation workstream clean and consolidating rather than duplicating · findings: ticketed, resolved
- 2026-06-16 · code-reassessment-2 · clean at dev HEAD; only delta is the CAL-746 fix · findings: CAL-746/747, resolved
- 2026-06-16 · code-deep · deep pass: codebase clean, strong coverage of the reclamation surface · findings: CAL-734/735/738, resolved
- 2026-06-16 · mode2-dryrun · re-bootstrap works and is gitignore-safe; a pre-merge install migrated cleanly · findings: CAL-748/749/750, resolved
- 2026-06-20 · code · healthy; five shipped tickets landed cleanly with guard tests · findings: CAL-800/810/811/815/816, resolved
- 2026-06-24 · code · healthy; the one production change (CAL-866 sandbox-init detection) sound · findings: CAL-829/834/835/866, resolved
- 2026-07-02 · code · tree healthy; loop-hardening well-built, the breaker decision extracted to a pure unit-tested module · findings: CAL-866 (Low), resolved
- 2026-07-06 · code · tree healthy; incremental pass, no new findings; two minimal production deltas (CAL-935, CAL-941) · findings: none new (prior CAL-935/937/941/979 all closed)
- 2026-07-17 · code · tree healthy; 07-15 backlog fully drained (CODE-1/2/INSIGHT-2 fixed at root), gate green at `d484116` · findings: none new
- 2026-07-18 · code · tree clean; CAL-1151 (unsafe-base-checkout refusal) + CAL-1158 (staging direct-push) landed sound, gate green at `1b4a12f` (1955 tests) · findings: none new
- 2026-07-19 · code-am · earlier 2026-07-19 pass (tick #58), superseded same day by the kept `2026-07-19-code.md` (tick #60); recorded here to keep the earlier zero-finding pass on the log without colliding with the kept report's `code` stem · findings: none new
- 2026-07-19 · code · tree healthy after CAL-1149 (doctor wrapper-drift check); one finding, CHANGELOG.md at 536 B headroom against its 60,000-byte gate · findings: CAL-1182, resolved (fold landed the next day, commit `208118e`)
- 2026-07-15 · code · force-push guard recognised only the `env` wrapper (siblings passed a literal `--force`) and the assessments/ retention convention itself had never been applied (28 reports, no LOG.md — this pass created it); retention gap: the report stayed on disk unfolded through three later `code` passes until this fold · findings: CODE-1/2/INSIGHT-1/INSIGHT-2, resolved (drained by the 2026-07-17 pass)
- 2026-07-23 · code · tracker-protocol growth (Tracker/release verb, `/decision`) landed clean; two findings, both process/doc drift not code defects · findings: CODE-1 (CHANGELOG.md byte-gate headroom) resolved via #195 soft-warning threshold, CODE-2 (RELEASING.md describing the retired Linear tracker) resolved via #196
- 2026-07-24 · code · tree clean, zero findings (`harness/`/`tests/` unchanged since the prior pass) · findings: none new
- 2026-06-19 · code-deep · the last `--deep` pass; SPEC §1 principle 5 hand-listed a stale partial verb surface one section over from the §4.1 drift CAL-746/747 had already fixed · findings: CODE-1 + CODE-INSIGHT-1, both resolved — §1 now defers to the §11 surface rather than re-listing it, and `test_cli_surface_locked.py` locks *every* live SPEC section against the enumeration idiom instead of section-by-section
- 2026-07-25 · code · two abandoned promotion worktrees at a non-canonical path inside `harness/` contaminated four tree-walking test guards; root cause was `resolve_repo_root` accepting any resolvable path, not just a git top-level · findings: CODE-1/CODE-2 → #214/#215, both resolved; CODE-INSIGHT-1 shipped as #214
- 2026-07-26 · code-am · the earlier same-day pass (tick #107's idle arm), superseded the same day by the kept `2026-07-26-code-eve.md` at a moved HEAD; recorded here under an `-am` stem so the earlier pass keeps its record without colliding with the kept report — the design-verb chain's first sweep after ADR 0007 completed · findings: CODE-1/2/3 → #217/#218/#219, CODE-INSIGHT-1/2 → #220/#221, all resolved and shipped
- 2026-07-26 · code-pm · the second same-day pass (tick #110's idle arm), superseded the same day by the kept `2026-07-26-code-eve.md` at a moved HEAD; recorded here under a `-pm` stem so the pass keeps its record without colliding with the kept report — found the four-way Typer-surface duplication #219's own fix had widened · findings: CODE-1 → #222, resolved and shipped
- 2026-07-26 · code-eve · third pass of the day; the four-verb lifecycle stale across four live canonical documents including the as-built record, plus a narrowed adoption-lock predicate · findings: CODE-1 → #224 (+ #228 from CODE-INSIGHT-3), CODE-2 → #225, all resolved and shipped
- 2026-07-29 · code · tree healthy at source level; all three findings were documentation/process drift, and the sharpest was architectural-process — two changes touched named `architecture_watchlist` gravity wells with no recorded `Watchlist trigger`, and `close.py` had regrown to exactly its 500-line hard limit with no `# size:` marker · findings: CODE-1 → #249, CODE-2 → #250, CODE-3 → #251, CODE-INSIGHT-1 → #252, CODE-INSIGHT-2 → #253, all resolved and shipped
- 2026-08-01 · code-am · the earlier same-day pass (tick #152's idle arm), superseded the same day by the kept `2026-08-01-code.md` at a moved HEAD (`42c84b0` → `f2b67cd`); `CLAUDE.md`'s `architecture_watchlist` prose was stale for both gravity wells and factually wrong for `close.py` (claimed the `# size:` marker retired at ~450 lines; the file was 531 lines with a marker at `:112`) · findings: CODE-1 → #272, CODE-INSIGHT-1 → #273, both resolved and shipped
- 2026-08-01 · code · the second same-day pass (tick #154's idle arm), superseded the same day by the kept `2026-08-01-code-pm2.md` at a moved HEAD (`f2b67cd` → `08d0401`); pushed the structure and test-health lenses into the test tree for the first time and found the size guard's year-old `tests/` deferral had never been decided, leaving 14 files past the declarative ceiling · findings: CODE-1 → #274, CODE-2 → #275, CODE-3 → #276, CODE-INSIGHT-1 → #277, CODE-INSIGHT-2 → #278, all resolved and shipped
- 2026-06-19 · system · mechanically coherent guidance with one distributed-prose ticket-ID leak; superseded by the 2026-08-04 system pass after the leak was removed from the live tree · findings: SYSTEM-1 / SYSTEM-INSIGHT-1 resolved
- 2026-08-01 · code-pm2 · the third same-day pass (the routine's idle arm), superseded by the kept `2026-08-04-code.md`; healthy — it confirmed the five-ticket batch had landed as claimed, and three of its four findings were one class, a field or list asserted to exist but never measured · findings: CODE-1/2/3/4 → #279/#280/#281/#282, CODE-INSIGHT-1/2/3 → #283/#284/#285, all seven closed
- 2026-08-04 · code · the last runtime-era deep pass (deleted `harness/` package, 95.08% coverage): highly verified but with accumulated drag — an unconditional 747-line design-stage spend, promotion escalation bypassing the tracker seam, and guards narrower than their names; superseded by the kept `2026-08-17-code.md`, the first post-teardown pass · findings: CODE-1..6 → #328/#332/#335–#341, all closed (#335 NOT_PLANNED in the ADR 0015 sweep; its surviving subject refiled by the 2026-08-17 pass as #466)
- 2026-08-04 · system · the last `system`-scope pass, run before ADR 0015 retired the stem: the mechanical distribution layer healthy (84 focused integrity tests green) and the semantic process on top of it not — a tracker migration that had reached configuration but not the lifecycle, two simultaneously-normative review stop rules, mutually exclusive decision-storage contracts, and a final review that did not cover the final commit; folded under the retired-scope clause rather than by supersession, since no later pass can carry the stem, and #458's provenance annotation lapsed when the two guards citing SYSTEM-1 and SYSTEM-3 went in the v5 guard cull · findings: SYSTEM-1..6 → #327/#329/#330/#331/#332/#333 and SYSTEM-INSIGHT-1/2/3 → #342/#343/#344, all nine closed (CODE-4 framed the set as the contiguous range #327–#334; #328 and #334 are the same day's `code` and `architecture` passes, not this one)
