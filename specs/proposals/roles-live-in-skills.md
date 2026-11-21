---
proposal: roles-live-in-skills
status: accepted         # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-11-21
related: [research/09-skills-only-roles.md, specs/features/plugin-surface.md, specs/decisions/0021-copy-or-bridge-by-failure-mode.md]
---

# Roles live in skills; an agent file is only a runtime profile

## In brief

**So what.** The plugin runs on two hosts, Claude Code and Codex. Each of its five roles (architect, dev, reviewer, steward, harness-audit) is a sub-agent defined by a file of settings and instructions. The instructions are written twice, once per host, and one test exists only to keep the copies equal. Most of that text is already in a skill, a shared how-to file both hosts read. This proposal moves the rest into existing skills and leaves each role file its settings. No new skill is created.

**What changes.**

| Today | After |
|---|---|
| A role's instructions sit in two files, about 440 lines per host | Once, in the skill the role already reads |
| A role file is 54 to 169 lines | About a dozen: settings and a pointer |
| Setting up a repo copies in the Codex role files, which go stale | If Codex can run a role without one (step two): none copied, Codex files deleted |
| The reviewer is a separate agent that never sees the build conversation | Unchanged |

**What we need from you.** Approve the plan. Step one moves the text and thins all ten role files. Step two tests whether Codex can run a role with no role file, and deletes the Codex files only if it can. Two questions:

1. Should a role file also load the skill into the role at start, as well as pointing at it? Recommended: yes.
2. If step two's test fails: keep pointer-only Codex role files, or delete them and run every role on Codex's default model? Recommended: keep.

Main risk: a role that skips reading its skill has nothing else to go on. Question 1 addresses it.

## Settled already

| Question | Answer | Who, when |
|---|---|---|
| Should each role get a skill of its own? | No. Role content folds into the skills that exist. The goal is reduction. | Operator, 2026-11-21 |
| Is this about reaching more hosts? | No. The aim is fewer files and one copy. Reaching other hosts is not a goal. | Operator, 2026-11-21 |
| Decision 1: how does the thin Claude Code file get the skill to the role? | Both: the pointer line, plus the `skills:` frontmatter field. The builder checks by dispatching a role and confirming the skill text is present; if a plugin-shipped agent does not receive it, the pointer ships alone and the as-built record says so. | Operator, 2026-11-21, accepting as written |
| Decision 2: what happens if the Codex test fails? | Keep pointer-only `.toml` files and the hydrate copy. | Operator, 2026-11-21, accepting as written |
| Do the agent files go away entirely on Claude Code? | No. The reviewer's fresh context, its worktree and each role's tool list are set in the agent file, and nothing else sets them. | Drafting, 2026-11-21 |

## Why

A **role** is a named sub-agent that a command dispatches: `/build` dispatches `reviewer`, `/assess` dispatches `steward`. Each role is defined in an **agent file**, which holds two different things: runtime settings (model, effort, tools, isolation) and written instructions.

