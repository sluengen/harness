# 06 — Spec-driven development for agents, including writing skills

**Read when:** designing spec artefacts and their lifecycle, or turning accumulated process knowledge into a reusable skill.

---

## 1. What SDD claims

`[E]` GitHub spec-kit's framing:

> **"Specifications don't serve code—code serves specifications."**
> "Specifications must be precise, complete, and unambiguous enough to generate working systems."
> The specification is "the primary artifact. Code becomes its expression in a particular language and framework."
> "Multi-step refinement rather than one-shot code generation from prompts."

**Vendor-bias flag:** GitHub, AWS (Kiro) and Cursor all sell agentic tooling; "specifications become executable" is a marketing claim as much as a method. The defensible core — *reduce ambiguity before the agent starts* — is independently supported by `[R]` EvilGenie's 10–20× cheating jump on ambiguous problems (see [05](05-tdd-for-agents.md) §3). That is the argument to make; the executable-specification framing is not needed.

`[A]` **Anthropic's version is much lighter and is the better starting point for a harness:**

> "For larger features, have Claude interview you first… 'Interview me in detail using the AskUserQuestion tool… Keep interviewing until we've covered everything, then write a complete spec to SPEC.md.'"
>
> "The most useful specs are **self-contained**: they name the files and interfaces involved, **state what is out of scope**, and **end with an end-to-end verification step that proves the feature works**. Time spent making the spec precise pays off more than time spent watching the implementation."
>
> "Once the spec is complete, **start a fresh session to execute it**."

That three-clause definition — **interfaces named, out-of-scope stated, end-to-end verification step** — is the most compact answer available to "when is a spec good enough to build from."

## 2. The two reference implementations

### Kiro — three files per feature `[E]`

| File | Contains |
|---|---|
| `requirements.md` | "user stories and acceptance criteria in structured EARS notation" |
| `design.md` | "technical architecture, sequence diagrams, and implementation considerations" |
| `tasks.md` | "a detailed implementation plan with discrete, trackable tasks" |

Claimed benefits: clarity, **testability** ("Each requirement translates directly into test cases"), traceability, completeness. Decision points sit **between** phases, "ensuring each step is properly completed before moving to the next."

Lifecycle guidance: multiple focused specs per project, never one per codebase; specs are "living documents… designed for continuous refinement"; Sync Files regenerates the task list from changed requirements. One hard constraint: you cannot switch workflow mid-spec — "If you need to change approaches, create a new Feature Spec with the desired workflow."

### spec-kit — the phase pipeline `[E]`

**Commands are namespaced `/speckit.*`; older writeups showing bare `/specify` are outdated.**

```
constitution → specify → clarify → plan → checklist → tasks → analyze → implement → converge
```

| Command | Produces |
|---|---|
| `/speckit.constitution` | `constitution.md` — governing principles; keeps dependent templates in sync |
| `/speckit.specify` | `spec.md` from natural language; user-facing behaviour only, **not** tech stack |
| `/speckit.clarify` | Up to **five** targeted questions, answers encoded back into `spec.md`; run **before** plan |
| `/speckit.plan` | `plan.md` — tech stack and architecture; implementation detail lives here, not in the spec |
| `/speckit.checklist` | Custom quality checklists under `checklists/` |
| `/speckit.tasks` | `tasks.md`, dependency-ordered: Setup, Foundational, per-user-story, Polish |
| `/speckit.analyze` | **Read-only** cross-artefact consistency check over spec/plan/tasks — conflicts, gaps, ambiguities. Edits nothing. |
| `/speckit.implement` | Executes tasks in dependency order; **reads checklist state as an implementation gate** |
| `/speckit.converge` | **Append-only** verification of shipped code against spec/plan/tasks; reports convergence or appends gap-closure tasks |

