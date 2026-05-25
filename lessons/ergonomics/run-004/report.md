# Workflow Author Ergonomics — Runs 002, 003, 004 (full cycle)

**Date:** 2026-05-26
**Mode:** Full suite (Scenarios B + C) — catch → fix → confirm
**Linear:** CAL-391 (acceptance via skill)
**Skill:** `.claude/skills/workflow-author-ergonomics.md` (shipped PR #36)

## Verdict

**PASS** after one fix cycle. The skill demonstrated its value by catching a real undocumented engine constraint that escaped run-001.

## The cycle, in one paragraph

run-002 dispatched both Scenarios B and C against `AUTHORING.md` as merged in PR #29. Both **FAILED validation** — same root cause, surfaced independently by two parallel sub-agents: the guide showed `worktree.create` with `writes: [worktree_path, worktree_branch]` but no `contract:`, and the loader's "every step that writes state has a contract" cross-validation rejected both workflows. Wrong fix attempted in run-003 (added explicit contract field) — failed differently because `WorktreeStep`'s Pydantic schema doesn't allow a `contract:` field at all (extra-forbidden). The correct fix: `worktree` steps need **neither** `contract:` **nor** `writes:` — the framework writes `worktree_path` + `worktree_branch` directly into `BaseState`, available to downstream nodes via `$state.worktree_path` etc. Applied to AUTHORING.md, re-ran as run-004: **both PASS**, 0 blockers, 5 minor/confusing refinements logged.

## Per-run results

### run-002 (initial, baseline AUTHORING.md from PR #29)

| Scenario | Validation | Blockers | Confusing | Minor |
|---|---|---|---|---|
| B (4-stage code-mutating) | ✗ FAIL — `step 'setup-worktree' declares writes but has no contract` | 2 | 3 | 3 |
| C (loop pattern) | ✗ FAIL — same root cause | 1 | 2 | 3 |

Both sub-agents independently concluded that `worktree.create` should write `worktree_path` and `worktree_branch` — but neither could find guidance on the contract requirement that the engine then demanded. **The agents reasoned correctly; the guide was wrong.**

### run-003 (wrong-fix iteration — added explicit contract)

First repair attempted: edit AUTHORING.md to show `contract: { worktree_path: string, worktree_branch: string }` on `worktree.create`. The agents dutifully copied the new pattern. Re-validated: both FAIL with `Extra inputs are not permitted [type=extra_forbidden]` — `WorktreeStep`'s Pydantic model rejects the `contract:` field outright. The right pattern is "neither contract nor writes," not "contract and writes." Artifacts kept in `lessons/ergonomics/run-003/` as honest history.

### run-004 (correct-fix iteration — drop contract and writes)

Final repair: AUTHORING.md updated to show `worktree.create` with no `contract:` and no `writes:`, with an explicit note that `worktree_path` + `worktree_branch` become available as `BaseState` fields (referenced via `$state.X` downstream). Updated §10 pitfalls accordingly.

| Scenario | Validation | Blockers | Confusing | Minor |
|---|---|---|---|---|
| B | ✓ PASS — 9 steps validated cleanly | 0 | 2 | 3 |
| C | ✓ PASS — 5 steps validated cleanly | 0 | 2 | 3 |

## Findings landed in this PR

The following were folded into AUTHORING.md as part of the run-002 → run-004 cycle:

| Section | Change | Source finding |
|---|---|---|
| §2 worktree example | Removed `contract:` and `writes:`; added note about `BaseState` auto-population | run-002 blocker (both B + C) |
| §10 pitfalls | New row: `worktree.create` step has `writes:` or `contract:` → loader rejects either | run-002 blocker |
| §10 pitfalls | New row: no multi-branch routing from a single `check` → canonical workaround | run-002 blocker (C) |
| §2 ai example | Added optional-keys line: `agent` default `claude`, `model` default `sonnet`, `allowed_tools` default `[Read, Grep, Glob]`, plus `cwd`/`writes_files`/`stall_timeout_s`/`timeout_s` defaults | run-001 + run-002 (B) |
| §2 script | Added bash form example contrasted with python form | run-002 blocker (B) |
| §2 loop example | Added note about `until:` accepting truthy expression; state persistence across iterations | run-002 confusing (C) |
| §2 worktree | Added `merge_to_base` semantics paragraph (assumes branch already committed) | run-002 confusing (B) |
| §4 variable references | New explicit substitution table — args/command/cwd/base/template_vars values | run-002 confusing (both) |
| §5 standard prompts | Added optional `template_vars` column (`tools_hint`, `constraints`, `severity_levels`, `length`) | run-001 minor |

## Findings logged for the next AUTHORING.md PR (not in this one)

Lower-severity items that came out of run-004 and didn't block:

- **Multi-line `command:`** — `$`-substitution table doesn't address whether `command: |\n  multi-line` substitutes the full block before bash sees it. (Both B and C flagged independently.)
- **`merge_to_base` and remote push** — clarification text says "engine fetches latest before ff-merge," which implies the worktree commit may need to reach remote first. The example says "or just git add/commit, since the engine fetches latest." These could be reconciled. (B confusing + C minor.)
- **`commit before merge_to_base` is implicit in loop bodies** — when a loop's `implement` step uses `implement.j2` with `writes_files: true`, the body doesn't commit. An explicit `git add/commit` script step is needed before `merge_to_base`. The example in §2 worktree mentions this as "typically created by a preceding script step" but the loop example doesn't show it. (C confusing.)
- **Cancel-time worktree disposition** — the §10 branching workaround leaves the failed worktree on disk because `cleanup` never runs on the cancel path. Could note this and suggest a periodic cleanup pattern. (C confusing.)
- **`allowed_tools` merge vs replace** — when you set `allowed_tools: [Read]`, does it replace the default `[Read, Grep, Glob]` or add to it? Loader almost certainly replaces but isn't documented. (B minor.)
- **Enum syntax inconsistency** — `{ type: string, enum: [...] }` (inline) vs block form. Both work; pick one canonical. (B minor.)
- **First-iteration `until:` evaluation** — when does `until:` first fire? Before the first body run or after? (C minor.)

All seven are low-cost fixes for a future doc PR. None warrant another full re-run cycle now.

## What this proves about the skill

- ✓ The skill found a real engine/doc disagreement that had escaped review (PR #29 merged with the bug intact)
- ✓ Parallel sub-agents independently surfaced the same blocker — the constraint isn't agent-specific noise
- ✓ The catch→fix→confirm cycle worked end-to-end in three iterations (~30 min total)
- ✓ A wrong fix attempt was caught by the same skill, not by ad-hoc testing
- ✓ run-004's 0-blocker result demonstrates the corrected guide is now self-sufficient for the two complex scenarios

## Follow-up engine work (separate Linear issue to be filed)

The cycle surfaced a real engine inconsistency worth fixing:

- The loader's `writes-needs-contract` cross-validation fires on `worktree.create` (which has framework-managed writes outside the normal contract pathway). Either:
  - Loader excludes `worktree` steps from that check (simpler), OR
  - `WorktreeStep` exposes an implicit/auto-generated contract that satisfies the check (more consistent)

Either fix would let the AUTHORING.md `worktree` example return to looking like a normal step (with `writes:`), reducing one piece of special-case knowledge an author has to learn. Not blocking for v1 — the current guidance ("worktree steps are framework-managed special-case, no contract no writes") is workable.

## Closing on CAL-391

CAL-391 acceptance reframed (per PR #36): substituted the one-shot human test with a reusable skill. This cycle is the first end-to-end demonstration that the substitution works — caught a real bug, drove a fix, confirmed the fix.

Run cadence going forward: re-run the skill after any AUTHORING.md edit, after any `harness/workflow/schema.py` or loader edit, and as a quarterly canary. New blockers should fire the same catch→fix→confirm cycle this run demonstrated.