**The instructions exist twice.** The five role files in `agents/` hold 447 lines for Claude Code. `.codex/agents/*.toml` holds the same bodies in 437 lines for Codex. The correspondence test `test_codex_agent_adapters.py` (deleted by #813), 108 lines, compares each pair as opaque strings and fails the gate when they differ. Its own docstring says why it exists: "This pair is what is left" of four mirror sets, and deleting the generator without it "would have retired the guard along with the thing it guarded."

**The copy is forced by a limit, and the limit costs more downstream.** `.codex-plugin/plugin.json` declares one component: `"skills": "./skills/"`. A Codex plugin cannot ship agent files. So `/harness:hydrate` step 9 copies each `.toml` into the consuming repo, recognises its own copies by two different first-line markers, and rewrites them on every run. The step states the reason: the body "changes every release, so a copy nothing refreshes freezes that repo's Codex dispatch at hydration-time content with no signal." Every agent body opens with a four-line path disclaimer because "this file may be a copy vendored into" another repo.

**The bodies are mostly pointers already.** Each role file has a "Load these skills" list, and many of its remaining sentences end in a citation: `(`review-discipline` → *The verdicts*)`, `(the spine, law 7)`. `agents/dev.md` lists five things the dev does not do, and four cite a spine law that already says it.

**Five skill passages cite an agent file as the definition of something.** `skills/review/SKILL.md`, `skills/build/SKILL.md` (twice), `skills/build/references/codex-review.md` and `skills/review-discipline/references/certifying.md` each point at `agents/reviewer.md` or `agents/dev.md` for a rule. A skill depending on an agent file for content is the reverse of the direction the rest of the plugin runs.

**Doing nothing costs** a two-file edit on every role change, a gate stage that guards only the copy, a hydrate step that guards only the vendoring, and stale role text in any consuming repo between hydrations.

## Options

**Option A — leave it.** Keep both copies and the test. No work, no risk. The costs above continue, and each role change keeps paying them.

**Option B — a skill per role.** Create a `reviewer` skill, a `dev` skill and so on, and point each agent file at its skill. One copy of the content. It adds five skills to a listing every session loads, and a role skill that fires in the main conversation turns the orchestrator into the reviewer, which then needs its own switch to prevent. More parts, against a goal of fewer.

**Option C — fold into existing skills, thin the agent files (recommended).** Each sentence in a role body either has a home in a skill already, in which case it is deleted, or has none, in which case it moves to the skill that role reads. Agent files keep their settings and one pointer. The Codex files shrink the same way first and are deleted second, if a test shows Codex can run a role without them.

**Option D — no agent files at all.** Skills dispatch a generic sub-agent and brief it with the skill name. This is the fewest files. On Claude Code it gives up the reviewer's restricted tool list, its worktree isolation and its fixed model, which an agent file sets and a brief cannot.

## Recommendation

Option C, in two steps. The first needs no outside fact and delivers most of the reduction. The second depends on one test.

**The rule.** *A role's instructions live in a skill. An agent file holds the role's runtime settings and one line naming the skill, and nothing a second host would need a copy of.* This is the copy-or-bridge decision (ADR 0021) applied to roles: a copy needs a guard and a bridge does not, and a missing skill shows in the work, because a reviewer that never read `review-discipline` returns none of the three verdict words the run parses.

**Where each role's content goes.** The builder decides sentence by sentence with one test: *does a skill or the spine already say this?* If so, delete it. If not, move it here:

| Role | Content with no other home moves to |
|---|---|
| `reviewer` | `review-discipline` → *Reviewer obligations*: the packet definition, which failures are the reviewer's to fix, the "does not do" list |
| `dev` | `engineering`: the stop-and-return-DEFER rule. `build` already owns when a dev is dispatched |
| `architect` | `architecture` → *What a design produces* |
| `steward` | `assess` → *One steward, scope selects the standards* |
| `harness-audit` | a new reference file, `audit.md`, under the `hydrate` skill, whole. It is a 169-line procedure, and a reference file is where a procedure a skill dispatches belongs |
| `reviewer` and `dev`, shared | `worktree-isolation`: how a dispatched agent takes the commit its brief names. Both files carry a version of this today; it becomes one passage |

**What an agent file looks like after.** Frontmatter as now (`name`, `description`, `tools`, `isolation`, `model`, `effort`), plus the skills to hand the role (open decision 1), and a one-line body: follow the named skill section, working only from what you were handed. Role names do not change in step one, so every dispatch by name keeps working; step two, on a pass, removes the Codex custom agents and the Codex dispatch wording changes with them.

**The Codex half.** Step one gives the `.toml` files the same pointer body, so the existing test still holds and both hosts read one copy of the content. Step two runs a test in the Codex CLI: can `/build` on Codex start one of Codex's built-in agents, name the skill in the brief, and set that role's model? If yes, the `.toml` files, the correspondence test and hydrate step 9 are deleted. If no, they stay as pointers and step two closes with the result recorded.

Traces to P0 (an addition names what it retires: the one new file, `audit.md`, replaces a longer agent body), P2 (a second copy; a guard over prose), and the repo principle that a producer names no consumer, which the five skill-to-agent citations break today.

## Not doing

- **A skill per role** — adds five skills and an auto-trigger problem to a change whose goal is reduction. Reopen if a role's content cannot fit the skill it reads without pushing that skill past its size budget.
- **Adapters or support for hosts beyond Claude Code and Codex** — nobody runs the plugin there. Reopen when the operator runs it on a third host.
- **Running a skill as a forked sub-agent (`context: fork`)** — reported as silently ignored in several Claude Code releases. Reopen if a release makes it reliable and an agent file's settings become expressible from a skill.
- **Removing the Claude Code agent files** — they set the reviewer's isolation, tools and model. Reopen with the item above.
- **A generator or a roles table for the thin files** — ten files of a dozen lines have nothing to drift. Reopen if a third host needs its own role files.
- **Splitting `promote` or `tracker`** — they are large, and that is a separate change. Reopen as its own proposal.
- **A spec-validator stage in the gate for skills** — a guard for a failure not observed here. Reopen on the first malformed skill that ships.
- **Hydrate deleting Codex role files it copied into a repo earlier** — hydrate carries no transition logic by design and has no word for a deletion in its report. The audit reports the leftovers and the operator removes them. Reopen if a consuming repo cannot be cleaned by hand.
- **Changing which roles exist, their models, or when each is dispatched** — out of scope; this moves text and deletes copies.

## Open decisions

None open. Decisions 1 and 2, as *Recommendation*, *Breakdown* and *Risks* name them, were answered at acceptance on 2026-11-21 and sit in *Settled already*.

The rule in *Recommendation* is recorded in `specs/architecture-principles.md`, beside the passage that defines an agent role as "who runs it + which skills it pulls".

## Breakdown

Neither item introduces a shape the four-dimension test fires on: nothing stored is transformed, role names stay, and the files are plain text behind one dispatch each.

1. **Role content moves into existing skills; all ten role files become pointers** — apply the sentence test to the five role bodies in `agents/`; move what has no home per the table in *Recommendation*; write `audit.md` as a reference file under the `hydrate` skill and point hydrate step 13 at it; reduce each role file in `agents/` and its Codex twin in `.codex/agents/` to settings plus the pointer body, keeping the two bodies equal so `test_codex_agent_adapters.py` still passes; retarget the five skill passages that cite an agent file to the skill section that now holds the rule; update `.claude/rules/agents.md` to the new rule. **Binding rule, in full:** a role's instructions live in a skill; an agent file holds the role's runtime settings and one line naming the skill, and nothing a second host would need a copy of. No new skill is created. Role names, models, tools and isolation do not change. · shares the role files in `agents/` and `.codex/agents/`, `.claude/rules/agents.md` and `skills/hydrate/SKILL.md` with item 2 · orphans the four-line path disclaimer in all ten files, deleted by this item · `assurance:simple` · separable
2. **Codex runs roles without role files, or the result is recorded** — in the Codex CLI on this host, test whether a built-in Codex agent can be started from a skill's instruction with the role's skill named in the brief and the role's model set. On a pass: delete `.codex/agents/*.toml`, the correspondence test `test_codex_agent_adapters.py`, hydrate step 9 and the step-1 read of those files, the Codex half of `.claude/rules/agents.md`, and the README line naming the adapters; have the audit report any plugin-marked `.toml` left in a consuming repo's `.codex/agents/`; rewrite the Codex dispatch wording in `build` and `assess` to name the role's skill. On a fail: apply open decision 2, whose recommended answer changes nothing, and record the test and its result in the as-built record. **Binding rule, in full:** a role's instructions live in a skill; an agent file holds the role's runtime settings and one line naming the skill, and nothing a second host would need a copy of. Hydrate gains no step that deletes a file it copied earlier. · shares the four operands above with item 1, so it depends on item 1 · orphans `tracked_files_under`'s use in the deleted test and the `.codex/agents` entry in `tests/unit/test_seeded_assets_are_tracked.py`, both removed by this item where nothing else calls them · `assurance:complex` (it changes what hydrate writes into a consuming repo) · separable

## Risks

- **A role that skips its skill has nothing left.** Today `agents/dev.md` says "The boundaries below bind even if you skip the rest", and that list is a deliberate copy. After the change there is no copy. Open decision 1 is the mitigation; without the `skills:` field the only hold is the pointer.
- **The Codex test rests on weak evidence.** The claim that Codex can set a model when it starts a built-in agent comes from one practitioner post, not from Codex's documentation. Item 2 is built to end cleanly either way for that reason.
- **Skills grow.** `review-discipline` is 116 lines and `engineering` 137, so both have room. If the sentence test moves more than expected, a reference file under the skill takes the overflow, never a new skill.
- **A host-specific passage lands in shared guidance.** How a reviewer takes its candidate describes Claude Code's worktree behaviour. It is already written conditionally ("where the host runs you in a worktree of your own") and already ships to Codex byte for byte, so the move changes its address and not its reach.
- **Consuming repos keep stale Codex files after item 2.** They hold the last full body hydrate copied, and nothing refreshes them again. The audit names them; removing them is the operator's one command per repo.
- **A version raise.** Item 2 on a pass removes a way to dispatch a role on Codex by a custom agent name, which may be a major raise. Each review decides its own.
- **Moved text can lose its force.** A sentence that worked as a role's opening instruction may read as background inside a longer skill. The first tickets built after item 1 are the test; a reviewer that returns something other than one of the three verdict words, or a dev that edits a locked test, is the signal to revert.

## For the builder

Read against `e1924d9d` on `claude/skills-only-roles-harness-ebf567`.

- **Role files.** In `agents/`, for architect, dev, harness-audit, reviewer and steward in that order: 57, 72, 169, 93, 56 lines. `.codex/agents/*.toml`: 55, 70, 167, 91, 54. Frontmatter fields in use: `name`, `description`, `tools`, `isolation` (`worktree` for architect, dev, reviewer; `shared` for steward, harness-audit), `model` (`opus`, except `harness-audit` on `sonnet`), `effort: high`.
- **The correspondence test.** `test_codex_agent_adapters.py` (deleted by #813) reads both operands through `indexed_text` and refuses an empty body on either side, so a pointer body must be non-empty and equal in both files. Admitted under ADR 0017 D5 class (e).
- **Skill passages citing an agent file.** `skills/review/SKILL.md` step 3 ("the packet `agents/reviewer.md` → *Your context is the packet* defines"); `skills/build/SKILL.md`, the *You are the builder* bullet and the review-stage paragraph; `skills/build/references/codex-review.md`; `skills/review-discipline/references/certifying.md`. Find them with `git grep -nE 'agents/[a-z-]+\.md' skills`.
- **Sections that receive content.** `skills/review-discipline/SKILL.md` → *Reviewer obligations*; `skills/engineering/SKILL.md` → *Evidence before implementation* and *Verification*; `skills/architecture/SKILL.md` → *What a design produces*; `skills/assess/SKILL.md` → *One steward, scope selects the standards*; `skills/worktree-isolation/SKILL.md`, which already says what "a reviewer or a dispatched `dev`" does on meeting a red base.
- **Hydrate.** Step 9 (*Hydrate Codex role adapters*) and step 1's read of `.codex/agents/*.toml` and their first lines; step 13 dispatches `harness-audit` by name and already tolerates a host that reports no such agent. Step 9 recognises two markers: `# Codex's native adapter for the role in` and the legacy `# Generated by` line naming the generator script #537 deleted. The audit's leftover check in item 2 uses the same two.
- **Other references.** `.claude/rules/agents.md` (scoped to `agents/**` and `.codex/agents/**`, states the mirror rule and the path convention); `README.md`, the line "Codex role adapters in `.codex/agents/`"; `tests/unit/test_seeded_assets_are_tracked.py`; `CLAUDE.md`, the *Sub-agents* delta; `specs/harness-assumptions.md` → *Agents*, whose rows name roles and stay true; `specs/architecture-principles.md`, the paragraph beginning "A unit of repeatable work decomposes into four durable artifacts".
- **Manifests.** `.claude-plugin/plugin.json` declares no component paths and takes `agents/` by convention. `.codex-plugin/plugin.json` declares `"skills": "./skills/"` and nothing else. Both at `37.0.0`.
- **Codex CLI.** Present on this host at `~/.local/bin/codex`, so item 2's test can run here.
- **Source research.** `research/09-skills-only-roles.md` holds the cross-host survey this proposal draws on. Its evidence that bears on the decision is restated above.

---

**Lifecycle.** Accepted 2026-11-21 by the operator, as written. Spawned umbrella #811 with children #812 (breakdown item 1) and #813 (item 2, blocked by #812). It becomes **shipped** once those have landed.
