# 07 — Capturing requirements for agents

**Read when:** designing intake — how a human's intent becomes something an agent can build from without further questions.

---

## 1. Why this is the highest-leverage stage

`[R]` EvilGenie measured clear reward hacking at **0.7–3.4% on unambiguous problems and 22–44% on ambiguous ones** (ambiguous set n=9 — direction strong, magnitude not; and a further 20.7% of Claude's *unambiguous* solutions were "heuristic", a separate category). Ambiguity is not a tidiness issue; it is the measured precondition for an agent producing something that satisfies the letter and misses the point.

`[A]` And the counterweight, which prevents over-correction: **"Vague prompts can be useful when you're exploring and can afford to course-correct… Sometimes a vague prompt is exactly right because you want to see how Claude interprets the problem before constraining it."**

`[J]` Reconciled: **precision should scale with the cost of being wrong**, not be applied uniformly. A one-file fix with a fast revert needs almost none. A change to a contract other things depend on needs all of it.

## 2. The interview

`[A]` Anthropic ships a verbatim prompt template:

```
I want to build [brief description]. Interview me in detail using the AskUserQuestion tool.

Ask about technical implementation, UI/UX, edge cases, concerns, and tradeoffs.
Don't ask obvious questions, dig into the hard parts I might not have considered.

Keep interviewing until we've covered everything, then write a complete spec to SPEC.md.
```

Then: **start a fresh session to execute it.**

`[A]` **Mechanics and limits of `AskUserQuestion`:**
- **1–4 questions per call, 2–4 options each.** Fields: `question`, `header` (max 12 chars), `options` with `label` + `description`, `multiSelect`.
- Used "when it needs more direction on a task with multiple valid approaches."
- **Not available in subagents.** A grounding or design subagent cannot ask the human; it must return open questions to its parent.
- "especially common in plan mode… ideal for interactive workflows where you want Claude to gather requirements before making changes."

## 3. The clarification loop — bounded, ranked, logged

`[E]` spec-kit's `/clarify` is the most concrete published loop. Steal its structure wholesale:

**An 8-category ambiguity taxonomy**, each scanned and marked Clear / Partial / Missing:

1. Functional scope & behaviour
2. Domain & data model
3. Interaction & UX flow
4. Non-functional quality attributes
5. Integration & external dependencies
6. Edge cases & failure handling
7. Constraints & trade-offs
8. Terminology & consistency

**The rules:**

- **Maximum 5 questions total.**
- Each answerable by multiple choice (2–5 options) or in **≤5 words**.
- Ask only questions whose answers "materially impact architecture, data modeling, task decomposition, test design, UX behavior, operational readiness, or compliance validation."
- **Prioritise by (Impact × Uncertainty).**
- **Stop conditions:** all critical ambiguities resolved; the user says "done/good/no more/stop/proceed"; five questions asked; or no valid questions remain.
- **Integrate after *each* answer** — append `- Q: <question> → A: <answer>` under `## Clarifications` → `### Session YYYY-MM-DD`, apply the answer to the affected section, **replace (not duplicate)** conflicting earlier statements, and save the file after each integration.

`[J]` That last rule is the one most often skipped and the one that matters most: integrating after each answer, and *replacing* the superseded statement, is what stops a spec accumulating two contradictory sentences — and `[E]` "agents silently drop one of two conflicting constraints" when they do.

`[E]` Kiro's requirements phase asks for the same shape in prose: who the user is, what they want to accomplish, why they need it, and the success criteria — producing requirements that are "unambiguous and testable," "easy to translate into test cases," and "traceable through implementation."

## 4. Notation: EARS

`[E]` **Easy Approach to Requirements Syntax**, from Alistair Mavin's primary source (non-vendor, predates the AI framing). Generic form:

```
While <optional pre-condition>, when <optional trigger>, the <system name> shall <system response>
```

Ruleset: "Zero or many preconditions; Zero or one trigger; One system name; One or many system responses."

| Pattern | Template | Official example |
|---|---|---|
| **Ubiquitous** | `The <system> shall <response>` | "The mobile phone shall have a mass of less than XX grams." |
| **State-driven** | `While <precondition>, the <system> shall <response>` | "While there is no card in the ATM, the ATM shall display 'insert card to begin'." |
| **Event-driven** | `When <trigger>, the <system> shall <response>` | "When 'mute' is selected, the laptop shall suppress all audio output." |
| **Optional feature** | `Where <feature included>, the <system> shall <response>` | "Where the car has a sunroof, the car shall have a sunroof control panel on the driver door." |
| **Unwanted behaviour** | `If <trigger>, then the <system> shall <response>` | "If an invalid credit card number is entered, then the website shall display 'please re-enter credit card details'." |
| **Complex** | `While <precondition>, when <trigger>, the <system> shall <response>` | "While the aircraft is on ground, when reverse thrust is commanded, the engine control system shall enable reverse thrust." |

`[E]` Kiro uses a **reduced dialect** — uppercase, event-driven only: `WHEN a user submits valid registration data THE SYSTEM SHALL create a new user account`. The other five patterns come from Mavin, not from Kiro; do not assume a tool accepts all six.

`[J]` **What EARS buys an agent pipeline** is not formality for its own sake. It is that each pattern forces a decision the author would otherwise leave implicit: *is there a precondition? is there a trigger? what exactly is the system? what is the observable response?* The **unwanted-behaviour** pattern (`If … then …`) is the most valuable of the six here, because negative and failure-path requirements are the ones most often omitted, and omitted requirements are where an agent invents behaviour.

`[J]` **Where EARS is worth the ceremony:** contracts, invariants, security and failure behaviour, and anything another component depends on. **Where it is not:** a one-line tweak, or UI behaviour better captured as a Given/When/Then scenario. Do not mandate a notation on every criterion of every ticket — the mandate itself becomes the ceremony `[A]` warns about.

`[E]` **Given/When/Then** is spec-kit's acceptance-criteria form, attached to user stories that are prioritised P1/P2/P3 and each **"independently testable"** — developable, testable, deployable and demonstrable on its own.

`[E]` **Contract-shaped requirements**: "Machine-readable schemas using JSON Schema, Zod, or OpenAPI [that] constrain the output space **without prescribing implementation steps**," with acceptance criteria as "concrete test cases with sample inputs and expected outputs serving as the specification's verification oracle."

## 5. Requirement (what) vs design (how)

`[E]` spec-kit is explicit: capture "*what* users need without specifying *how* to build it — avoiding implementation details and technology constraints in the specification phase." Kiro enforces it structurally by putting architecture in a separate `design.md`.

`[E]` **Why conflating them degrades output** — the published failure mechanisms:

1. **Implementation hints** — "specifying data structures or iteration mechanisms eliminates agent flexibility."
2. **Pseudo-code** — "Agents translate pseudo-code directly into production code… carry forward without scrutiny." The agent stops evaluating and starts transcribing. This is the sharpest causal claim in the material.
3. **Prescriptive architecture** — mandating a class hierarchy where pointing at an existing example would do.
4. **Vague quality attributes** — "fast", "secure" instead of a measurable condition.
5. **Restated codebase content** — duplicating instead of referencing.
6. **Conflicting instructions** — "agents silently drop one of two conflicting constraints."

`[A]` Anthropic's version is inverted and softer, and is the better rule: **design by exemplar, not prescription.** The improved prompt is *"look at how existing widgets are implemented on the home page… HotDogWidget.php is a good example. follow the pattern…"* — a pointer to a real, current instance rather than a described abstraction.

## 6. Ambiguity, assumptions, and stop-vs-proceed

**Make the unknowns visible in-line** `[E]`: `System MUST [NEEDS CLARIFICATION: auth method not specified - email/password, SSO, OAuth?]`. A marker in the text is superior to a separate open-questions list, because it sits where the reader will hit it.

**Log assumptions explicitly** `[E]`: an Assumptions section covering scope boundaries and dependencies. `[J]` An assumption is a decision made without authority; recording it converts a silent risk into a reviewable one, and costs one line.

**Unattended runs** `[E]`/`[A]`: the published answer is **halt into a typed "needs input" state with the question recorded** — Linear's `elicitation` / `error` activity types, or the Agent SDK's `defer` hook decision, which exits the process so the session can be resumed later. **Suspend and resume, not guess, and not stall.**

**Pre-encode the ask/proceed decision** `[E]`: a three-tier boundary system — what the agent **must always do**, what requires confirmation (**"Ask First"**), and what is **prohibited**. This is the only published scheme that puts the decision in the spec rather than leaving it to runtime judgment.

`[J]` A practical default for unattended work: **proceed with a stated assumption when the assumption is cheap to reverse and does not change a contract; hold when it does either.** Record the assumption in both cases.

## 7. How much system context, and how to give it

`[A]` **Pointers, not paste.**

- Reference files with `@` "instead of describing where code lives."
- Excluded from instruction files: "anything Claude can figure out by reading code," "detailed API documentation (link to docs instead)," "file-by-file descriptions of the codebase."
- Test for every line: *"Would removing this cause Claude to make mistakes?" If not, cut it.*
- **"Bloated CLAUDE.md files cause Claude to ignore your actual instructions!"**
- Delegate exploration to **subagents** so it does not consume the main context. "The infinite exploration" (unscoped "investigate X") is a named failure pattern.

`[E]` Note the limit of the pointer rule: Copilot's docs say file paths are optional because "Copilot cloud agent has the ability to search your codebase, including semantic code search." Pointers are a hint that saves search, not a requirement.

`[J]` The stronger version — and the one the harness already has in its Grounding section — is that pointers should be **verified at capture time**, with a `path:line` anchor. A stale pointer is worse than none: it is a confident wrong answer that the agent will not question.

## 8. Traceability

`[E]` Kiro's chain: `requirements.md` → `design.md` → `tasks.md`, with requirements "traceable through implementation." *(The commonly-reported task→requirement citation syntax `_Requirements: 1.1, 2.3_` could **not** be verified in Kiro's own docs — treat as unconfirmed.)*

