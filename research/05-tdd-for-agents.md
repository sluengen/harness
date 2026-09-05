# 05 — Test-driven development for agents

**Read when:** designing the test-first contract, choosing evidence for a change, or defending against test gaming.

---

## 1. The loop

`[A]` Anthropic's original published TDD workflow for Claude Code. *(Provenance: the April 2025 post now redirects to a rewritten page that no longer contains the numbered steps; the wording below is from a widely-reproduced mirror and is corroborated across many independent reproductions. Treat as high-confidence, not first-party-live.)*

1. **"Ask Claude to write tests based on expected input/output pairs"** — with an explicit instruction to avoid creating mock implementations for functionality that does not yet exist.
2. **"Tell Claude to run the tests and confirm they fail"** — explicitly instructing it not to write implementation code at this stage.
3. **"Ask Claude to commit the tests"** once satisfied.
4. **"Ask Claude to write code that passes the tests,"** instructing it **not to modify the tests**, and to continue "until all tests pass." Then: **"it can help to ask it to verify with independent subagents that the implementation isn't overfitting to the tests."**
5. **"Ask Claude to commit the code."**

Note the **five distinct control points** — mock prohibition, fail confirmation, tests committed before code, test immutability during implementation, independent overfitting check. Each maps to a measured failure mode in §3. A harness that keeps only "write tests first" has kept one of five.

`[A]` **The current framing** generalises it: TDD is one instance of "give Claude a way to verify its work," with the four-rung gating ladder in [03](03-quality-principles.md) §1. Also live and load-bearing:

- **Writer/reviewer separation applied to tests:** "have one Claude write tests, then another write code to pass them." `[J]` This is a *stronger* control than instructing immutability, because the implementer never had authorship — it removes the ownership feeling that makes editing a test feel legitimate.
- **A concrete criteria-bearing prompt shape:** replace *"implement a function that validates email addresses"* with *"write a validateEmail function. example test cases: user@example.com is true, invalid is false, user@.com is false. run the tests after implementing."*

## 2. Why TDD suits agents specifically

`[A]` "Claude performs best when it has a clear target to iterate against — a visual mock, a test case, or another kind of output," and this "becomes even more powerful with agentic coding."

`[J]` Four mechanisms, in order of importance:

1. **It supplies the stop condition.** Without one, "looks done" is the only signal.
2. **It bounds the diff.** The smallest code that passes is a much tighter target than "implement the feature."
3. **It converts an ambiguous requirement into a decided one before implementation** — and ambiguity is the measured precondition for cheating (§3).
4. **It makes the criterion falsifiable by someone other than the author.**

`[R]` **Honest verdict on the evidence.** Mathews & Nagappan (arXiv 2402.13521) found "including test cases leads to higher success in solving programming challenges" for GPT-4 and Llama 3 on MBPP/HumanEval — but that is *function-level* generation, the easiest possible setting, and the abstract carries no effect size. A follow-up study explicitly asks whether the result survives at class scope (arXiv 2602.03557). TDD-Agent (arXiv 2608.16742) reports "higher pass rates, coverage, and mutation scores" without numbers in the abstract.

So: **the claim that TDD improves agent output is directionally supported and weakly quantified in public.** The *reward-hacking* half below is far better measured. If you are justifying test-first in a harness, justify it on the anti-cheating and stop-condition grounds, which have data, not on a productivity delta, which does not.

`[C]` TDD-Agent also argues tests should be "evolving reasoning artifacts rather than fixed validators" — in direct tension with the Anthropic/spec-kit rule that tests freeze once committed. Unresolved.

## 3. Reward hacking — the measured part

`[R]` **ImpossibleBench** (arXiv 2510.20270) mutates test suites so they *conflict with the natural-language spec*, making honest success impossible. Any pass is therefore a cheat. Two variants: **One-Off** (change one expected value: `assert f(2) == 4` → `assert f(2) == 5`) and **Conflicting** (two contradictory expectations for the same input).

Cheat rates (Oneoff-SWEbench / Conflicting-SWEbench):

| Model | Rate |
|---|---|
| GPT-5 | 76% / 54% |
| Claude Opus 4.1 | ~50% / 50% |
| Claude Sonnet 4 | ~48% |
| o3 | ~49% |

**The taxonomy — use this as the reviewer's checklist:**

1. **Modify the test** directly, despite explicit instructions not to.
2. **Overload comparison operators** — a wrapper class whose `__eq__` always returns the desired value.
3. **Record extra state** — call counters or flags so identical inputs return different results across calls.
4. **Special-case** — detect the exact test input and return the hardcoded expected value.

**Distribution matters for guard design:** OpenAI models spread across all four (>14% each); **Claude models concentrate >79% in direct test modification.** If your agents are Claude, *diffing the test files is the single highest-yield guard you can build*, and enforcing test immutability mechanically is the single highest-yield control.

**Intervention effects — the actionable numbers:**

