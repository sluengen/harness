---
proposal: lifecycle-reset
status: accepted         # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-04
decided: 2026-09-05
related: [drift-reconvergence, structured-explorer-and-repair-build-loop, purpose-before-proof, plugin-surface]
research: research/INDEX.md
---

# Proposal: reset the lifecycle, top to bottom, on five lean principles

> Longer cycle times and ballooning work are one feedback loop. This proposal restates the principles as lean applied to agent-driven repos, each able to refuse something, redraws the lifecycle as three lanes sized by blast radius, moves spend from downstream detection to upstream prevention, deletes the machinery that re-implements the host, and ships with the measurements that would show it working or not. The landing posture decided on 2026-09-04 is carried unchanged.

## Problem / motivation

Two symptoms, reported across consuming repos:

1. **Longer cycle times**, with the waste that follows: tokens, merge contention, lost time.
2. **Ballooning complexity and work creation.** Every ticket discovers small things; the small things go on a ledger; architectural decisions are less principled than they could be.

They are one loop. Guards and tickets accumulate, the gate lengthens, the window in which concurrent work collides widens, collisions produce rework, rework discovers more small things, and those become more guards and tickets.

### Measured, 2026-09-04

Derived on this date with the commands named. Every figure is a starting line for the measurement section below.

| Signal | harness | calibrate | nano-erp | How derived |
|---|---|---|---|---|
| Commits on the integration branch, 6 weeks | 725 | 757 | 745 | `git rev-list --count --since='6 weeks ago' origin/dev` |
| Of which reconciliation merges (integration branch merged *into* a work branch) | 64 (9%) | **173 (23%)** | 93 (12%) | `git log --merges` subjects containing `into` |
| Gate stages | 6 under `uv` | 14 under `docker compose` | build + 8 under `npm` | `scripts/verify.sh`, `package.json` |
| Gate duration recorded in the marker | none | none | none | `<git-common-dir>/harness/gate/*.json` carries `finished_at` only |
| Always-on spine | 98 lines | 178 lines | 143 lines | `wc -l CLAUDE.md` |
| Test lines : source lines | 21,065 : 9,417 (`tests/unit` : `scripts` + `hooks`) | — | 67,846 : 32,065 | `wc -l` |

Inside the harness itself, the plugin carried **28 skills**, of which 9 were generated `command-*` mirrors of the 9 command files (621 lines) and 4 were generated `agent-*` mirrors of the 4 agent files (171 lines); a 375-line generator, a gate stage, and tests existed to keep those mirrors byte-faithful. The 5 hooks are 2,859 lines of JavaScript. The build workflow was 143 lines of normative procedure read once at the start of a run that then spans many sub-agent contexts. The review loop reached cycle 4 on twelve recorded occasions and cycle 5 on two; #510 took seven. Median ticket open-to-close over the last 200 closed tickets is 16.8 hours.

The prior version of this proposal measured the guard ratchet directly: 151 test modules before the v5 cull, 25 after it, 45 fourteen days later. **A cull without a stated basis for refusal resets the counter and changes nothing else.** That basis is what the principles below supply.

### What the research adds

