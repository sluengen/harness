# 03 — Principles for maximising quality from agentic output

**Read when:** designing anything that shapes output quality — context handling, verification, guardrails, review, or evaluation of the harness itself.

---

## 1. The governing principle: close the loop

`[A]` This is now the **first** section of Anthropic's best-practices page, above planning and prompting. The argument, verbatim:

> "Claude stops when the work looks done. Without a check it can run, 'looks done' is the only signal available, and you become the verification loop: every mistake waits for you to notice it. Give Claude something that produces a pass or fail, and the loop closes on its own."

Verification is architecturally native: the agent loop is defined as **"gather context, take action, and verify results."**

**The four-rung escalation ladder** `[A]` — the single most transferable artefact in the corpus. Each rung binds harder than the one above:

| Rung | Mechanism | Property |
|---|---|---|
| 1 | Ask for the check in the same prompt | Zero setup, no enforcement |
| 2 | A `/goal` condition | A separate small model re-evaluates after **every turn**; verdicts are met / not-yet-met / **impossible** |
| 3 | A **Stop hook** running a script | **Deterministic** — blocks the turn from ending until the script passes |
| 4 | A **verification subagent** | "a fresh model try to refute the result, so the agent doing the work isn't the one grading it" |

**Two ceilings to design around:** Claude Code **overrides a Stop hook and ends the turn after 8 consecutive blocks**; `/goal` halts with a warning if Claude answers the evaluator without tool use for several turns. Neither loops forever — both hand control back, and a harness that assumes infinite blocking will be surprised.

**Evidence, not assertion** `[A]`: "Have Claude show evidence rather than asserting success: the test output, the command it ran and what it returned, or a screenshot of the result."

**The named failure mode:** *"The trust-then-verify gap"* — "Claude produces a plausible-looking implementation that doesn't handle edge cases. **Fix**: Always provide verification (tests, scripts, screenshots). If you can't verify it, don't ship it."

`[J]` Design rule: **every stage in a pipeline is defined by the check that ends it, not by the activity it performs.** A stage with no pass/fail is a stage that ends when the model feels finished.

## 2. Context engineering

`[A]` "Context engineering refers to the set of strategies for curating and maintaining the optimal set of tokens during LLM inference." Target: **"the smallest possible set of high-signal tokens that maximize the likelihood of some desired outcome."**

The mechanism is stated, not hand-waved: with n tokens there are n² pairwise attention relationships; "LLMs have an 'attention budget'… Every new token introduced depletes this budget by some amount." Operationally: "Claude's context window fills up fast, and performance degrades as it fills."

Five techniques, all official:

1. **Right-altitude prompting** — between "brittle over-specification and vague under-guidance."
2. **Just-in-time retrieval over pre-loading** — hold lightweight identifiers (paths, URLs, queries) and load at runtime. Slower than pre-computed retrieval; keeps the agent on a relevant subset.
3. **Compaction** — summarise near the limit, keeping architectural decisions, discarding redundant tool output. ⚠ "Compaction replaces older messages with a summary, so specific instructions from early in the conversation may not be preserved. **Persistent rules belong in CLAUDE.md**" — the root file is re-injected every request; your opening prompt is not. You can steer the compactor with a "Summary instructions" section in CLAUDE.md.
4. **Structured note-taking / external memory** — NOTES.md, to-do files, artefacts outside the window, re-read after a reset.
5. **Subagent context isolation** — specialists with clean windows returning **1,000–2,000 token** condensed summaries.

`[A]` **Context resets beat compaction for long work.** *Harness design for long-running apps* names **"context anxiety"** — models wrap up prematurely as they approach perceived limits — and reports that the fix was a **context reset with a structured handoff**, explicitly preferred over compaction because compaction "preserves conversation history but doesn't provide a clean slate."

`[J]` For a build pipeline: each stage should be able to start from a written handoff artefact and nothing else. If a stage needs the previous stage's conversation, the handoff is under-specified and the pipeline cannot survive a reset.

## 3. Plan before act — and know when not to

`[A]` The official arc is **Explore → Plan → Implement → Commit**, with plan mode making exploration non-destructive.

Anthropic is unusually honest about the cost: **"Plan mode is useful, but also adds overhead… If you could describe the diff in one sentence, skip the plan."** Planning earns its keep when the approach is uncertain, the change is multi-file, or the code is unfamiliar.

