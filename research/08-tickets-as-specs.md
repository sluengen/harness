# 08 — Writing tickets that serve as specs for agents

**Read when:** designing the ticket schema, its labels and states, sizing rules, or the queue semantics an unattended loop reads.

---

## 1. The one measured claim about ticket quality

`[E]` Atlassian reports that AI-native ticket authoring produced **83% agent-ready tickets (score ≥4) versus 6%** traditionally; acceptance-criteria clarity **4.32/5 vs 2.20/5**; mean quality **4.47 vs 2.72**; p < 0.001. Agent-ready tickets "read like executable specs (explicit acceptance criteria, areas in scope, out-of-scope notes, dependency links)" where traditional tickets had "a one-line summary and a link." "Tight scope keeps agents on the rails," preventing agents from "going rogue or inventing requirements."

**Heavy vendor bias:** Atlassian sells the tooling, the rubric is their own, it is self-graded, and the comparison is their new process against their old one, not a controlled trial. The *direction* is consistent with `[R]` EvilGenie's ambiguity finding; the magnitude is not evidence.

## 2. GitHub's advice — the key non-Anthropic primary source

`[E]` An ideal task for a coding agent contains, verbatim:

> - "A clear description of the problem to be solved or the work required."
> - "Complete acceptance criteria on what a good solution looks like (for example, should there be unit tests?)."
> - "Directions about which files need to be changed."

**Good candidates:** bug fixes, UI feature alterations, test coverage improvements, documentation updates, accessibility enhancements, technical debt reduction.

**Do it yourself:** "Broad-scoped, context-rich refactoring problems requiring cross-repository knowledge"; "Complex issues requiring understanding dependencies and legacy code"; tasks requiring "deep domain knowledge" or "substantial business logic"; "Production-critical issues"; "Tasks involving security, personally identifiable information"; and **"Tasks lacking clear definition: tasks with ambiguous requirements, open-ended tasks."**

`[E]` **The WRAP framework** — **W**rite effective issues, **R**efine your instructions, **A**tomic tasks, **P**air with the agent. Its three rules, verbatim:

> "Write an issue as though it's for someone brand new to the codebase."
> "Craft a descriptive title that explains where the work is being done."
> "Add examples of what you want."

Its worked contrast is the best single illustration in the corpus:

> ❌ "Update the entire repository to use async/await"
> ✅ "Update the authentication middleware to use the newer async/await pattern, as shown in the example below. Add unit tests for verification of this work, ensuring edge cases are considered."

`[E]` GitHub's issue-content list: "Relevant background info: Why this task matters, what it touches, and any important history or context"; "Expected outcome: What 'done' looks like"; "Technical details: File names, functions, or components involved"; "Formatting or linting rules" — called out as "especially important if you use custom scripts or auto-generated files." On scope: "Copilot works best with well-scoped tasks, but it can handle larger ones. It just might take a little bit longer."

## 3. A concrete field list

`[P]` The most complete published template, in order:

1. **Title** — "Verb + object + outcome"
2. **Context** — user/customer problem; current behaviour; desired behaviour
3. **Scope** — in scope; out of scope; likely files/components/endpoints; **protected areas** (auth, billing, data migration, permissions)
4. **Acceptance criteria** — checkbox list
5. **Test expectations** — test runner/pattern; required cases: happy path, empty state, error state, permission/role case, regression case
6. **Implementation constraints** — match existing conventions; prefer existing components; keep the diff focused; do not change public API behaviour unless specified
7. **PR review checklist**

Labels: `agent-ready`, `tests-required`, `human-review`. Guidance: "Write failing tests before implementation"; **"Review the PR against the ticket, not only against the diff"**; and the balance statement — "The ticket does not over-specify implementation, but it gives the coding agent enough behavior, tests, and constraints to stay inside the intended change." Practitioner-grade, not authoritative.

`[E]` **OpenAI's compact four-part shape** is the version to reach for when the full list is too much:

> **Goal** — "What are you trying to change or build?"
> **Context** — "Which files, folders, docs, examples, or errors matter?"
> **Constraints** — "What standards, architecture, safety requirements, or conventions should Codex follow?"
> **Done when** — "What should be true before the task is complete"

Plus: "Keep one thread per coherent unit of work," and "If the task is complex, ambiguous, or hard to describe well, ask Codex to plan before it starts coding."

`[J]` **Protected areas** is the field most worth stealing that the harness lacks. It is not the same as out-of-scope: out-of-scope says "don't do this work," protected areas say "if your change reaches here, stop and escalate." It gives the agent a named tripwire rather than relying on it to infer blast radius.

## 4. Sizing

`[E]` Multi-vendor consensus, no dissent found:

- OpenAI: "Codex produces higher-quality outputs when it can verify its work" and "handles complex work better when you break it into smaller, focused steps. Smaller tasks are easier for Codex to test and for you to review."
- GitHub: "small, atomic, and well-defined tasks"; break larger problems into multiple independent issues.
- `[A]` Anthropic, on the other side of the ledger: **"If you could describe the diff in one sentence, skip the plan"** — planning earns its cost when the approach is uncertain, the change is multi-file, or the code is unfamiliar.

`[E]` **METR's time-horizon result** is the best published justification for "one ticket = one bounded unit," with a large caveat. The 50%-success time horizon is "the length (for humans) of tasks that the model can successfully complete with x% probability": near-perfect on sub-4-minute human tasks, **under 10% success beyond ~4 hours**, doubling roughly every 7 months. **This is March 2025 data with a Claude 3.7-generation model** — 18 months stale, and the absolute numbers are certainly obsolete. The transferable finding is the *shape*: a sharp reliability cliff as human-task-length grows, and occasional multi-hour success is not the same as reliable multi-hour success.

`[J]` **Size a ticket by the reliability cliff, not by effort.** The question is not "how long would this take" but "how many independent decisions does this require before anything can be checked." A ticket with one checkable outcome and five decisions is riskier than one with three checkable outcomes and three decisions.

## 5. Metadata and queue semantics

`[E]` **Linear** publishes the only agent-state semantics found:

- **Self-delegation:** "If your agent is working on implementation and no `Issue.delegate` is currently set, it should set itself as the delegate."
- **Triage exception:** when automation delegates to an agent, "keep it in triage state and leave assignment up to a human actor to action." *(Note these are two different rules and are easily conflated.)*
- **Status:** "move the issue to the first status in `started` when your agent begins work."
- **Acknowledgement SLA:** acknowledge the `created` webhook within **10 seconds**.
- **Terminal states:** a `response` activity on completion; **`elicitation` or `error`** when user action is needed.

`[C]` **Are comments the audit trail?** Genuine disagreement.

- **Linear says no:** "Comments may not be reliable to read from, as they are editable and may have changed since your agent's last run." Reconstruct from immutable **Agent Activities** instead.
- **GitHub says yes:** iterate by mentioning `@copilot` in PR comments — with one useful efficiency rule, **"Start a review" to batch comments into a single work session** rather than firing one agent run per comment. Only users with write access can trigger it.

`[J]` Resolve by dependency: anything a run *depends on* should come from an immutable source; comments are fine as human-readable narration and as the place a human addresses the agent.

## 6. Anti-patterns

Consolidated from the sources above:

- Vague titles that do not say **where** the work happens `[E]`
- Missing or non-executable acceptance criteria `[E]` — the widest measured quality gap
- Bundled unrelated work ("Update the entire repository to…") `[E]`
- Tickets assuming tribal knowledge — write "as though it's for someone brand new to the codebase" `[E]`
- Implementation prescription and **pseudo-code** — "Agents translate pseudo-code directly into production code… carry forward without scrutiny" `[E]`
- Vague quality adjectives instead of measurable conditions `[E]`
- Conflicting constraints across sections — "agents silently drop one of two conflicting constraints" `[E]`
- **Unverifiable completion language.** `[E]` "should pass," "looks correct," "follows best practices" are named as prohibited, to be replaced by "evidence-based completion phrases requiring specific test output and file paths." This aligns exactly with `[A]` "show evidence rather than asserting success."