*research/* (September 2026, evidence-tagged, untracked at acceptance) changes the diagnosis in four ways:

- **Ambiguity is the precondition for cheating.** Clear reward hacking runs at 0.7–3.4% on unambiguous tasks and 22–44% on ambiguous ones (EvilGenie; ambiguous set n=9, direction strong, magnitude not). The harness spends heavily on detecting bad work downstream and little on removing ambiguity upstream.
- **Instruction does not stop test modification.** Claude models concentrate over 79% of their cheating in editing tests directly, despite explicit instructions (ImpossibleBench). Read-only tests during implementation is the single highest-yield missing control, and it belongs in a hook, not a sentence.
- **Guidance is verified by use.** Anthropic's published skill loop is: evaluations first, the minimum instructions that pass them, iterate on observed behaviour. This is the answer to "how do you test a process document", and it is the capability the harness lacks. It also explains why the prose guards regrew: nothing else was available.
- **Harnesses are pruned as models improve.** "Every component in a harness encodes an assumption about what the model can't do on its own." Anthropic deleted its own sprint layer when a model made it unnecessary. Nothing in this repo names the assumption each component encodes, so nothing can retire one.

## The principles

Lean, applied to agent-driven repos. Each states what it rules out, because a principle that cannot refuse anything is a preference. The operator's original five and the six of the first revision fold into these; the mapping is recorded below so nothing decided under the earlier numbering is lost.

**P1. Build quality in.** Right first time. Clarity before build, tests before code, a probe before a write-up. Every stage ends on a pass/fail signal the agent can act on alone; evidence over assertion; enforcement on the lowest rung that can hold it (branch protection, then a hook, then prose). *Refuses:* a downstream detector for an upstream ambiguity; a stage that ends when the model feels finished; a "law" that is actually a request.

**P2. Reduce waste.** Native first: the host already plans, interviews, isolates, forks, sets effort and model, stops turns, scopes rules, runs evals, and sandboxes; re-ask on every release. Less is more: an addition names what it retires. Assurance is proportionate to blast radius, and every ticket, guard, or gate stage carries its cost and benefit at creation, weighed on four axes: quality, speed, cost, risk. The wastes this work produces, named so a reflection can name them: **rework** from ambiguity or a red base; **waiting** on a gate, a review cycle, or the operator; **over-processing**, ceremony that proves a stage ran; **over-production**, work nobody asked for, findings turned into tickets; **motion**, context reloaded or re-discovered; **inventory**, a backlog or ledger nobody drains; **defects** that reach the integration branch. *Refuses:* a parser, generator, or guard that re-implements a host feature; a second copy; a guard over prose; a ticket for a one-line fix; a guard for a risk never observed; an uncomputed cost; a stage whose benefit cannot be told from noise (about 3 percentage points on any agent eval).

**P3. Flow.** Work moves in small batches through explicit dependencies. Split so nothing waits on a blocker it does not need; run independent work in parallel; an interim state need not be shippable when nothing pulls it; land without an exponential; keep the queue's growth rate visible. *Refuses:* a chain where a fan-out would do; a serialised landing; a ticket split only so its interim state is workable; an invisible backlog.

**P4. Stop the line.** When continuing would compound a defect, pause. A red integration branch, criteria that contradict each other, a protected area reached, a review that is not converging, a lost claim, an instruction arriving in data: each is an andon pull, and the response is a typed hold that says why, what is needed, and what was preserved. **An open P1 bug is the cord for the whole repo: nothing else starts until it is cleared.** *Refuses:* pushing through a red base; guessing where a hold is due; a fresh loop under a new name; a queue that keeps flowing past a defect it is compounding.

**P5. Continuous improvement.** Every build ends with a short reflection that names the wastes it met and files what should change: to the repo's improvement ledger, or to the harness's own ledger when the improvement is to the guidance, hooks, or skills the plugin ships. `/assess` drains the ledger and decides each entry, do, fold, or drop, explicitly. The retirement table names the model limitation each component assumes and what would retire it; guidance is verified by evals, not by reading. *Refuses:* an improvement that goes nowhere; a lesson learned twice; a cull without a stated basis for refusal; a reflection long enough to be its own waste.

### Mapping from the earlier numbering

| Earlier (2026-09-04 revision) | Now |
|---|---|
| 1 Native first · 2 Balance the four axes · 3 Less is more · 5 Proportionate assurance | **P2 Reduce waste** |
| 4 Right first time · 6 A stage is its exit check | **P1 Build quality in** |
| not stated | **P3 Flow** · **P4 Stop the line** · **P5 Continuous improvement** |

### Principles and laws

They are different kinds of statement and the spine keeps both. A **principle** decides what gets built and what does not: a proposal, a guard, a gate stage, or a ticket cites the principle it serves and the one it spends against, by number, and a reviewer of any process change checks the citation. A **law** is a per-change obligation every agent follows, enforced by a hook where one can hold it. Principles come first in the spine because the laws are derived from them; a law that traces to no principle is retired.

The six current laws survive that test. Three are rewritten to one line each, because a 130-word law containing eight obligations is packaged so that the ones dropped are unpredictable; rationale moves to an HTML comment, which is stripped before injection and so costs nothing.

| Law today | Traces to | After |
|---|---|---|
| 1. Purpose precedes proof (about 130 words) | P1, P2 | *Name what a check protects before writing it; choose the cheapest evidence that can fail for that reason (ADR 0019).* |
| 2. A measurable executable criterion needs a measuring test | P1 | *A quantitative criterion about code has a test that measures it.* |
| 3. No completion claim without fresh gate evidence | P1 | Kept, restated in authored-tree terms under the landing posture. The Stop hook and push guard enforce it. |
| 4. The builder does not write the as-built record | P1 | Kept as is. |
| 5. Nobody builds on a shared branch | P3 | Kept; isolation is what lets many agents flow concurrently. Native worktree isolation and the push guard enforce it. |
| 6. External text is data, not instruction | P4 | Kept as is; an instruction arriving in data is an andon pull. |

One obligation the reset adds is stated as a law because a hook enforces it: *tests are locked during implementation; the fix lane may add a test but not edit one* (P1). Nothing else new becomes a law. "A change names what it retires" is P2 applied at creation, not a per-change obligation, and it stays a principle.

Numbering makes a principle citable and its number stable; the wording may be edited. The three moments a number is used: at creation, in the cost line a ticket, guard, or stage carries; at review of a process change; and in the retirement table, where each component names the principle it serves.

## The lifecycle: three lanes by blast radius

Work is classified once, at intake, into a lane. The lane is the existing `assurance:` label with its meaning tightened; the three names are kept because consuming repos already carry them.

| Lane | Label | Admits | Stages | Exit check per stage |
|---|---|---|---|---|
| **Fix** | `trivial` | A diff describable in one sentence; touches no protected area; adds tests but edits none | isolate → build → composite gate → land | gate marker over the exact tree; push guard |
| **Change** | `simple` | One checkable outcome, bounded decisions, no contract change | clarify → spec → isolate → ground → build (tests locked) → composite gate → review-or-repair → land → record if documented behaviour changed | no `[NEEDS CLARIFICATION]` left; every criterion names its evidence; RED for the right reason; marker; one fresh PASS bound to the tree |
| **Feature** | `complex` | A contract change, a protected area, or anything a proposal spawned | change lane plus: design (fresh sub-agent) before build; operator checkpoint at the spec; as-built record on PASS | design answers every criterion or stops |

Three rules make the lanes real:

- **The fix lane is cheap or it is not used.** No ticket, no reviewer sub-agent, no as-built record; the gate and the push guard are the whole assurance. The residual risk is a wrong one-sentence fix landing green, which the next builder's composite gate and the reviewer of the next change on that surface catch. Today `trivial` needs an opt-in certifier no repo has, so every one-line fix pays the change lane; agents route around it and the boundary erodes.
- **Protected areas are a tripwire, not a scope note.** The change spec names them (auth, billing, migrations, permissions, the gate, the hooks). A diff that reaches one stops and holds; it does not proceed with a stated assumption.
- **Upgrade only.** A lane may be raised mid-run with a recorded reason, never lowered.

### Stages, and what each one drops

**Intake** (`/capture`, or the fix lane's plain "fix X"). Classify the lane; search the open queue for a twin; write the title as *verb + where*. New: a **clarification loop with a stop condition rather than a cap.** Ask until no question remains whose answer would change the architecture, a contract, the data model, or the test design; rank by impact so the consequential ones come first; integrate each answer into the spec as it arrives and replace the sentence it supersedes. There is no number: a material question left unasked at intake is either asked at build time, where a paid context is waiting on it, or guessed, and guessing is the measured precondition for cheating. Attended, this is `AskUserQuestion`; unattended, an unanswerable question becomes an `input` hold. A spec may carry `[NEEDS CLARIFICATION: …]` inline; `/build` refuses to start while one remains. An **Assumptions** section records decisions made without authority.

**Ground.** Unchanged in purpose and kept verbatim as the harness's strongest requirements practice: verified current reality, `path:line` anchored. Done by the host's native read-only explorer with a fixed output shape (verified facts · current path · evidence surface · decision-relevant unknowns, no recommendation), per the sibling proposal `structured-explorer-and-repair-build-loop`. Conditional: skipped when the facts were read this session.

**Build.** **The orchestrator is the builder by default.** A builder sub-agent is dispatched only when the work would flood the orchestrator's context (a large diff across many files) or the feature lane wants a fresh design context; for a fix or an ordinary change, a hand-off to a sub-agent costs a second context and a written brief for no gain in independence. Sub-agents buy isolation, not delegation. The one context that must always be fresh is the reviewer's, and it is fresh whoever built, because it receives the packet and never the builder's conversation. Test-first for executable behaviour, RED for the right reason (a failing assertion with expected and actual, never an import error). New: **tests are locked during implementation.** Run state lives in `.harness/run.json` in the worktree (`stage`, `lane`, `tests_locked`, `reviewed_tree`, cycle count), a JSON file because the model rewrites JSON less casually than Markdown and because a crashed run can resume from it. A `PreToolUse` hook refuses edits to test paths while `tests_locked` is true; the fix lane allows additions only. The implementer's brief gains one sentence: *"if the criteria contradict each other or cannot be met honestly, stop and say so"*, with DEFER as the named way to return it (92% → 1% in the measured study).

**Composite gate.** The blocking gate certifies the candidate merged with the integration branch at that moment: one gate per build (decided 2026-09-04, D2). The marker names the tree it verified; the claim it licenses is *green over these exact bytes*.

**Review-or-repair.** One fresh reviewer per cycle, given the packet and never the builder's conversation. Its mandate is **scoped**: correctness, the stated criteria, the four-category cheat taxonomy (modified tests, overloaded comparisons, hidden state, special-cased inputs), and an explicit justification for every diff to a test file. It does not hunt for improvements; a reviewer prompted to find gaps will report some even when the work is sound, and chasing them enlarges the diff. A small, contained, in-scope finding it repairs in place and hands to a second fresh reviewer, which certifies only if it makes no repair (sibling proposal, Option C). Verdicts stay PASS / FAIL / DEFER. **The ceiling drops from five cycles to three**, and the `unconditional_review_cycles` key goes: a FAIL either converges in three or the work is held. The as-built record is written by the reviewer on PASS, still never the builder, **whenever the diff changes a documented behaviour, in any lane**: the record moves, or the review records a deferral naming why. The feature lane always reaches it, because a feature changes documented behaviour by definition; the fix lane never should, and a fix that does is not a fix and is upgraded. The record carries no bare counts (#518: anchor or derive).

**Land.** The decided landing posture, unchanged: a clean auto-merge over a certified ancestor carries the verdict without a re-gate; a conflicted merge re-gates over the conflicted paths with a scoped marker; gate outcomes are published as flat refs (`refs/harness/gate/<tree>-green|-red`) discovered by one `ls-remote`; two unattended runs never claim one ticket because a claim ref is created first-writer-wins; a green pointer names the last known-good integration tree for new worktrees to branch from. The four-step re-bind path in the build workflow becomes a script, because a low-freedom procedure written as prose costs context on every read and can still be deviated from.

#### The landing posture, explained

*Why it is hard.* A verdict binds to a tree. The integration branch moves while the gate runs. Under today's rule every move re-enters reconcile, delta review, the full gate, the verdict, and the push, and each of those opens a new window of the same width. With a ten-minute gate and several agents landing per hour, the expected number of attempts to land is `e^(λW)`: modelled at 7.4 attempts for eight pushes an hour. Making a retry cheaper does not change the shape; only taking λ out of the exponent does.

*What the posture does, in order.*

1. **Gate the composite, once.** Before review, merge the integration tip into the candidate and gate that. The verdict then covers the candidate as it would land at that moment, not as it was authored.
2. **At push, three cases.** The integration tip has not moved: push. It moved and `git merge` is clean with no authored bytes: git alone proves the merge added nothing a reviewer has not seen (one merge base, parents exactly the passed commit and the incoming tip, a clean index and worktree, no staged resolution), so the push guard accepts a marker over the certified parent and there is no re-gate and no re-review. It moved and the merge conflicts: the resolution bytes are the only thing nobody has verified, so the run re-gates over the conflicted paths with a marker that names its scope (the full gate where the repo declares no scoped command), then pushes.
3. **Share what was learned through git refs, not a service.** `refs/harness/gate/<tree>-green|-red` are blob refs read by one `ls-remote` in about a second with no object transfer, so a red integration branch is found by the next builder's composite gate rather than by a CI job these repos do not run. `refs/harness/claim/<ticket>-<bucket>` is created first-writer-wins, so two unattended runs never build one ticket; claims expire by time bucket, so no force-push is ever needed. `refs/harness/green/<integration>` names the last tree known green, so new worktrees branch from it rather than from a possibly-red tip.

*What it mitigates:* the exponential; a lock server or merge queue; a CI dependency; two routines on one ticket; building on a red base.

*What it accepts, stated as the trade (principle 2):* a silent semantic merge inside a shared file, two individually green changes whose combination is wrong, lands and is caught by the next composite gate; a red integration branch persists until the next build rather than the next CI run.

*What was killed by a probe:* lease-stealing with `--force-with-lease`, refused by the force-push guard in two minutes (probe 5), replaced by bucket rotation, which is simpler than what it replaced.

**Reflect, record, and close.** After the push and before close, a reflection of at most three lines or `none`: the wastes this run met, by P2's categories, and what should change; each line is filed to the repo's improvement ledger, or to the harness's when it concerns the guidance. Then the tracker transition, worktree cleanup, and the **queue growth line** in `/digest` (the "R line"): one line stating tickets opened versus closed in the window, with the opened count split by source, filed from use because the tree contradicted itself, promoted by the operator from the ledger, or filed by the operator directly. Read once a day, it is the only place the queue's growth rate is visible.

## Mechanisms

What changes in the tree to make the lifecycle above true. Each names its cost and what it retires (principle 3).

### Spine and configuration

- **One source file, `AGENTS.md`;** `CLAUDE.md` becomes `@AGENTS.md` plus Claude-specific deltas. Retires the Codex generator (375 lines), the codex drift gate stage, and its tests. *Verify first:* that Codex reads `skills/` from the plugin manifest (it declares `"skills": "./skills/"`) and needs nothing from a commands directory; a probe, not an argument.
- **Configuration leaves the prose.** The `repo: / tracker: / commands: / branches: / loop: / paths:` block moves to `harness.yaml`, read by hooks and skills alike. Retires the three hand-rolled spine readers in the hooks and the class of bugs they carried (#487, #488, #510).
- **Laws become obligations.** Under 120 lines, one imperative per line, rationale in HTML comments (stripped before injection, so free). Emphasis spent on at most two lines. Path-scoped rules (`.claude/rules/*.md` with `paths:`) carry what only matters in `scripts/` or `design/`.

### Skills: 28 → about 9

Keep the product, the lifecycle the model would get wrong without it: `engineering`, `review-discipline`, `authoring`, `work-discovery`, `worktree-isolation`, `architecture`, one merged `assess` (from `assessment-craft` + `process-economy`). **`spec-authoring` becomes `authoring`**: one skill for every artefact written for a downstream agent, a proposal, a change spec, a ticket (which is a prompt), a design hand-off, an as-built record. Precise, descriptive, no bloat, whatever the artefact; the old name narrowed it to specs while the same discipline governs the ticket a builder reads. It absorbs `writing-quality`, and its description carries the triggers. Command workflows ship once, as skills with `disable-model-invocation: true`, serving both hosts; the 9 generated `command-*` and 4 `agent-*` mirrors go. `systematic-debugging` and `infrastructure` face the deletion test (would the agent get this wrong without it?). `ux-design` and `design-system` become path-scoped rules in the repos that have a design layer.

*The provider swap, as probed.* The official marketplace carries `github` ("Official GitHub MCP server"), `linear` ("Linear issue tracking integration"), and `atlassian`. All three are **MCP transports, not recipes**: the marketplace entries carry no version, and the local plugin cache holds no skill content for either `github` or `linear`. So the swap is narrower than replacing our two provider skills. Those skills carry two things: API recipes (`gh` invocations, the Projects v2 GraphQL for board status, Linear's state and label id resolution), which are commodity and rot; and the harness's ticket semantics (states, hold = comment + label + assignment, explicit Todo placement verified by re-reading, the ledger found by label), which are product. The transport is swapped for the official MCP where the repo has it; the semantics collapse into one thin `tracker` skill of ours that works over whichever transport the repo declares, `gh` or MCP. Two probes before the swap lands: whether the GitHub MCP server can set a Projects v2 item's Status (the one write our recipes do that a generic issue API may not), and whether an unversioned MCP plugin can be pinned at all; where it cannot, the `gh` recipe for that single operation stays and the risk is recorded.

Every kept skill and agent gains `effort:` and `model:` frontmatter, so the lane sets cost through the runtime rather than through prose the agent may not honour. ADR 0005 already measured 110 Opus reviews against 114 Sonnet at 18.4% vs 17.3% fail rate, under the noise floor: the change-lane reviewer defaults to the cheaper model.

*How that is applied from a plugin file.* On Claude Code, `model:` and `effort:` are frontmatter fields on both skills and agents, read by the runtime when the file is loaded, plugin files included; a skill with `context: fork` applies them to the forked sub-agent, and the orchestrator can also pass a model override at dispatch. The lane therefore selects cost in one of two native ways: by which agent definition it dispatches (a change-lane reviewer and a feature-lane reviewer are two small agent files that differ in those two lines), or by the override on the call. Codex accepts only the six standard skill fields, so there the same choice is made in the Codex agent definitions and profile configuration; where a host offers neither, the lane still runs, at that host's default cost. Nothing here asks the model to honour a tier. That was the mechanism ADR 0005 retired, and rightly: it cost a tracker round trip and five degradation branches to read a label nobody set.

### The trigger commands

All nine keep their names and their triggers: `/harness:build`, `/capture`, `/propose`, `/review`, `/routine`, `/digest`, `/assess`, `/promote`, `/harness:init`. What changes is the artefact behind each. Today every workflow exists twice, a file under a commands directory for Claude Code and a generated `skills/command-*` mirror for Codex, kept byte-identical by a generator and a gate stage. In Claude Code a command file and a skill file produce the same slash command, and the Codex manifest reads `skills/`, so each workflow ships once, as a skill with `disable-model-invocation: true`: the operator triggers it, the model does not auto-fire it, and it leaves the skill-listing budget.

| Command | What changes inside |
|---|---|
| `/build` | 143 lines to under 70. Landing becomes a script, visual evidence a stage-loaded reference, stages are exit-check defined, the reflection step is added at the end. |
| `/capture` | Gains the clarification loop, the marker, Assumptions, Protected areas, the cost line. |
| `/routine` | Gains the claim ref and the andon check: an open P1 bug is the only pick. |
| `/assess` | Loads the merged `assess` skill, derives the ratios and gate duration, drains the improvement ledger. |
| `/review`, `/digest`, `/promote`, `/propose` | Vocabulary edits only. |
| `/harness:init` | Writes `harness.yaml`; seeds the path-scoped rules below. |

One composition must be probed before the flag is applied everywhere: `/routine` invokes `/build`, and `/build` invokes `/review`'s stage. Today the routine's model reads the command file and follows it, which a skill file supports unchanged; whether the flag also stops the Skill tool invoking the workflow by name from inside another workflow is the probe (T1). The fallback is that `build` and `review` stay model-invocable and the six operator-only workflows carry the flag.

### Path-scoped rules for design and UX

`design-system` and `ux-design` stop being plugin skills that must be triggered by description and become repo-owned rules that load whenever an agent touches a UI path. The measurement behind that (research 01 §10): guidance that had to trigger fired at 53%; guidance simply present when relevant scored 100%; a rule that appears whenever a component file is opened cannot fail to fire and costs nothing on every other task.

- **Mechanism.** `.claude/rules/design-system.md` with a `paths:` frontmatter of globs. `/harness:init` seeds it when `layers.design_system` is on, taking the globs from `harness.yaml`'s declared design directory and the repo's UI source paths (asked once at hydration, recorded in the yaml). Codex has no path-scoped rules; `init` seeds the equivalent nested instruction file in the design directory, which Codex reads nearest-wins.
- **Content.** The pointer to the repo's tokens source and primitives; the states checklist (empty, loading, error, edge: 0 / 1 / many / missing); accessibility; the visual-evidence capture rules that live in the build command today (viewport slices, the pixel ceiling, the capture cap, the `.evidence/` location). Repo-owned once seeded: the repo edits it, the plugin does not overwrite it on refresh.
- **Deletion test.** `ux-design`'s general craft (human behaviour, information architecture, flow) overlaps the official `frontend-design` plugin and much of what the model already does; it is deleted unless T5's evals show a delta, and a repo that wants the general craft installs the official plugin.

### Guidance verified by use

Each kept lifecycle skill gets an *evals/* set: two or three scenarios run with and without the skill in fresh contexts, plus a trigger set of should- and should-not-fire prompts. The harness itself gets a task set of roughly twenty items drawn from the ledger's recorded failures (`skills/review-discipline/references/craft.md` catalogues 49 admitted classes). This replaces prose guards as the way a guidance change is justified, and it is bounded: three scenarios per lifecycle skill, no more, or it becomes the next ratchet.

### Content quality of the kept skills

Process shape is half the reset. The other half is what the kept skills say, and how. Audited on 2026-09-04 against the writing rules skill-creator itself states (imperative form, why over must, explain the reasoning, keep the body lean, references one level deep, a table of contents past 100 lines, a description that carries every trigger):

| Skill | Lines | Words | Bold spans | Citations of other skills | References |
|---|---|---|---|---|---|
| `engineering` | 108 | 1,781 | 31 | 3 | 4 files, one of 247 lines |
| `review-discipline` | 109 | 2,882 | **81** | **12** | 4 files, `craft.md` at **776 lines, no table of contents** |
| `spec-authoring` | 110 | 2,700 | 62 | 6 | none |
| `work-discovery` | 159 | 1,485 | 27 | 1 | none |
| `worktree-isolation` | 71 | 525 | 1 | 1 | none |
| `architecture` | 83 | 1,499 | 37 | **12** | none |
| `assessment-craft` | 64 | 960 | 26 | 10 | none |
| `process-economy` | 96 | 1,909 | 33 | 4 | none |

What that says: no caps-lock imperatives anywhere, which is right; but two skills run to 26 words a line, which is paragraphs rather than instructions; bold is spent, so nothing can be raised above the rest; two skills cite twelve other skills each, which is the chained-reference shape the one-level rule exists to stop; and the largest reference has no table of contents, so a partial read hides its scope. Descriptions sit at 218 to 354 characters against a 1,024 limit, with room for the near-miss negative scope that stops a skill firing on the wrong task.

*The method is the skill-creator loop, applied per kept skill, in this order:* snapshot the skill; write two or three realistic prompts drawn from the ledger's recorded failures; run each with the current skill and with the snapshot in fresh sub-agents; grade against assertions and read the transcripts, not only the outputs; rewrite (cut restatement the model already knows, one obligation per sentence, the reason beside the rule, a bold budget, references one level deep, a table of contents for `craft.md`); re-run; then optimise the description with the trigger loop (twenty queries, half near-miss negatives, three runs each). Alignment is the last pass: the kept skills must share one vocabulary for lanes, verdicts, and the marker, because two rules that contradict get picked between arbitrarily.

*Bound:* three prompts and two iterations per skill unless the delta is still moving. The numbers above are the starting line; the exit is a recorded with/without delta per skill, or the skill is cut.

### Enforcement: three refusing hooks stay, one is added, one retires

Keep the Stop gate-evidence guard, the push-target guard, and the force-push refusal. Add the test-lock hook above. Retire `workflow-guard.js` once native worktree isolation is confirmed on both hosts. Stop-hook blocks are capped at eight by the host, so the hook is a nudge with a ceiling, and the push guard remains the control.

*The prompt guard* is a 105-line advisory `PreToolUse` scanner on writes: it looks for injection-shaped text (instructions addressed to an agent) in content being written and warns on stderr; it never blocks. It goes on the retirement table with the test this repo already states for warn-and-pass guards: it has not been shown to run until it has fired once for the real reason. Iron law 6 is the rule; the hook is at most a nudge.

*`scripts/mutate.py`* is not a general mutation-testing tool and is not shipped: it lives in this repo's `scripts/`, neither plugin manifest ships scripts beyond the gate helper `init` materialises, and neither calibrate nor nano-erp carries it. Its job is narrower: prove that a guard test in this repo can fail, by applying a bespoke mutation table to the guarded code and requiring the predicted tests, and only those, to go red. Where a consuming repo wants mutation testing over load-bearing logic, principle 1 says the ecosystem tool for its language (mutmut, Stryker), named as an evidence option in the feature lane, not 1,503 lines shipped from here. It stays a harness-local guard-quality instrument, on the retirement table with its test: retire when the evals cover guard quality.

### Work creation

- Bugs are filed; improvements are proposed. Kept, and given a home that drains. The standing ledger becomes the **improvement ledger** (kaizen, P5): the reviewer's Proposals section and the build's reflection step both append to it; an improvement to the guidance, hooks, or skills the plugin ships goes to the harness repo's own ledger, resolved from the plugin's declared source and never hardcoded (the shipped `guidance-feedback-upstream` rule, re-homed). `/assess` drains it and marks every entry done, folded into a ticket, or dropped, and dropped is written down. Settled proposals leave `specs/proposals/` (git history keeps them); `specs/retired/` (6,329 lines) leaves the tree.
- A filed ticket, a proposed guard, and a new gate stage each carry **one line of cost and benefit** at creation: what it costs, what it buys, which principle it serves and which it spends against, and which waste it removes or adds. Waste is a work decision, not only an audit finding: the fix lane exists to remove over-processing, and a ticket that adds inventory without removing a waste is refused at filing. Convention, no guard.
- A ticket filed from a breakdown carries its dependencies and its urgency in the tracker's own fields, never only in prose, so sequencing is enforced by `work-discovery` reading them rather than by an operator repeating the order. The `tracker` skill's filing recipe requires both (T4). Flow decides the split: by what can proceed independently, not by what is shippable alone; a ticket is blocked only by what it genuinely reads from. Andon decides the exception: an open P1 bug is picked before anything else and nothing new starts until it is closed (P4).
- `/assess` computes the module count and the guard-to-deliverable ratio every pass, using the derivations in this document.
- **A retirement table**, *specs/harness-assumptions.md*: one row per component naming the model limitation it assumes and the test that would show the limitation gone. Reviewed at every model or host release. This is the standing basis for refusal the v5 cull did not have.

### What stays, verbatim

The harness is ahead of the published state of the art on these, and the reset keeps them: the gate marker bound to a **tree oid**; a fresh reviewer that never sees the builder's conversation; **RED for the right reason**; **DEFER** as distinct from FAIL; hold = comment + label + assignment; **Grounding** with `path:line` anchors; the ticket body as the change spec; **bugs filed, improvements proposed**; the assurance label chosen at filing and upgrade-only; reconciliation placed adjacent to final binding; gate records as `ls-remote`-discoverable refs.

## Options

**Option A — principles as guidance only.** Free, and what the v5 cull did; the ratchet table measures the result.

**Option B — the reset as written, as five sequenced tickets.** The lean principles enter the spine as a numbered list later work cites; the lanes, the intake loop, the test lock, the scoped review, the landing posture, the deletions, the evals, and the retirement table follow in dependency order. *Trade-offs:* the largest single change since v5; the first two tickets change the machinery that would review them, so their assurance concentrates at the operator's merge review, as v5 did. The measurement plan is what keeps it honest.

**Option C — the reset without the deletions.** Add the lanes, the intake loop, and the test lock; keep the mirrors, the providers, and the 28 skills. *Trade-offs:* every gain in cycle time, none in complexity; the listing budget and the compaction budget keep dropping the skills a stage needs. Fails principle 3 on its face.

**Option D — landing posture only** (the previous version of this proposal). Removes the exponential; leaves the loop that produced it.

## Recommendation

**Option B.** A and D leave the loop intact and C leaves the cost intact. The order inside B is chosen so each ticket leaves the gate green and can be measured on its own.

## Open decisions

| # | Decision | Recommendation | Who | Recorded in |
|---|---|---|---|---|
| D1 | Do the principles enter the spine as a numbered list that later work cites by number, ahead of the laws, with each law rewritten to one line citing its principle? | Yes; see *Principles and laws*. No law is retired; three shrink; one is added for the test lock | user | `AGENTS.md` |
| D9 | Restate the principles as lean (P1 to P5) with the mapping from the earlier numbering? | **Decided 2026-09-05 by the operator:** yes | user | this proposal, `AGENTS.md` |
| D10 | A reflection step at the end of `/build`, bounded to three lines, filing to the improvement ledgers? | Yes; the bound is what keeps it from becoming its own waste | user | `skills/build/SKILL.md` |
| D11 | An open P1 bug stops the line: the only pick until closed? | Yes; it is the cord, and the Priority field is the pull | user | `work-discovery`, `/routine` |
| D2 | The fix lane ships on the gate alone, with no reviewer sub-agent. Accept the residual risk named above? | Yes; the next composite gate and the next reviewer on that surface are the backstop | user | spine, `harness-assumptions.md` |
| D3 | Test lock: enforced by a hook, or instructed? | Hook; instruction is measured not to work | user | `hooks/` |
| D4 | Transport swapped to the official `github` / `linear` MCP plugins, with one thin `tracker` skill of ours keeping the ticket semantics? | Yes, after two probes: Projects v2 Status writes over MCP, and whether an unversioned MCP plugin can be pinned | user | `plugin.json`, `tracker` skill |
| D5 | Codex surface served by the skill form alone, deleting the generator? | Yes, after the read-path probe | user | ADR |
| D6 | Review ceiling 3, `unconditional_review_cycles` deleted? | Yes | user | `harness.yaml` |
| D7 | As-built record owed only in the feature lane and on a documented-behaviour change? | Yes | user | `review-discipline` |
| D8 | Ledger entries not promoted at a drain are deleted? | Yes | user | `proposals-ledger.md` |

## Breakdown

Filed on 2026-09-05 as twelve issues, then **collapsed the same day under P3**: an interim state need not be shippable when nothing pulls it, so the eight landing-posture issues fold into one, the law-3 restatement folds into the spine ticket, and the cost line folds into the intake ticket. Five tickets remain, each carrying the brief below as its change spec, with native blocked-by dependencies and a board Priority:

| Ticket | Issue | Priority | Blocked by | Folded in |
|---|---|---|---|---|
| T1 Spine, configuration, principles | #537 | P1 | none | #540 |
| T2 Lanes, intake, build state, scoped review, reflection, andon | #538 | P1 | #537 | #546 |
| T3 Landing posture | #539 | P1 | #537 | #541 #542 #543 #544 #545 |
| T4 Prune, the tracker skill, the ledgers, the retirement table | #547 | P2 | #538 #539 | |
| T5 Skills and agent content remediation | #548 | P3 | #547 | |

T2 and T3 run in parallel after T1 (P3): T3 touches the hooks, the marker helper, and a new landing script, and writes its `/build` land-loop section last so it reconciles onto T2's slimmed command. The first three change the machinery that would otherwise review them, so their assurance concentrates at the operator's review of the merge, as v5 did; T4 and T5 go through the lanes as any change does. Every criterion names its evidence. A builder who finds a criterion already met by the tree closes it by observation on the ticket rather than rebuilding it.

### T1 — Spine, configuration, and principles (#537)

*Lane:* feature. *Serves:* P2. *Spends against:* nothing; this ticket only deletes and rearranges.

**Delivers.** Configuration leaves the prose into `harness.yaml`, read by hooks and skills through one reader. `AGENTS.md` becomes the source instruction file and `CLAUDE.md` becomes `@AGENTS.md` plus Claude-specific deltas. The five principles enter the spine as a numbered list ahead of the laws; the laws are rewritten per *Principles and laws*, one obligation per line, rationale in HTML comments, with the test-lock law added and law 3 restated in authored-tree terms (the two acceptance paths the landing posture creates, stated in one home each: the spine, and `review-discipline`'s final-evidence ordering rule). The Codex generator, its gate stage, and its mirror tests are deleted after the read-path probe. Path-scoped rules carry what only matters under `scripts/` or `design/`.

**Acceptance criteria.** AC-1 the hydrated spine is under 120 lines, principles numbered ahead of one-line laws (`wc -l`; direct review). AC-2 hooks and the marker helper read roles, commands, and loop settings through one shared reader, and the three legal `branches:` spellings parse identically (existing hook tests re-pointed, RED first on a fixture the old parsers accepted). AC-3 Codex discovers the command workflows from `skills/` alone (the probe, recorded on the ticket before deletion). AC-4 no codex drift stage, no generator, no mirror tests (gate green without them). AC-5 `/harness:init --refresh` migrates calibrate's and nano-erp's spines into the yaml without losing a value (diffed key by key, recorded). AC-6 law 3 and the shipping equality state the authored-tree claim in one home each (`grep -rn "must equal the tree"` finds only that home). AC-7 the workflow-composition probe is recorded before any workflow gains `disable-model-invocation: true`: whether `/routine` can still drive `/build`, and `/build` the review stage, with the flag set; if not, `build` and `review` stay model-invocable and only the six operator-only workflows carry it.

**Out of scope.** Lifecycle semantics (T2), landing logic (T3), skill content (T5). **Protected areas:** `hooks/` beyond the reader swap and message wording.

### T2 — Lanes, intake, build state, scoped review, reflection, andon (#538)

*Lane:* feature. *Serves:* P1, P3, P4, P5. *Spends against:* P2, by one hook and one JSON file, each named with what it retires.

**Delivers.** Lane rules in the spine with the fix lane real (gate and push guard only; `assurance.trivial_certify` retired). `templates/change.md` and `/capture` gain the clarification loop with its stop condition, `[NEEDS CLARIFICATION]`, Assumptions, Protected areas, the title convention, and **the cost line at creation**: what it costs, what it buys, which principle it serves and which it spends against, and which waste it removes or adds (P2's categories); a filing without it is incomplete. `/build` refuses a spec with a marker left, is the builder by default, keeps run state in `.harness/run.json`, and dispatches a builder sub-agent only on the two stated conditions. The test-lock hook. The scoped reviewer mandate with the four cheat categories, review-or-repair, `max_review_cycles: 3`, the unconditional window deleted. The builder's stop-and-flag sentence. The as-built obligation restated for every lane. **The reflection step:** after a successful push and before close, `/build` writes at most three lines or `none`: the wastes this run met, by category, and what should change; each line is filed to the repo's improvement ledger, or to the harness's ledger when it concerns the guidance (the channel T4 builds; until then, the existing `proposals-ledger` label and the shipped upstream rule). **Andon in the loop:** `/routine` and `work-discovery` treat an open P1 bug as the cord: it is the only pick until closed, and an attended `/build` on anything else reports it before starting. `skills/build/SKILL.md` under 70 lines; the visual-evidence rules move to a stage-loaded reference.

**Acceptance criteria.** AC-1 the hook refuses a locked test edit, allows a fix-lane addition, allows everything with no run state (one test per decision-table row, each proven able to fail). AC-2 `/build` refuses a spec with a marker left and names the line (direct use). AC-3 a killed run resumes from `run.json` (direct use, report names the stage). AC-4 `build.md` under 70 lines naming no procedure a script or reference owns. AC-5 the reviewer's report carries the scoped mandate and an explicit item per test-file diff (one representative run). AC-6 `unconditional_review_cycles` appears nowhere; the ceiling is 3. AC-7 `/capture` refuses a filing without the cost line and the template carries Assumptions and Protected areas (direct use). AC-8 a run ends with a reflection of at most three lines and each line lands in a ledger (one representative run; the ledger entry). AC-9 with an open P1 bug on the board, `/routine` picks it and nothing else (direct use on scratch issues).

**Out of scope.** Landing (T3). Provider recipes and the ledger rename (T4). **Protected areas:** the three refusing hooks.

### T3 — Landing posture (#539)

*Lane:* feature. *Serves:* P1, P2, P3. *Spends against:* P2, by one optional `commands:` key, one marker field, and one script; the script retires a longer prose procedure and the rest is four refs.

**Delivers,** as decided 2026-09-04 (D2 to D5, probes 1 to 8) and unchanged in substance; the eight items become one ticket because none of the interim states is pulled by anything. (1) The push guard's second acceptance path: a clean two-parent merge over a certified ancestor with no authored bytes, proven from git alone. (2) Gate records as flat blob refs `refs/harness/gate/<tree>-green|-red`, one `ls-remote` to read, prune riding on publish, publish failure never reddening a green gate. (3) Claims as create-wins refs `refs/harness/claim/<ticket>-<bucket>` with bucket rotation, never a force. (4) The scoped re-gate on the conflict path through an optional `commands.test_scoped`, a marker `scope` field, and a containment check in the guard; undeclared, the full gate. (5) `/build`'s composite gate before the verdict and the land loop after it (unchanged tip: push; clean merge: push under the acceptance path; conflict: resolve, scoped re-gate, push; two attempts then hold; triage a red composite gate whose failures lie outside the candidate as a red base, reported through the records; park on a lost claim), with the three-case decision and its git checks in a landing script and the command explaining only when it applies. (6) The green pointer `refs/harness/green/<integration>` advancing on uncontended landings, and `worktree-isolation` branching from it. (7) `started_at` in the marker so gate duration is measured from week one.

**Acceptance criteria.** AC-1 the guard allows the clean shape and denies it once one byte is authored, once a parent differs, once the merge base is not unique, once the marker is stale, and once authored bytes fall outside a scoped marker (one test per condition, each proven able to fail). AC-2 a record published from one clone is read by another in one `ls-remote` with no object transfer, and publishing prunes a departed record while leaving current ones (scratch bare remote; `git count-objects`). AC-3 two concurrent claim creates yield one winner and a rotated bucket admits a new one (raced pushes; clock advanced). AC-4 a scoped run's marker names exactly the conflicted paths on a fixture conflicting in two files and touching a third cleanly, and an undeclared repo writes an unscoped marker. AC-5 the landing script takes the unchanged, clean, and conflict paths on three fixtures and refuses every other shape; `build.md` carries no git invocation for landing. AC-6 the pointer advances on an uncontended landing and not on a conflicted one; a new worktree reports its base. AC-7 every new marker carries `started_at` and `finished_at`, and `/assess` reports the median gate duration.

**Out of scope.** Review-stage changes (T2). The force-push refusal never changes. **Protected areas:** `hooks/git-push-guard.js`; `hooks/gate-evidence-guard.js` beyond message wording.

### T4 — Prune, the tracker skill, the ledgers, the retirement table (#547)

*Lane:* feature. *Serves:* P2, P3, P4, P5. *Spends against:* nothing; deletions are most of the diff.

**Delivers.** Skills 28 → about 9: the kept set (`engineering`, `review-discipline`, `authoring`, `work-discovery`, `worktree-isolation`, `architecture`, `assess`) plus the command workflows as skills with `disable-model-invocation: true`; the 13 generated mirrors, `writing-quality` (absorbed), `systematic-debugging`, `infrastructure`, `ux-design`, and `design-system` deleted, with the deletion-test answers recorded. The last two are re-homed per *Path-scoped rules for design and UX*: a *templates/rules/design-system.md* asset that `init` seeds into `.claude/rules/` with globs from `harness.yaml` (design directory plus UI source paths) and, for Codex, as a nested instruction file in the design directory; it carries the tokens pointer, the states checklist, accessibility, and the visual-evidence capture rules moved out of `/build`; it is repo-owned after seeding and never overwritten by `--refresh`. **The `tracker` skill:** one thin skill carrying the ticket semantics over the transport the repo declares (`gh` or the official MCP plugins, after the two D4 probes). It owns sequencing for flow and andon: `create` sets native blocked-by relationships and the board's Priority, and reports a breakdown ticket filed without both as incomplete; a breakdown is split by what can proceed independently, not by what is shippable alone, and a ticket is blocked only by what it genuinely reads from; `work-discovery` picks an open P1 bug before anything, then skips blocked tickets, then prefers the higher Priority and the ticket that unblocks the most. **The ledgers:** the standing `proposals-ledger` issue becomes the **improvement ledger** (`improvement-ledger` label; the recipe migrates the old label), and the harness repo's own ledger is the destination for guidance improvements, resolved from the plugin's declared marketplace source, never hardcoded (re-homing the shipped `guidance-feedback-upstream` rule from the retired lock file). `/assess` drains the ledger and records each entry as done, folded, or dropped. Every kept skill and agent carries `effort:` and `model:`, with a change-lane and a feature-lane reviewer definition. *specs/harness-assumptions.md* with one row per component. `specs/retired/` and settled proposals leave the tree. `/assess` derives the module count, the guard-to-deliverable ratio, and the gate duration.

**Acceptance criteria.** AC-1 the skill listing is under the 1% budget with the summed description length recorded. AC-2 every hook, script, skill, and agent has a row in the assumptions table. AC-3 `tracker` performs create, transition, hold, Todo placement, and ledger append on a GitHub and a Linear repo (scratch issues, recorded). AC-4 the two D4 probes are recorded before any provider recipe is deleted. AC-5 `create` sets blocked-by and Priority when supplied and reports a breakdown filing incomplete without them; `work-discovery` picks an open P1 bug first, skips a blocked ticket, and prefers the higher Priority among unblocked candidates (scratch issues, the pick recorded). AC-6 no `command-*` or `agent-*` directory remains and both hosts expose every workflow. AC-7 a reflection line filed from a consuming repo about the guidance lands on the harness repo's ledger without a hardcoded owner (direct use from calibrate). AC-8 an `/assess` drain leaves every ledger entry marked done, folded, or dropped. AC-9 `init` on a repo with `layers.design_system: true` writes the rule with the repo's globs and the Codex nested file, and a second `--refresh` leaves a repo edit to the rule untouched (direct use on a scratch repo, diffed).

**Out of scope.** Rewriting kept-skill content beyond renames, merges, and the vocabulary T2 changed (T5). **Protected areas:** `hooks/`.

### T5 — Skills and agent content remediation (#548)

*Lane:* feature. *Serves:* P2, P5. *Spends against:* P2, by adding an *evals/* directory per kept skill; bounded below. *Depends on:* T4, so the set being refined is the set being kept.

**Intention.** The kept skills and the four agents are the product. Their content has never been verified by use, only by reading; two are written as paragraphs rather than instructions, emphasis is spent, references chain, and descriptions under-specify their triggers. This ticket makes each one leaner, explains its reasoning instead of asserting it, and proves the result with a recorded with-and-without delta. It does not change what the lifecycle means; T2 owns that.

**In scope.** The seven kept skill directories under `skills/` (engineering, review-discipline, authoring, work-discovery, worktree-isolation, architecture, assess) including their *references/* subdirectories, and the four files under `agents/` (architect, dev, reviewer, steward). The command-workflow skills are in scope only for the description and for cutting text T2 made redundant.

**Starting line, derived 2026-09-04** (`wc`, `grep -c` over `**…**`, and a grep for backticked skill names):

| Skill | Lines | Words | Bold spans | Cites other skills | References |
|---|---|---|---|---|---|
| `engineering` | 108 | 1,781 | 31 | 3 | 4 files, one of 247 lines |
| `review-discipline` | 109 | 2,882 | 81 | 12 | 4 files; `craft.md` 776 lines, no table of contents |
| `spec-authoring` (→ `authoring`) | 110 | 2,700 | 62 | 6 | none |
| `work-discovery` | 159 | 1,485 | 27 | 1 | none |
| `worktree-isolation` | 71 | 525 | 1 | 1 | none |
| `architecture` | 83 | 1,499 | 37 | 12 | none |
| `assessment-craft` + `process-economy` (→ `assess`) | 64 + 96 | 960 + 1,909 | 26 + 33 | 10 + 4 | none |

Agents: `architect` 33 lines, `dev` 35, `reviewer` 65, `steward` 38. No caps-lock imperative appears in any of these files; keep it that way.

**Method, per skill, in this order.** Use the official `skill-creator` plugin's loop as published; do not write a bespoke runner.
1. Snapshot the skill to the workspace.
2. Write two or three realistic prompts, drawn from recorded failures: the defect classes in `skills/review-discipline/references/craft.md`, the `/assess` reports under `specs/`, the improvement ledger, and the operator's ledger of tickets that went past review cycle 3. Save them to *evals/evals.json* inside the skill. A prompt is realistic when a builder or reviewer in a consuming repo would actually type it, with file paths and a ticket shape.
3. Run each prompt with the current skill and with the snapshot, in fresh sub-agents, in the same turn. Save outputs and timing; draft assertions while they run; grade with the plugin's grader; aggregate the benchmark; generate the viewer for the operator.
4. Rewrite. Apply, per line, "would the agent get this wrong without this sentence?" and cut what fails it. One obligation per sentence. The reason beside the rule instead of emphasis. References one level deep from `SKILL.md`, each with a stated moment to load it. A table of contents at the head of `craft.md`. No time-bound content. The description states what the skill does, when to use it in the words a user would say, and what it is not for; under 1,024 characters.
5. Re-run the prompts against the rewrite and the snapshot; record the delta.
6. Run the plugin's description trigger loop: twenty queries, half of them near-miss negatives that share vocabulary with the skill, three runs each; adopt the held-out winner.
7. Agents: keep each thin. An agent file names the role, the tools, `isolation`, `model`, `effort`, the skills it loads, and what it must not do; it does not restate a skill.
8. The alignment read, once, across the whole kept set: one vocabulary for lanes and labels, verdicts, the marker, the hold, the wastes. Each term is defined in the spine and used, never redefined, in a skill.

**Bound.** Three prompts and two rewrite iterations per skill unless the recorded delta is still moving; roughly 130 sub-agent runs in total, which is the budget this ticket states. *evals/* holds prompts, assertions, and the benchmark of the last iteration; it holds no transcripts.

**Acceptance criteria.** AC-1 every kept skill has *evals/evals.json* and a recorded with/without benchmark whose pass-rate delta clears the noise floor, or the skill is cut and the retirement table says why. AC-2 no kept skill cites more than three others, and no reference is reached through another reference (the starting-line grep, re-run). AC-3 `craft.md` opens with a table of contents; no `SKILL.md` exceeds 1,800 words or twelve bold spans (proxies, and the ticket says so; AC-1 is the exit). AC-4 each description scores at or above the plugin's threshold on the held-out trigger set. AC-5 each agent file is under 60 lines, sets `model` and `effort`, and cites only skills that exist. AC-6 the alignment grep finds no contract term defined in more than one place.

**Out of scope.** New skills. Any change to what a verdict, lane, hold, or marker means (T2). Any test or guard over the wording of a skill: ADR 0017 D5 forbids it, and the evals are the verification. **Protected areas:** `hooks/`, the spine's contract section, `templates/`.

Then four weeks of measurement in calibrate and nano-erp before any further change to the process.

## Measurement

Before figures are the table above. Each target is a direction and a floor for what counts as a change, not a promise.

| Metric | Source | Before | Direction |
|---|---|---|---|
| Reconciliation share of integration-branch commits | `git log --merges` | calibrate 23%, nano-erp 12% | down; a fall under the noise floor is no result |
| Ticket cycle time, In Progress → Done | tracker timestamps (git cannot see it; median branch age at merge is zero because candidates are committed at the end) | harness median 16.8h open→close | down |
| Review cycles per ticket | `run.json` | cycle 4 reached 12 times, cycle 5 twice | ceiling 3, and the distribution |
| Gate duration | `finished_at` minus a new `started_at` in the marker | unmeasured | measured, then decided |
| Guard : product | `wc -l tests/unit` : `scripts` + `hooks` | 21,065 : 9,417 | down, and reported every `/assess` |
| Always-on context | spine bytes + skill listing bytes | 98 lines / 28 descriptions | under 120 lines / under the 1% budget |
| Work creation | the `/digest` R line, by source | present | opened ≤ closed over the window |
| Tokens per shipped ticket | host usage where reported | unavailable | recorded as unavailable rather than proxied |

## Risks / unknowns

- **The evals are new machinery.** Bounded to three scenarios per lifecycle skill; if the count grows, the ratchet has moved rather than stopped.
- **The test lock is a convenience-rung control.** A shell redirect bypasses a `Write|Edit` hook; the reviewer's test-diff justification is the second line, and branch protection with the gate in CI is the control of record. Stated so nobody mistakes the hook for the guarantee.
- **The fix lane can leak.** A behaviour change shipping unrecorded is the cost of a real fast lane; the R line and `/assess` are where it shows.
- **Swapping the transport trades maintenance for dependency.** The official `github` and `linear` plugins carry no version in the marketplace, so pinning may not be available; and the official `code-review` and `pr-review-toolkit` plugins define review in their own vocabulary and would compete with `review-discipline` for the same trigger if installed. The probes in D4 exist for the first; the second is answered by not installing them.
- **λ and gate duration are still unmeasured**, so the landing posture's benefit is modelled, not observed. The marker's new `started_at` field closes half of that in the first week.
- **This proposal can become what it describes.** A governance layer, an enforcement guard over prose, or a standing audit obligation would break principle 3 in the document that states it.

**What would invalidate the recommendation:** a measured gate duration near this repo's (tens of seconds) in the consuming repos, which collapses the landing posture's benefit and leaves the loop as a complexity problem alone; or evals showing no with/without delta for the lifecycle skills, which would say the product is thinner than the harness believes and the right reset is smaller still.

## The first instance, carried forward: the landing posture

Decided with the operator on 2026-09-04 and unchanged by this revision. Included as the worked example the principles produced.

- The blocking gate certifies the **composite** tree: the candidate merged with the integration branch at that moment. One gate per build.
- Landing does **not** re-gate a clean auto-merge. The push guard gains a second acceptance path: a fresh marker covering an ancestor commit's tree, that commit a parent of the pushed merge, and no authored bytes in the merge.
- A **conflicted** merge re-gates over the conflicted paths. The marker gains a scope field so it never asserts coverage the run did not have (D4, D3).
- A red integration branch is found by the next builder's composite gate rather than by CI. Sessions share findings through git refs.
- The verdict binds to the **authored** tree rather than the shipped tree.

### Measured

Eight probes against `sluengen/calibrate-coffee`, private, no server-side configuration, 2026-09-04. Every probe ref was deleted afterward.

| # | Probe | Result | Consequence |
|---|---|---|---|
| 1 | Push a commit-pointing ref to `refs/harness/gate/<oid>` | new reference | Custom namespaces work on a private repo. |
| 2 | Push a **blob**-pointing ref, no commit wrapper | new reference | A record is one blob. |
| 3 | Fresh clone, then `+refs/harness/*:refs/harness/*` | needs an explicit refspec | Records never bloat an ordinary fetch. |
| 4 | Two unrelated commits race one claim ref | second rejected, non-fast-forward | First-writer-wins works. |
| 5 | `--force-with-lease` through the hooks | **denied by `git-push-guard.js`** | Killed the lease-steal design; replaced by bucket rotation. |
| 6 | `<tree>/<bucket>` beneath an existing `<tree>` ref | rejected, cannot lock ref | D/F conflict. Every key stays flat. |
| 7 | `git ls-remote origin 'refs/harness/gate/*'` | ~1.0s, zero objects | Put the outcome in the ref name. |
| 8 | *refs/notes/* fallback | new reference | Available, and unnecessary. |

### Decisions — 2026-09-04

**D2 — the verdict binds to the authored tree, and a clean auto-merge may carry it.** The guard proves from git alone: one merge base, parents exactly the passed commit and the incoming tip, a clean index and worktree, no staged resolution. Disjoint changed-path sets were considered and **not** required. The residual risk is a silent semantic merge inside a shared file, and the next builder's composite gate is what catches it.

**D4 — a conflicted merge re-gates over the conflicted paths, not the whole tree.** Resolution bytes are the only uncertified path left under D2.

**D3 — one optional command, no strategy key.** A repo names its scoped test command in the existing `commands:` block. Declared, the conflict path runs scoped; undeclared, it runs the full gate.

**D5 — pruning rides on a write that already happens.** When a builder publishes a gate record it also deletes records whose tree has left the integration branch's recent history.

### Decisions — 2026-09-05, taken while building #539

The shape above survived contact; these five are what building it settled. The two that are cross-cutting and expensive to reverse are [ADR 0020](../decisions/0020-authored-tree-binding.md) and the dated amendment to [ADR 0018](../decisions/0018-gate-marker-convention-is-node.md).

**D12 — every `refs/harness/*` key is one flat, percent-encoded component.** Probe 6 recorded a directory/file conflict the moment a key nested beneath an existing key, and a branch named `release/1.0` or a ticket named `team/42` would reintroduce it. Every byte outside `[A-Za-z0-9_]` is percent-encoded, which is wider than the `/` and `%` the hazard strictly needs: encoding `.` as well makes a leading dot and a trailing `.lock` — both refused by git's ref grammar — unrepresentable without a second rule. *Rejected:* encoding only the two characters that cause the D/F conflict, which leaves a legal branch name that cannot be pointed at.

**D13 — records and claims point at blobs; the green pointer points at a commit.** A blob update is never a fast-forward, so an existing claim rejects every non-forced update and first-writer-wins holds with no lock and no lease (probe 4). The pointer has the opposite requirement — it must advance — so it is a commit and moves only where git will fast-forward it. A record's body is deterministic (the tree and the outcome, no timestamp), so republishing one is the same blob and git reports it as up to date rather than as a rejected update. *Rejected:* one object kind for all three, which makes either the claim stealable by a descendant or the pointer unmovable.

**D14 — publishing a record is never a gate stage.** `scripts/verify.sh` does not publish; `scripts/land.js` does. A record push inside the gate would put a network round trip in every gate run, fail offline, and — worse — let a failure *after* the marker was written turn a green result red. The publish verb therefore exits non-zero only for a caller error and reports a refused remote in its result. This is the argument `scripts/gate-marker.js` already makes about dependencies, applied to the network.

**D15 — the prune window is the integration branch's last 200 commits** (`HARNESS_RECORD_WINDOW`). D5 said pruning rides on a write that already happens; this is what "has left the integration branch's recent history" means mechanically. It is coherent because a composite tree that *lands* becomes an integration-branch tree, so what ages out is exactly the trees that never landed. Records are a cache with the standing of the local marker directory, not a revived run ledger (ADR 0015).

**D16 — the landing script decides and merges; it never pushes a *branch*, and never runs the gate.** It is invoked as one Bash command, so a branch push it made internally would be invisible to `hooks/push-target-guard.js` — the script would become the way around the guard it exists to satisfy. It prints the push for the agent to run through the tool the hook can see, so there is one adjudicator and it stays the hook. It *does* push `refs/harness/*`: `done` publishes a gate record and advances the green pointer, and those refs move no branch and authorise nothing. The invariant a guard can hold is therefore *no verb pushes a branch*, not *no verb pushes* — the second is the stronger sentence and the weaker check. It does not run the gate either: law 3 obliges the agent to run it and read the output, and a script that swallowed the run would take the reading with it. *Rejected:* a single `land` verb that carries a landing end to end, which would have to resolve a conflict — a judgment, not a decision a script can make.

### Modelled

Carried from `drift-reconvergence` with its inputs unchanged, still assumptions: exposure window 15 min falls to about 5 s, collision probability at λ≈8/hr falls from 87% to 1.1%, expected attempts to land fall from 7.4 to about 1.01.