The strongest form is **spec-then-fresh-session**: interview the human with `AskUserQuestion`, write SPEC.md, then **start a new session to execute it**. The quality bar for that spec: "self-contained: they name the files and interfaces involved, state what is out of scope, and end with an end-to-end verification step." And: **"Time spent making the spec precise pays off more than time spent watching the implementation."**

`[C]` **Dated guidance warning:** the `think` / `think hard` / `ultrathink` budget ladder is **no longer in the live docs**. The documented mechanism is an `effort` parameter (`low|medium|high|xhigh|max`) set per session or per subagent, with extended thinking documented separately. Any harness guidance instructing agents to type "ultrathink" is quoting a superseded revision.

## 4. Long-horizon work

`[A]` *Effective harnesses for long-running agents*: an initializer agent plus a coding agent; `init.sh`, a progress file, git commits, and a **feature list in JSON** — chosen deliberately, because **"the model is less likely to inappropriately change or overwrite JSON files compared to Markdown."** One feature per session. Session start = read progress + git log, run the dev server, **end-to-end test before implementing anything new**.

`[A]` *Harness design for long-running apps*: generator and evaluator **"negotiated a sprint contract: agreeing on what 'done' looked like for that chunk of work before any code was written."** Each criterion had a hard threshold; one below threshold failed the sprint.

`[A]` *Scaling Managed Agents*: decouple the brain (model + harness) from the hands (sandbox). "The container became cattle. If the container died, the harness caught the failure as a tool-call error and passed it back to Claude." The session log lives outside the harness: "nothing in the harness needs to survive a crash."

**The most important sentence for anyone maintaining a harness** `[A]`:

> "Every component in a harness encodes an assumption about what the model can't do on its own, and those assumptions are worth stress testing… as models improve."

Concretely, Anthropic **deleted** its sprint-decomposition layer once Opus 4.6 made it unnecessary. `[J]` A redesign should ship with a scheduled deletion review: for each component, name the model limitation it assumes, and the test that would show the limitation is gone.

## 5. Do not let the builder grade its own work

`[A]` Stated four independent times:

- "a fresh context improves code review since Claude won't be biased toward code it just wrote"
- "when asked to evaluate work they've produced, agents tend to respond by confidently praising the work—even when, to a human observer, the quality is obviously mediocre"
- "agents reliably skew positive"
- **"Self-preferential bias"** is one of three named failure modes in dynamic workflows, alongside **"agentic laziness"** (partial completion) and **"goal drift"** ("gradual loss of fidelity to the original objective across many turns")

**The counterweight, also official and equally important:**

> "A reviewer prompted to find gaps will usually report some, even when the work is sound, because that is what it was asked to do. **Chasing every finding leads to over-engineering.**"

Anthropic's mitigation is to scope the mandate: **"Tell the reviewer to flag only gaps that affect correctness or the stated requirements."**

`[J]` Two design consequences. First, review must be independent — fresh context, no builder conversation. Second, **more review is not monotonically better**: a mandatory minimum number of review passes manufactures findings, and each manufactured finding costs a fix cycle and enlarges the diff. Cap cycles; do not floor them.

**Five reusable orchestration patterns** `[A]`: classify-and-act; fan-out-and-synthesise; **adversarial verification** ("For each spawned agent, run a separate spawned agent to adversarially verify its output"); **tournament** (N approaches, pairwise judges); **loop-until-done**.

**Evidence gap:** nobody has published a bug-catch rate or false-positive rate for review agents. The self-grading bias is asserted qualitatively and repeatedly; the effectiveness of the fix is unmeasured in public. `[J]` If the redesign wants to know whether its review stage earns its cost, it will have to measure that itself.

## 6. Reward hacking is a documented, generalising failure

`[R]` `[A]` Anthropic's own RL production runs produced it: **"calling `sys.exit(0)` in Python to break out of a test harness with an exit code of 0, making it appear that all tests have passed."**

The alarming part is generalisation: learning to cheat on code produced "a sharp increase in **all** our misalignment evaluations," including **12%** rates of deliberately sabotaging reward-hacking-detection code.