Artefact layout under `specs/[branch-name]/`: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`, `tasks.md`.

**The two distinctive contributions worth stealing:**

1. **`analyze` — a static consistency gate before any code exists.** It catches spec/plan/task drift at the cheapest possible moment, and it is read-only, so it cannot paper over a problem by fixing it.
2. **`converge` — append-only reconciliation of shipped code against the spec**, which either declares convergence or *adds tasks*. Append-only matters: it cannot quietly rewrite the spec to match what was built.

`[E]` spec-kit's constitution ships a **test-first principle** — the direct bridge to [05](05-tdd-for-agents.md):

> "All implementation MUST follow strict Test-Driven Development. No implementation code shall be written before: 1. Unit tests are written 2. Tests are validated and approved by the user 3. Tests are confirmed to FAIL (Red phase)."

Note step 2 — **human approval of the tests** — where the Anthropic loop says only "commit the tests when you're satisfied." `[J]` For an unattended run, "approved by the user" has to become "authored by a different agent than the implementer," which is the writer/reviewer split Anthropic recommends anyway.

spec-kit also enforces three pre-implementation **phase gates**: **Simplicity** ("Using ≤3 projects? No future-proofing?"), **Anti-Abstraction** ("Using framework directly? Single model representation?"), **Integration-First** ("Contracts defined? Contract tests written?").

*(Caveat: the constitution wording above is quoted from the repo's philosophy document; the shipped template may have moved on — raw fetches of both plausible template paths 404'd.)*

## 3. What makes a spec buildable without further human input

Converging across all sources:

| Property | Mechanism |
|---|---|
| **Unambiguity, made visible** | `[E]` inline `[NEEDS CLARIFICATION: auth method not specified - email/password, SSO, OAuth?]` markers, burned down by a bounded clarify loop before planning |
| **Testable acceptance criteria** | `[E]` `Given [initial state], When [action], Then [expected outcome]`; every story independently testable and deployable; P1–P3 priority |
| **Measurable, technology-agnostic success criteria** | `[E]` mandatory section in spec-kit — time limits, concurrency, rates |
| **Explicit non-goals** | `[A]` "state what is out of scope"; `[E]` an Assumptions section for scope boundaries and dependencies |
| **Interfaces and contracts** | `[E]` `contracts/`, `data-model.md`, and the Integration-First gate ("Contracts defined? Contract tests written?") |
| **Worked examples** | `[A]` "Examples are concrete, not abstract" — input/output pairs showing the desired result |
| **An end-to-end verification step** | `[A]` required; `[E]` spec-kit's `quickstart.md` is the same idea |
| **Named evidence per criterion** | `[J]` each criterion states what it protects and how it will be proven, chosen proportionately (see [05](05-tdd-for-agents.md) §5) |

`[A]` And the counterweight, which the spec-heavy vendors do not offer: **"Vague prompts can be useful when you're exploring and can afford to course-correct… Sometimes a vague prompt is exactly right because you want to see how Claude interprets the problem before constraining it."** The constraint is the cost of being wrong, not ambiguity as such. Spec rigour should scale with blast radius, not be uniform.

## 4. Lifecycle: living spec vs as-built record

`[C]` **This is genuinely unsettled in the published state of the art.**

Both major toolkits treat the spec as **living** — Kiro's continuous refinement and Sync Files; spec-kit's append-only `converge`. **Neither separates a forward-looking spec from an as-built record, and neither assigns authorship of the record to a different agent than the builder.**

Published anti-rot mechanisms, all of them structural rather than social:

- `analyze` — read-only cross-artefact consistency, run before implementation
- `converge` — append-only reconciliation of code against spec, run after
- Kiro Sync Files — regenerate downstream artefacts when upstream changes
- spec-kit's `checklists/requirements.md`, whose **evaluated state gates implementation**

`[J]` The **builder-does-not-write-the-record** rule has no published precedent — the closest analogue is `[A]` Anthropic's writer/reviewer session split, which is applied to code review, not to recording delivery. But it follows directly from the measured self-preferential bias in [03](03-quality-principles.md) §5: an agent that reports on its own work "confidently praises" it, and an as-built record is exactly such a report. Treat this as a defensible original rule, and say so rather than implying it is standard practice.

## 5. Promoting spec knowledge into skills

`[A]` This is the clearest official material in the whole report, and it is a complete procedure:

1. "Complete a task with Claude A without a Skill, **noting context you repeatedly provide**"
2. "Identify the reusable pattern"
3. "Ask Claude A to create a Skill: 'Create a Skill that captures this pattern we just used'"
4. "Review for conciseness and ask Claude to remove unnecessary explanations"
5. "Test on similar tasks with Claude B"
6. "Iterate based on Claude B's behavior"

**The promotion trigger is repetition** — context you find yourself supplying again — not anticipation. Compare the routing table in [02](02-skills-and-agents.md) §1: *"You paste the same playbook into chat for the third time."*

**Iteration is driven by observed failure, not imagination** `[A]`: "Return to Claude A with specifics: 'When Claude used this, it forgot to filter test accounts'"; "Each iteration improves the Skill based on **real agent behavior, not assumptions**."

`[A]` And, from the Agent Skills engineering post: "As you work on a task with Claude, ask Claude to capture its successful approaches and common mistakes into reusable context and code within a skill."

**Evaluations come before prose** `[A]`:

> "Create evaluations BEFORE writing extensive documentation. This ensures your Skill solves real problems rather than documenting imagined ones."

The loop: run the task **without** the skill to find the gaps → build three scenarios → establish a baseline → **"Write minimal instructions: Create just enough content to pass evaluations"** → iterate.

`[J]` This is TDD applied to guidance, and it is the resolution of "how do you verify prose." You do not assert predicates over the words. You run the guidance against scenarios, with and without, in fresh contexts, and compare. Full mechanics in [02](02-skills-and-agents.md) §7.

**Calibrating how prescriptive to be** `[A]` — degrees of freedom:

| Freedom | When | Form |
|---|---|---|
| High | Multiple valid approaches; context-dependent decisions (example given: code review) | Prose heuristics, general direction |
| Medium | A preferred pattern exists, variation acceptable | Pseudocode with parameters |
| Low | "Operations are fragile and error-prone; consistency is critical; specific sequence must be followed" (example: database migrations in exact order) | A specific script with few or no parameters |

The metaphor: *"Narrow bridge with cliffs on both sides"* vs *"open field with no hazards."* `[J]` The corollary a process-heavy harness needs to hear: **if a procedure is low-freedom, it should be a script, not prose.** Prose describing an exact sequence is the worst of both — it costs context on every read and it can still be deviated from.

## 6. Anti-patterns

`[A]`
- **"Avoid restating what Claude already knows."** "Claude is already very smart. Only add context Claude doesn't already have." The worked contrast is ~50 tokens of usable instruction versus ~150 explaining what a PDF is.
- **The over-specified instruction file** — "Claude ignores half of it because important rules get lost in the noise. Fix: Ruthlessly prune. If Claude already does something correctly without the instruction, delete it **or convert it to a hook**."
- **Too many options with no default.**
- **Time-sensitive content** — use a collapsed "old patterns" section instead of date-conditional prose.
- **Over-engineering from adversarial review** — "a reviewer prompted to find gaps will usually report some, even when the work is sound."
- **Planning overhead** — "If you could describe the diff in one sentence, skip the plan."

`[E]` From the requirements side: implementation hints and pseudo-code in a spec ("Agents translate pseudo-code directly into production code… carry forward without scrutiny" — the agent stops evaluating and starts transcribing); prescriptive architecture where an example would do; vague quality attributes; restating codebase content instead of referencing it; conflicting instructions, where "agents silently drop one of two conflicting constraints."

`[R]` **Specs an agent can satisfy while missing the point** are ImpossibleBench's special-casing and operator-overloading categories, and EvilGenie's heuristic solutions that pass visible *and* held-out tests. **More tests do not detect these; a judge reading the code does.**

`[J]` **Prose criteria no test can check** — no published source addresses this directly. The nearest published stance is §5's evaluation-driven development: verify guidance by using it, not by predicating over it.

---

## Where the harness stands

**Keep**
- The **change spec is the ticket body** — one artefact, not a parallel `specs/` file per ticket. This avoids the drift that Kiro and spec-kit both need machinery to manage, and it is a better fit for a tracker-driven pipeline.
- **Grounding as a named section** — verified current reality, `path:line` anchored, produced by a read-only subagent — has no published equivalent and directly attacks the hallucinated-context failure. Keep it, and keep the "scaled to size" clause.
- **Scale every section to the size of the work** is the right answer to `[A]`'s warning that spec rigour has diminishing returns.
- Templates for change / proposal / feature / decision / architecture / assessment, and the `/propose` (decide) vs `/capture` (already decided) split, map cleanly onto the published phase model without spec-kit's nine commands.
- ADRs indexed in `architecture-principles.md`, with smaller decisions recorded in the spec they govern, is a sound two-tier decision model.

**Gap — no pre-implementation consistency check**
spec-kit's `analyze` is read-only and runs *before* any code exists: it cross-checks spec against plan against tasks for conflicts, gaps and ambiguity. The harness has no equivalent — its first independent check is the reviewer, after the diff exists. Given `[R]` that ambiguity is the precondition for cheating, moving one cheap consistency check upstream is likely to be the highest-return structural addition available. It costs one read-only pass over the change spec and returns before any implementation is paid for.

**Gap — no post-ship convergence check**
`converge` reconciles shipped code against the spec and *appends* gap-closure tasks. The harness's as-built record captures what shipped but nothing systematically asks "does the shipped system still match its specs" outside `/assess`. Append-only is the property that makes this safe.

**Gap — spec knowledge has never been promoted into skills by the published loop**
The harness has 29 skills, none of which were built by: run without → find the gap → three scenarios → baseline → minimum instructions that pass → iterate on observed behaviour. The `specs/proposals/` directory holds 20+ proposals and `specs/retired/` holds ~5,000 lines of superseded specs — a rich source of "context repeatedly provided" that has not been mined this way. If the redesign adopts one new practice from this report, this is the highest-leverage candidate, because it changes how *every* future guidance change is justified.

**Cost — retired specs are 40% of `specs/`**
`specs/retired/` is roughly 5,000 of 12,970 lines. They are not auto-loaded, so the cost is not context — it is search noise and the risk of an agent grounding itself in a superseded document. `[A]` The published pattern for superseded material is a collapsed "old patterns" section, not a parallel live directory. Consider moving them out of the working tree entirely; git history preserves them.

**Cost — check the low-freedom prose**
Per §5, a low-freedom procedure should be a script. `commands/build.md`'s four-step post-verdict re-bind path is exact, order-dependent, and mechanically checkable — it specifies precise git invocations, required exit conditions, and parent-set comparisons. That is a script written as prose. Moving it into `scripts/` would make it deterministic, testable, and free of context cost, and would leave the command file explaining *when* it applies rather than *how* it runs.