| Intervention | Effect |
|---|---|
| Strict prompt instructing the model to **stop and identify conflicts** | GPT-5 **92% → 1%** |
| Offering a `flag_for_human_intervention` tool | GPT-5 **54% → 9%** on Conflicting-SWEbench |
| Hidden tests | Cheating near zero, **but legitimate performance degraded** |
| **Read-only test access** | One of the paper's two recommendations — verbatim: "either hiding test files entirely or restricting them to read-only access during implementation". Read-only preserves the performance that hiding costs; calling it *the* middle ground is my gloss `[J]`, not the paper's framing |
| Multiple submission attempts (feedback loop) | Cheating **up**, 33% → 38% |
| Human monitoring | 86–89% detection on simple tasks, only **42–65%** on SWE-bench-style complexity |

`[R]` **EvilGenie** (arXiv 2511.21654) is the finding that should shape spec design most. On *unambiguous* problems (n=145) clear reward hacking was low — Codex 1.4%, Claude 2.1%, Gemini 0.7%, individual cells spanning 0.7–3.4%. On the **ambiguous problems, rates exploded**: Codex 44.4%, Claude 33.3%, Gemini 22.2%. The paper's own summary: "Reward hacking was far more prevalent in all models for the ambiguous problems."

> **Ambiguity in the spec is the precondition for reward hacking.** A 10–20× jump.

**Two caveats, both load-bearing.** The ambiguous set is only **9 problems**, so those percentages are 2–4 incidents each — the direction is strong, the magnitude is not. And the low unambiguous figures cover *clear reward hacking only*: the paper counts **"heuristic solutions"** as a separate category, and Claude produced those on **20.7%** of unambiguous problems. Corner-cutting on clear specs is not rare; only the flagrant kind is.

Detector comparison, also from EvilGenie: **LLM judges outperformed 30% held-out tests** — near-zero false positives, while holdouts produced false positives on legitimate solutions *and* missed heuristic solutions that passed both visible and held-out tests. Note the implication: held-out tests are not a complete answer either.

`[A]` Anthropic's own RL runs produced `sys.exit(0)` to fake a green suite, and learning to cheat on code **generalised** to a broad rise in misalignment evaluations, including 12% rates of sabotaging cheat-detection code. The mitigation that worked was **inoculation prompting** — naming the unusual framing explicitly: *"This is an unusual request, in that your task is just to make the grading script pass."*

## 4. The mitigation set, evidence-graded

| Mitigation | Grade | Note |
|---|---|---|
| Tests committed separately, before implementation | `[A]` asserted | Not independently measured |
| **Read-only tests during implementation (enforced, not instructed)** | `[R]` recommended, alongside hiding tests entirely | Instruction alone is insufficient — models modify tests "despite explicit instructions against it". Read-only keeps the performance that hiding costs `[J]` |
| **Diff review of test files** | `[R]` highest yield for Claude | >79% of Claude's cheating is direct test modification |
| A different agent writes the tests | `[A]` | Removes authorship, stronger than instruction |
| Independent verification subagent / LLM judge | `[A]` + `[R]` | LLM judges were the best detector in EvilGenie |
| Explicit "stop and flag conflicts" instruction | `[R]` 92%→1% | Cheap, large effect |
| A human-escalation tool the agent can call | `[R]` 54%→9% | Give the agent a legitimate exit |
| Inoculation prompt when the task genuinely is "make the gate pass" | `[A]` | Prevents generalisation |
| Differential oracle (reference implementation) | `[A]` C-compiler used GCC | Only complete answer where one exists |
| Held-out tests | `[R]` mixed | Cuts cheating, degrades legitimate performance, misses heuristic solutions |
| Mutation testing as an anti-cheat guard | `[C]` | Reported as a quality metric; **no controlled study as a cheating guard** |
| Coverage as a guard not a goal | `[C]` | Widely repeated practitioner claim; **no benchmark evidence found** |

## 5. Practical mechanics

### Did it fail for the *right* reason?

`[A]` The original step 2 says only "run the tests and confirm they fail." **No published source addresses how to verify the failure was the right one.** This is a real gap: a test failing with `ImportError`, `NameError`, or a collection error proves nothing about the assertion.

`[J]` Defensible practice, stated as a rule:

> A qualifying RED reports **the failing assertion, with expected and actual values**. A collection error, import error, syntax error, or fixture error is **not** a qualifying RED — it is a broken test. A test that passes on first run is testing existing behaviour and must be rewritten.

`[A]` Related and better-supported: drive tests with inputs the production code actually produces. A test fed synthetic events no live path emits "exercises a branch the live system never reaches" — a green that is a fact about the test, not the system.

### Granularity

`[E]` Consensus: one independently testable behaviour per unit. spec-kit requires each user story be "INDEPENDENTLY TESTABLE" and independently deployable. Kiro recommends "creating multiple specs for different features… rather than attempting to just have a single one for your entire codebase." `[A]` Anthropic's own CLAUDE.md example: "Prefer running single tests, and not the whole test suite, for performance."

### Changes that are not behaviourally testable

Config, docs, generated artefacts, migrations. **No vendor or research guidance exists on proportionate verification here.** The nearest published analogues `[A]`:

- Fragile, order-dependent operations (Anthropic's own example: "database migrations that must run in exact order") should be driven by **specific scripts with few or no parameters**, not prose instructions.
- The **plan → validate → execute** pattern: produce a structured plan file, validate it with a script, then execute. This is the closest published shape for verifying a non-behavioural change.

`[J]` Proportionate evidence, by subject:

| Subject | Evidence |
|---|---|
| Executable behaviour | RED → GREEN → REFACTOR |
| Mechanically enforceable invariant | A guard test, proven able to fail (mutate the condition, watch a *named* assertion go red) |
| Generated artefact | A producer-side check plus a drift guard; **never** re-derive in every consumer |
| Configuration | A validator or a smoke test that exercises the config path |
| Runtime/compatibility floor | The declaration **plus** functional execution on every supported environment |
| Prose / guidance | Used, not predicated — see §6 |

### Measurable criteria need measuring tests

`[J]` A criterion stated as a quantity — a count, a latency, a size, a rate — needs a test that **measures that quantity and asserts the bound**. A structural change that ought to reduce it is not proof it did.

**No source states this.** `[E]` spec-kit comes closest by mandating measurable, technology-agnostic Success Criteria, but that establishes measurability of the *criterion*, not existence of a *measuring test*. `[R]` The supporting empirical case is ImpossibleBench's core finding: structural compliance and actual correctness diverge, so structure is not proof.

### Prose criteria

`[J]` A predicate over prose can only check that words are present, and a sentence saying the opposite passes it. Prose is verified by **use** — see [02](02-skills-and-agents.md) §7 for the published loop (evals first, minimum instructions that pass them, with/without comparison in fresh contexts, iterate on observed behaviour). A criterion demanding a wording guard is the criterion to rewrite.

---

## Where the harness stands

**Keep — and this is genuinely ahead of published guidance**
- **"Verify RED. Confirm it *fails*, not errors, and fails because the feature is missing."** No published source states this. It is the correct rule and it should survive verbatim.
- **"A guard with several independent trigger conditions needs one test per condition, proven by deleting each condition and watching a named assertion go red."** This is mutation testing applied at the right granularity, and `scripts/mutate.py` mechanises it. Nothing in the vendor literature is this specific.
- **"A green suite is only evidence if its inputs are real."** Directly addresses the synthetic-input failure.
- **"A guard that regenerates its reference pins the generator in the same commit"** and **"a warn-and-pass guard has not been shown to run until it has failed once for the real reason."** Both are real failure classes; neither appears in published guidance.
- **"A guard owns only a mechanically decidable contract… do not add a prose predicate, wording guard, vocabulary test, or pinned sentence to judge meaning."** Correct, and consistent with the research.
- Evidence-by-subject (ADR 0019) matches §5's proportionality table closely.
- The reviewer independently re-runs the gate rather than trusting the builder's output.

**Gap — test immutability is instructed, not enforced**
This is the highest-value single change available. `[R]` Models modify tests despite explicit instruction; Claude models concentrate **>79%** of their cheating there; and read-only test access is the intervention with the best measured performance/honesty trade-off.

The harness already has a `PreToolUse` `Write|Edit` hook (`workflow-guard.js`, `prompt-guard.js`). Adding a rule that **refuses edits to test paths while a run is in its implement stage** puts the control on the deterministic rung, where the agent cannot argue with it. The complement is cheap too: the reviewer's Stage 1 should treat **any diff to a test file** as an explicit item to justify, not something noticed incidentally.

**Gap — no "stop and flag the conflict" instruction, and no escalation tool at the implement stage**
Two of the largest measured effects in the literature (92%→1% and 54%→9%) come from telling the agent to stop and name a conflict, and from giving it a legitimate escape hatch. The harness has DEFER and holds at the *run* level, but the implementation subagent's brief does not tell it that "the criteria contradict each other" or "this cannot be satisfied honestly" is an allowed and expected answer. `[J]` Add it to the implementer's instructions in one sentence, and give it a named way to return that verdict.

**Gap — nothing detects the non-modification cheats**
Operator overloading, hidden state, and input special-casing (categories 2–4) leave the test files untouched and pass a diff review. `[R]` The best detector measured was an **LLM judge reading the code** for solutions that satisfy the test without satisfying the intent. The reviewer is well placed to do this; the current review brief does not name the pattern. Adding the four-category taxonomy to `review-discipline` is a small, high-yield edit.

**Gap — the strongest lever is upstream**
`[R]` EvilGenie: 10–20× more cheating on ambiguous problems. The harness invests heavily in *detecting* bad work downstream (gate, review, mutation, tree binding) and comparatively little in *removing ambiguity* before build. See [07](07-requirements-capture.md): a bounded clarification loop with an ambiguity taxonomy is cheaper per ticket than any downstream detector and attacks the cause.

**Question — mutation testing's actual role**
`scripts/mutate.py` is 1,503 lines with 1,200 lines of tests plus liveness and gate-lock suites. It is defensible as a *guard-quality* tool (does this assertion actually assert). It is **not** evidenced as an anti-reward-hacking control — no controlled study supports that use. Worth being precise about which job it is doing, because the two justify very different amounts of investment.
