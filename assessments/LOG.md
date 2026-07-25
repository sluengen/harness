# Assessment log

A rolling one-line record of every **superseded** assessment report — those
folded out of `assessments/` under the retention convention
(`templates/assessment.md`, `commands/assess.md`). The directory itself keeps
only the **latest report per scope** plus **any report with an open finding**;
when a report is neither, it folds into a line here and its file is removed, so
`assessments/` stays a live index rather than a growing pile.

Entries are chronological (oldest first); each new fold appends below. Format:

`- <YYYY-MM-DD> · <scope> · <one-clause verdict> · findings: <resolved / ticketed>`

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
