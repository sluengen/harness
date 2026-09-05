---
proposal: lifecycle-reset
status: accepted         # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-04
decided: 2026-09-05
related: [drift-reconvergence, structured-explorer-and-repair-build-loop, purpose-before-proof, plugin-surface]
research: research/INDEX.md
---

# Proposal: reset the lifecycle, top to bottom, on six principles

> Longer cycle times and ballooning work are one feedback loop. This proposal restates the principles so each can refuse something, redraws the lifecycle as three lanes sized by blast radius, moves spend from downstream detection to upstream prevention, deletes the machinery that re-implements the host, and ships with the measurements that would show it working or not. The landing posture decided on 2026-09-04 is carried unchanged.

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

Inside the harness itself, the plugin carries **28 skills**, of which 9 are generated `command-*` mirrors of the 9 command files (621 lines) and 4 are generated `agent-*` mirrors of the 4 agent files (171 lines); a 375-line generator, a gate stage, and tests exist to keep those mirrors byte-faithful. The 5 hooks are 2,859 lines of JavaScript. `commands/build.md` is 143 lines of normative procedure read once at the start of a run that then spans many sub-agent contexts. The review loop reached cycle 4 on twelve recorded occasions and cycle 5 on two; #510 took seven. Median ticket open-to-close over the last 200 closed tickets is 16.8 hours.

The prior version of this proposal measured the guard ratchet directly: 151 test modules before the v5 cull, 25 after it, 45 fourteen days later. **A cull without a stated basis for refusal resets the counter and changes nothing else.** That basis is what the principles below supply.

### What the research adds