`[A]` **Anthropic's traceability is verification-shaped, not document-shaped**, and this is the more useful framing for a harness. The chain that matters is: criterion → the check that proves it → the output of that check → the tree it was run against. "Have Claude show evidence rather than asserting success."

`[A]` The as-built record in the long-running-agent work is git-shaped: a progress file, a **feature list in JSON with `passes: true/false`**, and git history — with the note that "the model is less likely to inappropriately change or overwrite JSON files compared to Markdown," and the warning that agents "mark a feature as complete without proper testing" unless required to verify end-to-end first.

---

## Where the harness stands

**Keep**
- **Grounding** — verified current reality with `path:line` anchors, produced by a read-only subagent, recorded in the spec — is the strongest single piece of requirements practice in the harness and has no published equivalent. It operationalises "pointers, not paste" *and* solves the stale-pointer problem in one step.
- `/capture`'s **bug vs tweak** distinction is a good, cheap classifier: a bug requires a repro (the objective anchor); a tweak does not, because nothing is broken.
- The **tweak escape hatch** — "carries a real decision, or would spawn more than one change → `/propose` instead" — is a sizing gate at the right moment, before effort is spent.
- "The desired outcome, not the implementation" in `/capture` step 1 is the requirement-vs-design rule, correctly stated.
- Change-spec sections map well onto the published set: Problem, Approach, Grounding, Design (data model / interface / scenarios in GIVEN-WHEN-THEN), Acceptance criteria, Out of scope.

