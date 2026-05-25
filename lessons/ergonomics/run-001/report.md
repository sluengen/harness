# Workflow Author Ergonomics — Run 001

**Date:** 2026-05-25
**Mode:** Smoke (Scenario A only — first run of the new skill)
**AUTHORING.md SHA:** [pre-this-PR baseline — agent read the version merged in PR #29]
**Linear:** CAL-391 (acceptance via skill, see closing note)
**Skill:** `.claude/skills/workflow-author-ergonomics.md` (new in this PR)

## Verdict

**PASS** — workflow validates, zero `blocker` pain points, agent stayed within the AUTHORING.md-only constraint.

## Scenario A — informational, 3 stages

> Pull Notion pages tagged `release-notes` from the last N days, summarise into markdown grouped by tag, write to disk.

| Field | Value |
|---|---|
| Sub-agent | `general-purpose` (fresh context) |
| Files read | `AUTHORING.md`, `prompts/standard/summarize.j2` |
| Workflow produced | `.harness/ergonomics/run-001/scenario-A.yaml` |
| Step shape | `script` → `ai` → `script` (matches expected canonical) |
| Standard prompt | `prompts/standard/summarize.j2` (used correctly with `subject` + optional `length`) |
| Validation | ✓ `load_workflow()` returns a clean `Workflow` |
| Workflow name | `notion_release_notes_digest`, version 1, 3 steps |

### Pain points logged

| # | Severity | Section | Summary |
|---|---|---|---|
| 1 | confusing | §2 step types / §7 worked example | `agent`/`model` on `ai` step — §2 lists only `prompt`/`contract` as required; §7 includes `agent: claude` + `model: sonnet`. Agent had to guess they were safe. |
| 2 | confusing | §4 / §7 | Write-file step in §7 takes `--output-path` as input AND declares `output_path` in contract — circular. The "script computes its own path from `$state.run_id`" pattern isn't explicit. |
| 3 | minor | §4 Variable references | `$`-substitution inside `template_vars` string values is shown by example in §7 but not explicit. **Fixed in this PR.** |
| 4 | minor | §5 Standard prompts | §5 table only shows required `template_vars`. Optional ones (e.g. `length` for summarize.j2) require reading the `.j2` header to discover. |
| 5 | minor | §3 Inline contracts | "Three primitive types" sentence then lists four. **Fixed in this PR.** |
| 6 | minor | §7 Worked example | Pattern for "scripts receiving large state values" (flag vs stdin vs reading from state file) not shown. Agent guessed `--content` flag. |

### Self-assessment quote from agent

> "I believe the workflow loads. Required workflow-level fields (name, version, steps) are present; each step has id/type/contract/writes with names matching contract field names exactly; the AI step uses prompts/standard/summarize.j2 with its required `subject` template var; no worktree/loop/decision used as the scenario specifies a 3-stage informational workflow. The one area I'm least certain about is whether `agent`/`model` on the ai step are required defaults — I included them mirroring §7."

## Aggregate metrics

- Scenarios run: 1 of 3 (smoke check)
- Validation pass: 1 / 1
- Total pain points: 6 (0 blocker / 2 confusing / 4 minor)
- Constraint adherence: ✓ (agent consulted only AUTHORING.md + the cited prompt header)

## Fixed in this PR (trivial)

- §3 — "Three primitive types" → "Four primitive types" (cosmetic typo)
- §4 — One-line clarification that `$`-substitution happens inside any YAML scalar string including `template_vars` values

## Recommended follow-up (next AUTHORING.md PR)

The two `confusing` findings need small design calls before fix:

- **§2 / §7 — `agent` and `model` required-ness.** Decide: are they required on `ai` steps, or do they have framework defaults? Update §2 table accordingly. (My read: they should have framework defaults — `agent: claude`, `model: sonnet` — so the guide can drop them from required and add a "Defaults" note. But that's a choice that should be confirmed by a real engine read, not in this PR.)
- **§7 — write-file pattern.** The `--output-path` input + `output_path` contract pattern is technically valid but reads circular. Either show two patterns side-by-side ("caller-provides-path" vs "script-derives-from-run-id") or pick one canonical and stick to it.

Both are doc-only changes — no engine work needed.

The four `minor` findings (now reduced to 2 unfixed):

- Optional `template_vars` could be surfaced in §5 table (1-line addition per prompt)
- Pattern for scripts receiving large state values could be added to §7 (one-paragraph addition with a concrete example)

## What this proves about the skill itself

- ✓ The protocol works end-to-end (dispatch → constraint adherence → structured report)
- ✓ The validation gate (`load_workflow()` succeeds) is the right pass/fail signal
- ✓ The pain-points structure (severity + section + description) produces actionable findings on first run
- ✓ Reproducible — re-running on a different AUTHORING.md version will surface a different (or shorter) list

What we still need before treating this as a complete validation:

- **Run Scenarios B (code-mutating 4-stage) and C (loop pattern)** in a follow-on session. Same protocol, different scenarios, different surface coverage. The smoke check passes but the full suite hasn't run yet.
- The follow-on can be triggered any time by reading `.claude/skills/workflow-author-ergonomics.md` and dispatching three `general-purpose` sub-agents in parallel.

## Closing note on CAL-391

CAL-391 originally specified a human author re-testing the 10-minute bar against SPEC.md. That mandate was already revised (PR #29 → AUTHORING.md became the test reference). This run further revises the acceptance: instead of a one-shot human test, CAL-391 is closed by:

1. **AUTHORING.md exists and is the canonical author reference** (PR #29 ✓)
2. **A reproducible ergonomics-check skill exists and runs cleanly on Scenario A** (this PR)
3. **The skill is documented for future re-runs** (`.claude/skills/workflow-author-ergonomics.md`)

The skill substitutes the "one human, one moment" measurement with "any agent, any time, with regression catch." Less precise on cognitive friction; far more precise on testable surface bugs (validation failures, undocumented fields, ambiguous syntax). For an evolving tool, that trade is worth making.

If at any point a real human attempts to author from blank and finds the guide too heavy, the canonical response is "open a Linear issue, update AUTHORING.md, re-run the skill, see findings drop." The skill is the regression net; humans report into it.