*research/* (September 2026, evidence-tagged, untracked at acceptance) changes the diagnosis in four ways:

- **Ambiguity is the precondition for cheating.** Clear reward hacking runs at 0.7–3.4% on unambiguous tasks and 22–44% on ambiguous ones (EvilGenie; ambiguous set n=9, direction strong, magnitude not). The harness spends heavily on detecting bad work downstream and little on removing ambiguity upstream.
- **Instruction does not stop test modification.** Claude models concentrate over 79% of their cheating in editing tests directly, despite explicit instructions (ImpossibleBench). Read-only tests during implementation is the single highest-yield missing control, and it belongs in a hook, not a sentence.
- **Guidance is verified by use.** Anthropic's published skill loop is: evaluations first, the minimum instructions that pass them, iterate on observed behaviour. This is the answer to "how do you test a process document", and it is the capability the harness lacks. It also explains why the prose guards regrew: nothing else was available.
- **Harnesses are pruned as models improve.** "Every component in a harness encodes an assumption about what the model can't do on its own." Anthropic deleted its own sprint layer when a model made it unnecessary. Nothing in this repo names the assumption each component encodes, so nothing can retire one.

## The principles

Each states what it rules out, because a principle that cannot refuse anything is a preference. The operator's five are kept and sharpened; one is added.

**1. Native first.** Use what Claude Code and Codex already do: plan mode, `AskUserQuestion`, sub-agents with `isolation: worktree`, `effort:` and `model:` frontmatter, Stop hooks, path-scoped rules, skills-as-commands, the official `github` and `linear` plugins, the skill-eval tooling, the sandbox. Re-ask on every model and host release. *Refuses:* any parser, generator, or guard that re-implements a host feature, and any component that cannot name the model limitation it assumes.

**2. Balance the four axes: quality, speed, cost, risk.** *Refuses:* driving one axis to the floor. A guard that buys risk mitigation at unbounded cost to speed fails this while working exactly as designed. A stage whose benefit cannot be distinguished from noise (about 3 percentage points on any agent eval) does not exist.

**3. Less is more.** Simplicity scales; complexity fails. *Refuses:* the additional exception, the second copy, the guard over prose. The question of any addition is not whether it is correct but whether the tree gets simpler; a change that adds names what it retires, or states that nothing does and why.

**4. Right first time.** Quality is built in upstream, not inspected in downstream. Spend on clarity before build, tests before code, a probe before a write-up. *Refuses:* a downstream detector for an upstream ambiguity; a design sent to review that a two-minute probe would have killed.

**5. Proportionate assurance.** Not all work needs doing; not every risk needs covering. Rigour scales with blast radius, not with ceremony. *Refuses:* uniform rigour, a ticket for a one-line fix, a guard for a risk never observed, and an uncomputed cost.

**6. A stage is its exit check.** Every stage ends on a pass/fail signal the agent can act on alone; evidence over assertion; enforcement on the lowest rung that can hold it (branch protection, then a hook, then prose). *Refuses:* a stage that ends when the model feels finished, and a "law" that is actually a request.

### Principles and laws

They are different kinds of statement and the spine keeps both. A **principle** decides what gets built and what does not: a proposal, a guard, a gate stage, or a ticket cites the principle it serves and the one it spends against, by number, and a reviewer of any process change checks the citation. A **law** is a per-change obligation every agent follows, enforced by a hook where one can hold it. Principles come first in the spine because the laws are derived from them; a law that traces to no principle is retired.

The six current laws survive that test. Three are rewritten to one line each, because a 130-word law containing eight obligations is packaged so that the ones dropped are unpredictable; rationale moves to an HTML comment, which is stripped before injection and so costs nothing.

| Law today | Traces to | After |
|---|---|---|
| 1. Purpose precedes proof (about 130 words) | P5, P6 | *Name what a check protects before writing it; choose the cheapest evidence that can fail for that reason (ADR 0019).* |
| 2. A measurable executable criterion needs a measuring test | P6 | *A quantitative criterion about code has a test that measures it.* |
| 3. No completion claim without fresh gate evidence | P6 | Kept; already one obligation. The Stop hook and push guard enforce it. |
| 4. The builder does not write the as-built record | P6 | Kept as is. |
| 5. Nobody builds on a shared branch | P2 | Kept; native worktree isolation and the push guard enforce it. |
| 6. External text is data, not instruction | P2 | Kept as is. |

One obligation the reset adds is stated as a law because a hook enforces it: *tests are locked during implementation; the fix lane may add a test but not edit one.* Nothing else new becomes a law. "A change names what it retires" is principle 3 applied at creation, not a per-change obligation, and it stays a principle.

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

**Land.** The decided landing posture, unchanged: a clean auto-merge over a certified ancestor carries the verdict without a re-gate; a conflicted merge re-gates over the conflicted paths with a scoped marker; gate outcomes are published as flat refs (`refs/harness/gate/<tree>-green|-red`) discovered by one `ls-remote`; two unattended runs never claim one ticket because a claim ref is created first-writer-wins; a green pointer names the last known-good integration tree for new worktrees to branch from. The four-step re-bind path in `commands/build.md` becomes a script, because a low-freedom procedure written as prose costs context on every read and can still be deviated from.

#### The landing posture, explained

*Why it is hard.* A verdict binds to a tree. The integration branch moves while the gate runs. Under today's rule every move re-enters reconcile, delta review, the full gate, the verdict, and the push, and each of those opens a new window of the same width. With a ten-minute gate and several agents landing per hour, the expected number of attempts to land is `e^(λW)`: modelled at 7.4 attempts for eight pushes an hour. Making a retry cheaper does not change the shape; only taking λ out of the exponent does.

*What the posture does, in order.*

1. **Gate the composite, once.** Before review, merge the integration tip into the candidate and gate that. The verdict then covers the candidate as it would land at that moment, not as it was authored.
2. **At push, three cases.** The integration tip has not moved: push. It moved and `git merge` is clean with no authored bytes: git alone proves the merge added nothing a reviewer has not seen (one merge base, parents exactly the passed commit and the incoming tip, a clean index and worktree, no staged resolution), so the push guard accepts a marker over the certified parent and there is no re-gate and no re-review. It moved and the merge conflicts: the resolution bytes are the only thing nobody has verified, so the run re-gates over the conflicted paths with a marker that names its scope (the full gate where the repo declares no scoped command), then pushes.
3. **Share what was learned through git refs, not a service.** `refs/harness/gate/<tree>-green|-red` are blob refs read by one `ls-remote` in about a second with no object transfer, so a red integration branch is found by the next builder's composite gate rather than by a CI job these repos do not run. `refs/harness/claim/<ticket>-<bucket>` is created first-writer-wins, so two unattended runs never build one ticket; claims expire by time bucket, so no force-push is ever needed. `refs/harness/green/<integration>` names the last tree known green, so new worktrees branch from it rather than from a possibly-red tip.

*What it mitigates:* the exponential; a lock server or merge queue; a CI dependency; two routines on one ticket; building on a red base.

*What it accepts, stated as the trade (principle 2):* a silent semantic merge inside a shared file, two individually green changes whose combination is wrong, lands and is caught by the next composite gate; a red integration branch persists until the next build rather than the next CI run.

*What was killed by a probe:* lease-stealing with `--force-with-lease`, refused by the force-push guard in two minutes (probe 5), replaced by bucket rotation, which is simpler than what it replaced.

**Record and close.** Tracker transition, worktree cleanup, and the **queue growth line** in `/digest` (the "R line"): one line stating tickets opened versus closed in the window, with the opened count split by source, filed from use because the tree contradicted itself, promoted by the operator from the ledger, or filed by the operator directly. Read once a day, it is the only place the queue's growth rate is visible.

## Mechanisms

What changes in the tree to make the lifecycle above true. Each names its cost and what it retires (principle 3).

### Spine and configuration

- **One source file, `AGENTS.md`;** `CLAUDE.md` becomes `@AGENTS.md` plus Claude-specific deltas. Retires `scripts/generate_codex_artifacts.py` (375 lines), the codex drift gate stage, and its tests. *Verify first:* that Codex reads `skills/` from the plugin manifest (it declares `"skills": "./skills/"`) and needs nothing from `commands/`; a probe, not an argument.
- **Configuration leaves the prose.** The `repo: / tracker: / commands: / branches: / loop: / paths:` block moves to `harness.yaml`, read by hooks and skills alike. Retires the three hand-rolled spine readers in the hooks and the class of bugs they carried (#487, #488, #510).
- **Laws become obligations.** Under 120 lines, one imperative per line, rationale in HTML comments (stripped before injection, so free). Emphasis spent on at most two lines. Path-scoped rules (`.claude/rules/*.md` with `paths:`) carry what only matters in `scripts/` or `design/`.

### Skills: 28 → about 9

Keep the product, the lifecycle the model would get wrong without it: `engineering`, `review-discipline`, `authoring`, `work-discovery`, `worktree-isolation`, `architecture`, one merged `assess` (from `assessment-craft` + `process-economy`). **`spec-authoring` becomes `authoring`**: one skill for every artefact written for a downstream agent, a proposal, a change spec, a ticket (which is a prompt), a design hand-off, an as-built record. Precise, descriptive, no bloat, whatever the artefact; the old name narrowed it to specs while the same discipline governs the ticket a builder reads. It absorbs `writing-quality`, and its description carries the triggers. Command workflows ship once, as skills with `disable-model-invocation: true`, serving both hosts; the 9 generated `command-*` and 4 `agent-*` mirrors go. `systematic-debugging` and `infrastructure` face the deletion test (would the agent get this wrong without it?). `ux-design` and `design-system` become path-scoped rules in the repos that have a design layer.

*The provider swap, as probed.* The official marketplace carries `github` ("Official GitHub MCP server"), `linear` ("Linear issue tracking integration"), and `atlassian`. All three are **MCP transports, not recipes**: the marketplace entries carry no version, and the local plugin cache holds no skill content for either `github` or `linear`. So the swap is narrower than replacing our two provider skills. Those skills carry two things: API recipes (`gh` invocations, the Projects v2 GraphQL for board status, Linear's state and label id resolution), which are commodity and rot; and the harness's ticket semantics (states, hold = comment + label + assignment, explicit Todo placement verified by re-reading, the ledger found by label), which are product. The transport is swapped for the official MCP where the repo has it; the semantics collapse into one thin `tracker` skill of ours that works over whichever transport the repo declares, `gh` or MCP. Two probes before the swap lands: whether the GitHub MCP server can set a Projects v2 item's Status (the one write our recipes do that a generic issue API may not), and whether an unversioned MCP plugin can be pinned at all; where it cannot, the `gh` recipe for that single operation stays and the risk is recorded.

Every kept skill and agent gains `effort:` and `model:` frontmatter, so the lane sets cost through the runtime rather than through prose the agent may not honour. ADR 0005 already measured 110 Opus reviews against 114 Sonnet at 18.4% vs 17.3% fail rate, under the noise floor: the change-lane reviewer defaults to the cheaper model.

*How that is applied from a plugin file.* On Claude Code, `model:` and `effort:` are frontmatter fields on both skills and agents, read by the runtime when the file is loaded, plugin files included; a skill with `context: fork` applies them to the forked sub-agent, and the orchestrator can also pass a model override at dispatch. The lane therefore selects cost in one of two native ways: by which agent definition it dispatches (a change-lane reviewer and a feature-lane reviewer are two small agent files that differ in those two lines), or by the override on the call. Codex accepts only the six standard skill fields, so there the same choice is made in the Codex agent definitions and profile configuration; where a host offers neither, the lane still runs, at that host's default cost. Nothing here asks the model to honour a tier. That was the mechanism ADR 0005 retired, and rightly: it cost a tracker round trip and five degradation branches to read a label nobody set.

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

- Bugs are filed; improvements are proposed. Kept. The proposals ledger stops being memory that never expires: an entry not promoted at the next `/assess` drain is **deleted**. Shipped, rejected, and superseded proposals leave `specs/proposals/` (git history keeps them); `specs/retired/` (6,329 lines) leaves the tree.
- A filed ticket, a proposed guard, and a new gate stage each carry **one line of cost and benefit** at creation. Convention, no guard.
- A ticket filed from a breakdown carries its dependencies and its urgency in the tracker's own fields, never only in prose, so sequencing is enforced by `work-discovery` reading them rather than by an operator repeating the order. The `tracker` skill's filing recipe requires both (T4).
- `/assess` computes the module count and the guard-to-deliverable ratio every pass, using the derivations in this document.
- **A retirement table**, *specs/harness-assumptions.md*: one row per component naming the model limitation it assumes and the test that would show the limitation gone. Reviewed at every model or host release. This is the standing basis for refusal the v5 cull did not have.

### What stays, verbatim

The harness is ahead of the published state of the art on these, and the reset keeps them: the gate marker bound to a **tree oid**; a fresh reviewer that never sees the builder's conversation; **RED for the right reason**; **DEFER** as distinct from FAIL; hold = comment + label + assignment; **Grounding** with `path:line` anchors; the ticket body as the change spec; **bugs filed, improvements proposed**; the assurance label chosen at filing and upgrade-only; reconciliation placed adjacent to final binding; gate records as `ls-remote`-discoverable refs.

## Options

**Option A — principles as guidance only.** Free, and what the v5 cull did; the ratchet table measures the result.

**Option B — the reset as written, as five sequenced tickets.** Principles enter the spine as a numbered list later work cites; the lanes, the intake loop, the test lock, the scoped review, the landing posture, the deletions, the evals, and the retirement table follow in dependency order. *Trade-offs:* the largest single change since v5; the first two tickets change the machinery that would review them, so their assurance concentrates at the operator's merge review, as v5 did. The measurement plan is what keeps it honest.

**Option C — the reset without the deletions.** Add the lanes, the intake loop, and the test lock; keep the mirrors, the providers, and the 28 skills. *Trade-offs:* every gain in cycle time, none in complexity; the listing budget and the compaction budget keep dropping the skills a stage needs. Fails principle 3 on its face.

**Option D — landing posture only** (the previous version of this proposal). Removes the exponential; leaves the loop that produced it.

## Recommendation

**Option B.** A and D leave the loop intact and C leaves the cost intact. The order inside B is chosen so each ticket leaves the gate green and can be measured on its own.

## Open decisions

| # | Decision | Recommendation | Who | Recorded in |
|---|---|---|---|---|
| D1 | Do the six principles enter the spine as a numbered list that later work cites by number, ahead of the laws, with each law rewritten to one line citing its principle? | Yes; see *Principles and laws*. No law is retired; three shrink; one is added for the test lock | user | `AGENTS.md` |
| D2 | The fix lane ships on the gate alone, with no reviewer sub-agent. Accept the residual risk named above? | Yes; the next composite gate and the next reviewer on that surface are the backstop | user | spine, `harness-assumptions.md` |
| D3 | Test lock: enforced by a hook, or instructed? | Hook; instruction is measured not to work | user | `hooks/` |
| D4 | Transport swapped to the official `github` / `linear` MCP plugins, with one thin `tracker` skill of ours keeping the ticket semantics? | Yes, after two probes: Projects v2 Status writes over MCP, and whether an unversioned MCP plugin can be pinned | user | `plugin.json`, `tracker` skill |
| D5 | Codex surface served by the skill form alone, deleting the generator? | Yes, after the read-path probe | user | ADR |
| D6 | Review ceiling 3, `unconditional_review_cycles` deleted? | Yes | user | `harness.yaml` |
| D7 | As-built record owed only in the feature lane and on a documented-behaviour change? | Yes | user | `review-discipline` |
| D8 | Ledger entries not promoted at a drain are deleted? | Yes | user | `proposals-ledger.md` |

## Breakdown

Five tickets, filed on acceptance through `/propose`, each carrying the brief below as its change spec. The first two change the machinery that would otherwise review them, so their assurance concentrates at the operator's review of the merge, as v5 did; the rest go through the lanes as any change does. Every criterion names its evidence, and every number here is derived in this document or names the command that derives it. A builder who finds a criterion already met by the tree closes it by observation on the ticket rather than rebuilding it.

### T1 — Spine and configuration

*Lane:* feature. *Serves:* P1, P3. *Spends against:* nothing; this ticket only deletes.

**Delivers.** Configuration leaves the prose into `harness.yaml`, read by hooks and skills through one reader. `AGENTS.md` becomes the source instruction file and `CLAUDE.md` becomes `@AGENTS.md` plus Claude-specific deltas. The six principles enter the spine as a numbered list ahead of the laws; the laws are rewritten per *Principles and laws* above, one obligation per line, rationale in HTML comments, with the test-lock law added. The Codex generator, its gate stage, and its mirror tests are deleted after the read-path probe. Path-scoped rules carry what only matters under `scripts/` or `design/`.

**Grounding to verify first.** `templates/spine.md` and the three spine readers in `hooks/gate-evidence-guard.js`, `hooks/push-target-guard.js`, and `scripts/gate-marker.js` (the bug class #487, #488, #510 lived there); `scripts/generate_codex_artifacts.py` (375 lines) and the `codex drift guard` stage of `scripts/verify.sh`; `.codex-plugin/plugin.json` declares `"skills": "./skills/"`.

**Acceptance criteria.**
- AC-1: the hydrated spine is under 120 lines with one imperative per law line. *Evidence:* `wc -l` on a freshly hydrated consumer spine; direct review of the law lines.
- AC-2: the hooks and the marker helper read branch roles, commands, and loop settings from `harness.yaml` through one shared reader, and the three legal `branches:` spellings from #488 parse identically. *Evidence:* the existing hook tests re-pointed at the yaml; RED first on a fixture the old parsers accepted.
- AC-3: Codex discovers the command workflows from `skills/` alone. *Evidence:* the read-path probe, recorded on the ticket before the generator is deleted.
- AC-4: `scripts/verify.sh` carries no codex drift stage, and `scripts/generate_codex_artifacts.py` and its tests are gone. *Evidence:* the gate green over the tree without them.
- AC-5: `/harness:init --refresh` migrates a consumer's existing spine block into `harness.yaml` without losing a declared value. *Evidence:* refresh against a copy of calibrate's and nano-erp's spines, diffed key by key.

**Out of scope.** Any lifecycle semantic (T2), the landing posture (T3), skill content (T5). **Protected areas:** `hooks/` beyond the reader swap; a diff that changes what a hook refuses stops and holds.

### T2 — Lanes, intake, build state, and the scoped review

*Lane:* feature. *Serves:* P4, P5, P6. *Spends against:* P3, by one hook and one JSON file; each named with what it retires.

**Delivers.** Lane rules in the spine with the fix lane real (gate and push guard only). `templates/change.md` and `/capture` gain the clarification loop with its stop condition, `[NEEDS CLARIFICATION]`, an Assumptions section, Protected areas, and the title convention. `/build` refuses a spec with a marker left, is the builder by default, keeps run state in `.harness/run.json`, and dispatches a builder sub-agent only on the two stated conditions. A `PreToolUse` hook refuses edits to test paths while `tests_locked` is true and allows additions in the fix lane. The reviewer's mandate is scoped (correctness, stated criteria, the four cheat categories, justification for every test diff) and review-or-repair replaces review-then-fresh-builder for small in-scope findings. `loop:` becomes `max_review_cycles: 3`; `unconditional_review_cycles` is deleted. The builder's brief gains the stop-and-flag sentence. The as-built obligation is restated per *Review-or-repair* above.

**Grounding to verify first.** `commands/build.md` (143 lines; the sections to cut are *Visual evidence*, the nine-stage lifecycle block, and the four-step re-bind, which T3 scripts); `skills/review-discipline/references/fail-stop-rule.md`; the sibling proposal `structured-explorer-and-repair-build-loop` for the repair contract, which this ticket adopts rather than re-decides; `hooks/workflow-guard.js` for the hook shape.

**Acceptance criteria.**
- AC-1: the hook refuses a write to a path under the repo's declared tests directory while `run.json` says locked, allows a new test file in the fix lane, and allows any test write when no run state exists. *Evidence:* RED then GREEN in the hook suite, one test per condition, each proven able to fail by deleting its condition.
- AC-2: `/build` refuses to start on a spec containing `[NEEDS CLARIFICATION` and says which line. *Evidence:* direct use on a fixture ticket.
- AC-3: a run killed after the build stage resumes at the same stage from `run.json`. *Evidence:* direct use; the run report names the resumed stage.
- AC-4: `commands/build.md` is under 70 lines and names no procedure a script now owns. *Evidence:* `wc -l`; direct review.
- AC-5: the reviewer agent's brief carries the scoped mandate and the four cheat categories, and a diff to a test file appears as an explicit item in its report. *Evidence:* one representative review run whose report shows the item.

**Out of scope.** Landing (T3). The visual-evidence rules move to a stage-loaded reference under `review-discipline` unchanged in substance. **Protected areas:** `hooks/push-target-guard.js` and `hooks/gate-evidence-guard.js`; a diff reaching them stops and holds.

### T3 — Landing posture

*Lane:* feature, as eight tickets already broken down on 2026-09-04 and unchanged: the push-guard second acceptance path; the spine restatement of law 3 in authored-tree terms; the gate-record protocol; the claim protocol; the scoped re-gate on the conflict path; the `/build` stages; the green pointer; cost/benefit at creation. Their criteria stand as written in *The first instance* below. Two additions from this revision: the four-step re-bind path ships as a script under `scripts/` with the command file explaining only when it applies; and the marker gains `started_at`, so gate duration is measured from the first week. *Serves:* P1, P2, P5.

### T4 — Prune

*Lane:* feature. *Serves:* P1, P3. *Spends against:* nothing.

**Delivers.** Skills 28 → about 9: the kept set (`engineering`, `review-discipline`, `authoring`, `work-discovery`, `worktree-isolation`, `architecture`, `assess`) plus the command workflows as skills with `disable-model-invocation: true`; the 13 generated mirrors, `writing-quality` (absorbed), `systematic-debugging`, `infrastructure`, `ux-design`, and `design-system` (the last two re-homed as path-scoped rules in repos with a design layer) deleted; `github-issues` and `linear` collapsed into one `tracker` skill over the transport the repo declares, after the two D4 probes. **The `tracker` skill owns sequencing:** every ticket filed from a breakdown carries its dependencies as the tracker's native blocked-by relationships (GitHub's issue dependencies; Linear's blocking relations) and an urgency on the board's Priority field, and `work-discovery` reads both, so a blocked ticket is never picked and a P1 outranks a P2 when neither is blocked. A ticket filed without either is an incomplete filing, the same way a ticket without an assurance label is. Every kept skill and agent carries `effort:` and `model:`, with a change-lane and a feature-lane reviewer definition. *specs/harness-assumptions.md* is created with one row per component. `specs/retired/` and settled proposals leave the tree. The ledger's default-delete rule lands in `proposals-ledger.md`. `/assess` derives the module count and the guard-to-deliverable ratio.

**Acceptance criteria.**
- AC-1: the skill listing is under the host's 1% budget with the count of descriptions reported. *Evidence:* the sum of description lengths, derived and recorded.
- AC-2: every hook, script, skill, and agent has a row in *specs/harness-assumptions.md* naming the model limitation it assumes and the observation that would retire it. *Evidence:* direct review against `git ls-files`.
- AC-3: the `tracker` skill performs create, state transition, hold, Todo placement, and ledger append on both a GitHub and a Linear repo. *Evidence:* direct use against a scratch issue on each, recorded on the ticket.
- AC-4: the two D4 probes are recorded with their outcome before any provider recipe is deleted. *Evidence:* the ticket comment.
- AC-5: the `tracker` skill's `create` recipe sets a blocked-by relationship and a Priority value when the filer supplies them and reports the filing incomplete when a breakdown ticket supplies neither; `work-discovery` skips a ticket with an open blocker and prefers the higher Priority among unblocked candidates. *Evidence:* direct use on scratch issues, one blocked and one not, with the pick recorded.

**Out of scope.** Rewriting the content of kept skills (T5). **Protected areas:** none new; deletions are the whole diff.

### T5 — Skills and agent content remediation

*Lane:* feature. *Serves:* P1 (delete what the model already does), P3, P6 (guidance verified by use). *Spends against:* P3, by adding *evals/* directories; bounded below. *Depends on:* T4, so the set being refined is the set being kept.

**Intention.** The kept skills and the four agents are the product. Their content has never been verified by use, only by reading; two are written as paragraphs rather than instructions, emphasis is spent, references chain, and descriptions under-specify their triggers. This ticket makes each one leaner, explains its reasoning instead of asserting it, and proves the result with a recorded with-and-without delta. It does not change what the lifecycle means; T2 owns that.

**In scope.** the seven kept skill directories under `skills/` (engineering, review-discipline, authoring, work-discovery, worktree-isolation, architecture, assess) including their *references/* subdirectories, and the four files under `agents/` (architect, dev, reviewer, steward). The command-workflow skills are in scope only for the description and for cutting text T2 made redundant.

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
2. Write two or three realistic prompts, drawn from recorded failures: the defect classes in `skills/review-discipline/references/craft.md`, the `/assess` reports under `specs/`, and the operator's ledger of tickets that went past review cycle 3. Save them to *evals/evals.json* inside the skill. A prompt is realistic when a builder or reviewer in a consuming repo would actually type it, with file paths and a ticket shape.
3. Run each prompt with the current skill and with the snapshot, in fresh sub-agents, in the same turn. Save outputs and timing; draft assertions while they run; grade with the plugin's grader; aggregate the benchmark; generate the viewer for the operator.
4. Rewrite. Apply, per line, "would the agent get this wrong without this sentence?" and cut what fails it. One obligation per sentence. The reason beside the rule instead of emphasis. References one level deep from `SKILL.md`, each with a stated moment to load it. A table of contents at the head of `craft.md`. No time-bound content; a superseded pattern goes in a collapsed section or is deleted. The description states what the skill does, when to use it in the words a user would say, and what it is not for; under 1,024 characters.
5. Re-run the prompts against the rewrite and the snapshot; record the delta.
6. Run the plugin's description trigger loop: twenty queries, half of them near-miss negatives that share vocabulary with the skill, three runs each; adopt the held-out winner.
7. Agents: keep each thin. An agent file names the role, the tools, `isolation`, `model`, `effort`, the skills it loads, and what it must not do; it does not restate a skill. Verify by reading each agent against the skills it cites.
8. The alignment read, once, across the whole kept set: one vocabulary for lanes and labels, verdicts, the marker, the hold. Each term is defined in the spine and used, never redefined, in a skill. A grep for a second definition of any contract term is the check.

**Bound.** Three prompts and two rewrite iterations per skill unless the recorded delta is still moving; roughly 130 sub-agent runs in total, which is the budget this ticket states. *evals/* holds prompts, assertions, and the benchmark of the last iteration; it holds no transcripts.

**Acceptance criteria.**
- AC-1: every kept skill has *evals/evals.json* and a recorded with/without benchmark whose pass-rate delta clears the noise floor stated in *Measurement*, or the skill is cut and the retirement table says why. *Evidence:* the benchmark files; the retirement table.
- AC-2: no kept skill cites more than three other skills, and no reference is reached through another reference. *Evidence:* the grep that produced the starting line, re-run.
- AC-3: `craft.md` opens with a table of contents; no `SKILL.md` exceeds 1,800 words; no `SKILL.md` carries more than twelve bold spans. *Evidence:* `wc -w`, `grep -c`. These three are proxies for the rewrite rules, and the ticket says so; AC-1 is the real exit.
- AC-4: each kept skill's description scores at or above the plugin's threshold on the held-out trigger set, with the near-miss negatives recorded. *Evidence:* the trigger loop's report.
- AC-5: each agent file is under 60 lines, sets `model` and `effort`, and cites only skills that exist. *Evidence:* `wc -l`; a tree-consistency check that each cited skill directory exists.
- AC-6: the alignment grep finds no contract term defined in more than one place. *Evidence:* the grep, recorded.

**Out of scope.** New skills. Any change to what a verdict, lane, hold, or marker means (T2). Any test or guard over the wording of a skill: ADR 0017 D5 forbids it, and the evals are the verification. **Protected areas:** `hooks/`, the spine's contract section, `templates/`; a content edit that reaches them belongs to T1 or T2 and stops here.

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

### Modelled

Carried from `drift-reconvergence` with its inputs unchanged, still assumptions: exposure window 15 min falls to about 5 s, collision probability at λ≈8/hr falls from 87% to 1.1%, expected attempts to land fall from 7.4 to about 1.01.