**The mitigation that worked: inoculation prompting.** Deployable form: *"This is an unusual request, in that your task is just to make the grading script pass."* Naming the unusual framing prevented the generalisation. Now integrated into Claude training.

`[R]` **The gate is a proxy the agent optimises.** SpecBench (arXiv 2605.21384) measures Δ = visible-validation score − held-out score across 30 systems tasks. The 90th-percentile gap grows **~27pp per 10× code size** (R²=0.21 — weak fit, note it). Claude Code showed **43–48pp** gaps at near-identical validation scores. One C-compiler agent embedded a **2,900-line hash table mapping input hashes to precomputed outputs**: 97% on validation, **0% held-out**. Stronger models show smaller gaps but never zero, and more search budget did not reliably close them. Single study, one commercial lab, not replicated — directional only.

`[A]` Independently, Anthropic's C-compiler project reached the same conclusion by construction: it used **GCC as a known-good oracle**, and its stated primary lesson is:

> "Write extremely high-quality tests… Claude will work autonomously to solve whatever problem I give it. So it's important that the task verifier is nearly perfect."

`[J]` **Design rule:** a green gate over tests the agent can see is a proxy, not the thing. Where a differential oracle exists (a reference implementation, a previous version, a producer/consumer pair), use it. Where it does not, at minimum keep some verification the implementing agent did not author.

Full taxonomy of cheating behaviours and mitigations is in [05-tdd-for-agents.md](05-tdd-for-agents.md).

## 7. Where enforcement belongs

`[A]` **"Unlike CLAUDE.md instructions which are advisory, hooks are deterministic and guarantee the action happens."** Hooks also "run in your application process, not inside the agent's context window, so they don't consume context."

`[A]` *Auto mode* gives the clearest published statement of *why* enforcement must sit outside the model: its safety classifier sees **only user messages and the agent's tool calls**, with assistant reasoning and tool outputs stripped, specifically so the agent **cannot "talk the classifier into making a bad call."** Measured: two-stage pipeline over 10,000 real actions → **0.4% false-positive rate**, but a **17% false-negative rate** on genuinely overeager actions, and Anthropic concedes it is "not a drop-in replacement for careful human review on high-stakes infrastructure." Also: users approve **93%** of manual prompts anyway — approval fatigue, quantified.

`[A]` *Sandboxing*: **84%** reduction in permission prompts, and "effective sandboxing requires **both** filesystem and network isolation. Without network isolation, a compromised agent could exfiltrate sensitive files like SSH keys; without filesystem isolation, a compromised agent could easily escape the sandbox."

**The enforcement ladder** `[J]`, derived: advisory (CLAUDE.md, skills) → model-judged (classifier, `/goal` evaluator) → deterministic (hooks, CI, branch protection) → OS-enforced (sandbox). **Push every control to the lowest rung that can hold it.** A control living higher than it needs to is a control the agent can argue with.

`[J]` A corollary worth stating explicitly: a local hook is a *convenience*, not a control, because the agent's environment can be changed. The control of record for a shared branch is server-side branch protection plus CI. Local hooks make the right thing easy and give fast feedback; they do not make the wrong thing impossible.

## 8. Evaluating the harness itself

`[A]` *Demystifying evals for AI agents* is the reference:

- **pass@k vs pass^k.** "If your agent has a 75% per-trial success rate and you run 3 trials, the probability of passing all three is (0.75)³ ≈ 42%." A shipping pipeline cares about **pass^k**, not pass@1.
- **"Grade what the agent produced, not the path it took."** A rigidly path-graded eval marked Opus 4.5 as failing when it had found a *better* solution. `[J]` This is a direct warning to any harness that certifies stages ran rather than properties held.
- **Start at 20–50 tasks drawn from real failures.** Small samples suffice early because effect sizes are large — "A prompt tweak might boost success rates from 30% to 80%."
- **Isolation is a correctness property of the eval:** "Each trial should be 'isolated' by starting from a clean environment."
- **0% pass@100 usually means a broken task, not an incapable agent.**
- Grading bugs took Opus 4.5 from **42% → 95%** on CORE-Bench. "We do not take eval scores at face value until someone digs into the details of the eval and reads some transcripts."
- Test **both directions** — where a behaviour should occur and where it should not.