**Gap — no ambiguity taxonomy and no bounded clarification loop**
`/capture` step 1 gathers "by asking, in one turn, if missing" — a single unstructured round. `[R]` Given the 10–20× cheating differential on ambiguity, and `[E]` the availability of a ready-made 8-category taxonomy with a 5-question cap, (Impact × Uncertainty) ranking, explicit stop conditions, and after-each-answer integration, this is the cheapest high-value addition in the whole report. It costs a bounded number of questions at intake and reduces the failure the entire downstream gate exists to catch.

**Gap — no `[NEEDS CLARIFICATION]` marker convention**
Nothing in `templates/change.md` lets an author leave a visible, greppable hole. Without it, an unresolved question either blocks capture entirely or vanishes into prose. Adding the marker plus a rule that `/build` refuses to start on a spec containing one is a two-line change with a hard enforcement point.

**Gap — no Assumptions section**
The template has Out of scope but no place to record a decision made without authority. `[J]` For unattended runs this is the difference between a reviewable risk and a silent one, and it is the natural companion to the hold rules already in the spine.

**Gap — no notation discipline on acceptance criteria**
Criteria are free-form `AC-1: {…}`. The Design section uses GIVEN/WHEN/THEN for scenarios, but criteria themselves have no form. `[J]` Consider requiring EARS's **unwanted-behaviour** pattern (`If <trigger>, then the system shall <response>`) for at least one criterion on any change with a failure path — negative requirements are the ones most often omitted, and omission is where agents invent behaviour.

**Question — is the interview step missing on purpose?**
`[A]` Anthropic's `AskUserQuestion` interview pattern is the published route from a vague human intent to a buildable spec, and `/propose` is the harness's closest equivalent. But `/capture` explicitly files the *already-decided*, and the fast lane files nothing. Nothing in the pipeline handles "I know roughly what I want but not precisely" except escalating to a full proposal. If that gap is real rather than deliberate, a bounded interview inside `/capture` — the same 5-question loop — closes it without adding a command.