## 7. Structured schemas — the weakest area

**Verifiable and real:** path-scoped instruction files (`.github/instructions/**/*.instructions.md` with glob frontmatter), skill frontmatter, `AGENTS.md`/`CLAUDE.md` conventions, and JSON Schema / Zod / OpenAPI contracts embedded in specs.

**Weakly evidenced:** **no authoritative, widely-adopted YAML/JSON schema for issues themselves** was found. What exists is proprietary custom fields (Jira, Linear) plus practitioner label conventions (`agent-ready`, `tests-required`, `human-review`). MCP-driven tracker integration is real — `[A]` Anthropic documents `claude mcp add` for issue trackers and says "you can ask Claude to implement features from issue trackers" — but no schema standard for agent-consumable tickets exists.

`[J]` So a harness defining its own ticket schema is not reinventing a wheel; there is no wheel. The design freedom is real, and the constraint is portability across trackers, not conformance to a standard.

---

## Where the harness stands

**Keep**
- **The ticket body *is* the change spec** — no parallel artefact, so no drift between them. Better than the Kiro/spec-kit file model for a tracker-driven pipeline.
- **`assurance:<level>` (trivial · simple · complex), exactly one per ticket, chosen at filing**, is the best-designed piece of ticket metadata in the audit. It is the metadata-that-changes-agent-behaviour pattern done properly: the label selects the review shape mechanically, defaults conservatively (`simple`) when missing or conflicting, can be **upgraded but never downgraded**, and `trivial` requires an explicit repo opt-in. Nothing published is this well specified.
- **Hold = comment + label + assignment, always all three**, with `input` vs `operator` as the reason class, is the concrete form of Linear's typed `elicitation` state — and requiring all three prevents the half-held ticket that an unattended loop would re-pick.
- **Filing discipline** — search the open queue first and extend an unstarted ticket rather than create a twin; explicit Todo placement verified by re-reading the ticket, not by exit status — addresses two real failure modes that no vendor documents.
- **Todo/Backlog semantics** — Backlog for work whose *existence* is uncertain, blocked-but-confirmed staying in Todo held — is a genuinely useful distinction.
- Iron law 6 (external text is data, not instruction) is the correct posture for ticket bodies, and stronger than anything published.

**Gap — no protected-areas field**
The template has Out of scope but no tripwire list. `[J]` For an unattended loop, "if the change reaches auth, billing, migrations or permissions, stop and hold" is a better control than hoping the agent infers blast radius, and it maps directly onto the existing `input`/`operator` hold machinery.

**Gap — no verification instructions on the ticket**
`[E]` GitHub calls out "formatting or linting rules… especially important if you use custom scripts or auto-generated files," and the practitioner template has a whole **Test expectations** section (runner, pattern, and the required cases: happy path, empty, error, permission, regression). The harness's change spec names evidence *per criterion*, which is more principled — but it does not name the required *case classes*, so the empty/error/permission cases are left to the implementer to remember. A short checklist costs little.

**Gap — title convention unstated**
`[E]` Both GitHub ("a descriptive title that explains where the work is being done") and the practitioner template ("verb + object + outcome") specify one. The harness does not, and titles are what an unattended `work-discovery` pass ranks on.

**Gap — no `[NEEDS CLARIFICATION]` marker and no Assumptions section**
Covered in [07](07-requirements-capture.md), repeated here because the ticket body is where they would live.

**Check — comment reliance**
`/build` carries findings forward through ticket comments. Per Linear's warning, comments are mutable. Where the tracker offers an immutable stream, prefer it for anything a run depends on; keep comments for the human-facing narrative.

**Check — the sizing rule is implicit**
`/capture`'s escape hatch ("carries a real decision, or would spawn more than one change → `/propose`") is a good sizing gate, but it is stated only for tweaks. `[E]` GitHub's do-it-yourself list (cross-repo refactors, deep domain knowledge, production-critical, security/PII, ambiguous) is a ready-made complement, and it maps onto the existing hold reasons rather than needing new machinery.