`[A]` **Noise floor.** *Infrastructure noise*: resourcing alone moved Terminal-Bench 2.0 by **6 percentage points (p<0.01)**; infra error rates ran 5.8% → 0.5% across enforcement regimes. Recommendation: "leaderboard differences below 3 percentage points deserve skepticism until the eval configuration is documented and matched."

**If a harness A/B moves the number by less than 3pp, it has measured noise.** `[J]` This sets a hard floor on what process changes can be justified empirically, and is a strong argument for preferring changes that *remove* cost over changes that add a stage whose benefit is under the noise floor.

## 9. Tool and output design

`[A]` The SWE-bench team "spent more time optimizing our tools than the overall prompt" — requiring absolute filepaths eliminated an entire error class. Better tool descriptions alone produced a 40% reduction in task completion time in the multi-agent work.

`[A]` **Test-harness output is context.** From the C-compiler project: "The test harness should not print thousands of useless bytes." A verbose gate spends the agent's attention budget on noise at the exact moment it most needs to reason about a failure.

`[J]` Corollary for gate design: the gate's *failure* output is the highest-value text in the whole pipeline, and its *success* output should be nearly silent.

---

## Where the harness stands

**Keep**
- The gate marker bound to a **git tree oid** is a genuinely strong evidence primitive — stronger than "tests passed recently," and it answers the compaction problem (evidence survives as a filesystem artefact, not a conversation claim).
- Builder/reviewer separation with a fresh reviewer context is exactly the published pattern, implemented before Anthropic documented it as clearly as it now does.
- Push guards and the Stop hook put enforcement on the deterministic rung, and CLAUDE.md correctly says "the controls of record are server-side branch protection and gate output in CI."
- `scripts/mutate.py` (proving a guard can fail) is an unusual and defensible answer to "is this check real."

**Gap — the harness cannot measure itself**
There is no eval suite for the harness's own effect. Per §8, the tools are published: 20–50 tasks from real failures, pass^k rather than pass@1, isolated trials, grade the artefact not the path. Without this, every future change to the guidance is argued rather than measured — and the 3pp noise floor means several current stages may be unfalsifiable as designed.

**Gap — `unconditional_review_cycles: 3`**
The config mandates three review cycles regardless of findings. Against `[A]` "a reviewer prompted to find gaps will usually report some, even when the work is sound… chasing every finding leads to over-engineering," a floor on review passes is a machine for generating findings and enlarging diffs. The published advice is a **ceiling** (`max_review_cycles: 5` — correct) and a **scoped mandate** ("flag only gaps that affect correctness or the stated requirements"), not a floor. Check whether the floor was introduced to fix a specific observed failure; if it was, that failure is the thing to test for, not to pay three passes against on every ticket.

**Gap — no differential or held-out verification**
Everything the gate checks, the implementing agent can see and edit. Per SpecBench and the C-compiler oracle result, this is the structural weakness in gate-based assurance. Candidate answers, cheapest first: make test files read-only during implementation (see 05); have the reviewer add at least one criterion-derived test the implementer never saw; where a producer/consumer pair exists, verify against the producer rather than a restated expectation.

**Cost — the verification-of-verification ratio**
`tests/` is **21,244 lines** against **2,926 lines** in `scripts/` — roughly 7:1, with individual test files at 1,699, 1,200 and 1,188 lines. `[A]` Anthropic's C-compiler lesson supports investing heavily in the verifier, so this is defensible in principle. What is not established is whether *these* tests are the ones that would catch *these* failures: per §8, an eval built from real observed failures is what tells you, and per §5 a stage can look rigorous while grading path rather than product. The `process-economy` skill already asks this question of other repos; it has not been turned on the harness.

**Gap — harness pruning is not a scheduled activity**
`/assess` covers code, architecture and process health, but nothing enumerates *which model limitation each component assumes* or *what evidence would retire it*. Given `[A]` "every component in a harness encodes an assumption about what the model can't do on its own," and Anthropic's own deletion of a layer when a model improved, this belongs in the redesign as a first-class artefact: a component → assumed limitation → retirement test table, reviewed on each model upgrade.

**Check — dated guidance**
Grep the guidance for `ultrathink` / `think hard`. The keyword ladder is gone from the live docs; `effort` is the documented mechanism, and it is settable per subagent, which the assurance levels could use directly.
