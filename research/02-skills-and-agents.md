# 02 — Skills and agents: structure, content, length, and when to use which

**Read when:** authoring a skill, a subagent, or a command — or deciding which of them a piece of guidance should become.

---

## 1. The decision, first

`[A]` Anthropic publishes a trigger-based routing table. Use it before writing anything:

| Trigger | Build |
|---|---|
| Claude gets a convention or command wrong **twice** | CLAUDE.md line |
| You keep typing the same prompt to start a task | User-invocable skill |
| You paste the same playbook into chat **for the third time** | Skill |
| You keep copying data from a system Claude cannot see | MCP server (or a CLI tool — cheaper) |
| A side task floods your context with output you will not re-read | Subagent |
| You want something to happen **every time**, without asking | Hook |
| A second repo needs the same setup | Plugin |

The distinctions, quoted `[A]`:

- **CLAUDE.md vs skill** — "CLAUDE.md is loaded every session, so only include things that apply broadly. For domain knowledge or workflows that are only relevant sometimes, use skills instead."
- **Skill vs subagent** — skills are "reusable content you can load into any context" and **add to your main window**; subagents are "isolated workers" with "a separate window with its own input and output tokens." They compose: a subagent can preload skills via `skills:`; a skill can fork context with `context: fork`.
- **Skill vs slash command** — **this distinction no longer exists.** "Custom commands have been merged into skills." `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` both produce `/deploy`. A slash command is now just a skill with `disable-model-invocation: true`.
- **MCP vs skill** — "MCP connects to your database, a skill documents your schema and query patterns."
- **Hook vs skill** — "An instruction like 'never edit `.env`' in CLAUDE.md or a skill is a request, not a guarantee. A `PreToolUse` hook that blocks the edit is enforcement."

`[J]` Collapsed into an ordered test — stop at the first that holds:

1. Must it happen every time, with no reasoning? → **hook**
2. Does it need data or actions from outside the repo? → **CLI tool first, MCP second**
3. Must it be known on *every* task, and is it short? → **CLAUDE.md** (or `.claude/rules/` if path-local)
4. Is it knowledge or a procedure needed *sometimes*? → **skill** (add `disable-model-invocation: true` if it has side effects — this also removes it from the listing budget)
5. Will it read many files, produce output nobody re-reads, or need different tools or a different model? → **subagent**
6. Does it fan out past a handful of agents, or need cross-checking? → **workflow** — but see the coding warning in §7.

---

## 2. SKILL.md — the format

`[A]` The Agent Skills format is now an open standard at agentskills.io. **Six frontmatter fields; only `name` and `description` are required.**

| Field | Req | Constraint |
|---|---|---|
| `name` | yes | Max 64 chars. Lowercase, numbers, hyphens. No leading/trailing/consecutive hyphens. **Must match the parent directory name.** No XML tags. Cannot contain "anthropic" or "claude". |
| `description` | yes | Max 1024 chars, non-empty. What it does **and when to use it**. No XML tags. |
| `license` | no | Short name or bundled-file reference |
| `compatibility` | no | Max 500 chars. "Most skills do not need the `compatibility` field." |
| `metadata` | no | String → string map |
| `allowed-tools` | no | Space-separated, e.g. `Bash(git:*) Bash(jq:*) Read`. Experimental. |

Directory layout (convention, not enforced):

```
skill-name/
├── SKILL.md      # required
├── scripts/      # executable code — output enters context, source does not
├── references/   # loaded on demand
└── assets/       # templates, schemas, images
```

**Portability trap** `[A]`: Claude Code adds ~19 extra frontmatter fields (`when_to_use`, `argument-hint`, `disable-model-invocation`, `model`, `effort`, `context: fork`, `agent`, `background`, `hooks`, `paths`, `shell`, …). claude.ai uploads, the Skills API and `package_skill.py` accept **only the six standard fields** and hard-error on the rest. If a skill must be portable, keep the frontmatter to six fields.

## 3. Progressive disclosure and the real budgets

`[A]` Three levels:

| Level | Loaded | Budget |
|---|---|---|
| Metadata (`name` + `description`) | At startup, for **every** skill | ~100 tokens each |
| SKILL.md body | On activation | **< 5,000 tokens recommended; under 500 lines** |
| `references/`, `scripts/`, `assets/` | Only when read | No cost until accessed |

"Files don't consume context until accessed… There's no context penalty for bundled content that isn't used."

**Two budgets that bite in Claude Code and are easy to miss:**

1. **Skill listing budget = 1% of the model's context window.** On overflow, "Claude Code drops descriptions starting with the skills you invoke least" — and shortening a description "can strip the keywords Claude needs to match your request." This is the real cap on how many skills a repo can carry: not a count, but the total size of all descriptions.
2. **Invoked skill content persists.** An invoked SKILL.md "enters the conversation as a single message and stays there across later turns" — a recurring cost, not one-time. After auto-compaction, the most recent invocation of each skill is re-attached, **first 5,000 tokens each, combined budget 25,000 tokens**, filled most-recently-invoked first. Older skills are dropped entirely.

`[J]` Consequence for a harness: a workflow that loads eight skills in one build run will lose the earliest-loaded ones at the first compaction, silently. Design so the skills a stage depends on are loaded *at* that stage, not all at the start.

**Calibration** — Anthropic's own shipped skills, measured: `docx` 91 lines / 6.9 KB; `mcp-builder` 236 lines / 9.1 KB; `pdf` 314 lines / 8.1 KB. The repo's starter template is 5 lines.

## 4. The description does all the triggering

`[A]` "The description carries the entire burden of triggering." Rules:

- Cover **both** what it does and when to use it.
- **Include the words users would naturally say**, including where they never name the domain: "even if they don't explicitly mention 'CSV' or 'analysis.'"
- **"Err on the side of being pushy."**
- Describe user intent, not implementation.
- Note the ceiling: "agents typically only consult skills for tasks that require knowledge or capabilities beyond what they can handle alone. A simple, one-step request… may not trigger a PDF skill even if the description matches perfectly."

**Worked example — Anthropic's own `docx` description** (≈1,000 chars) enumerates file extensions, quoted user phrasings ("'Word doc'"), deliverable nouns ("report", "memo", "letter"), *and* negative scope: `Do NOT use for PDFs, spreadsheets, Google Docs, or general coding tasks unrelated to document generation.`

Bad: `Helps with PDFs.` / `Processes data.` / `Does stuff with files.`

**`[C]` Contested: third person vs imperative.** Two Anthropic-controlled sources disagree. platform.claude.com: "Always write in third person… inconsistent point-of-view can cause discovery problems." agentskills.io: "Use imperative phrasing… 'Use this skill when…' rather than 'This skill does…'." Anthropic's shipped skills do both. **Resolution `[J]`: third-person capability statement + an explicit "Use when…" trigger clause + a "Do NOT use for…" negative clause.** Both sources forbid first/second person about the assistant.

## 5. Body vs reference vs script

`[A]`

**Body** — instructions needed on *every* run of the skill. Under 500 lines.

**`references/`** — two hard rules:
- **One level deep from SKILL.md.** "Claude may partially read files when they're referenced from other referenced files… `head -100`… resulting in incomplete information." `SKILL.md → advanced.md → details.md` is named as an anti-pattern.
- **Files over 100 lines need a table of contents**, so a partial read still reveals scope.
- Say *when* to load each: `"Read references/api-errors.md if the API returns a non-200 status code"` beats "see references/".

**`scripts/`** — ship code when operations are fragile, must be consistent, or repeat. Stated benefits: "More reliable than generated code / Save tokens / Save time / Ensure consistency." Rule: **"Solve, don't defer"** — scripts handle their own error conditions. Make intent unambiguous: *"Run `analyze_form.py` to extract fields"* (execute) vs *"See `analyze_form.py` for the extraction algorithm"* (read). Promotion signal: "If every test run independently wrote a similar helper script… bundle the script."

## 6. Writing style

`[A]`

- **"Claude is already very smart. Only add context Claude doesn't already have."** Per-line test: *"Would the agent get this wrong without this instruction?" If no, cut it.*
- **Degrees of freedom — match specificity to fragility.** The official metaphor: *"Narrow bridge with cliffs on both sides"* = low freedom, exact scripts with few parameters (example: database migrations in exact order). *"Open field with no hazards"* = high freedom, general direction (example: code review).
- **Provide defaults, not menus.** Anti-pattern: "You can use pypdf, or pdfplumber, or PyMuPDF, or pdf2image, or…"
- **Procedures over declarations** — teach how to approach a class of problems, not the answer to one instance.
- **Explain why for the flexible parts:** "Reasoning-based instructions ('Do X because Y tends to cause Z') work better than rigid directives ('ALWAYS do X, NEVER do Y')."
- **No time-sensitive content.** Never "if you're doing this before August 2025…"; use a collapsed "old patterns" section.
- Other named anti-patterns: Windows paths; assuming tools are installed; "voodoo constants" without justification; **over-comprehensive skills** ("the agent struggles to extract what's relevant and may pursue unproductive paths"); skills scoped too narrowly (multiple loads, conflicting instructions) or too broadly (hard to activate precisely); and the headline pitfall — **generating a skill from an LLM's general knowledge rather than real expertise.**

## 7. Evaluating a skill — the missing discipline

`[A]` **"Create evaluations BEFORE writing extensive documentation. This ensures your Skill solves real problems rather than documenting imagined ones."** (platform.claude.com → Agent Skills → best practices.) Two things are measured **separately**, and they live in different documents.

**Does it trigger?** (agentskills.io → skill-creation → optimizing-descriptions)
- ~20 labelled queries: **8–10 should-trigger, 8–10 should-not**, the negatives being *near-misses* that share keywords.
- Run each **3 times**; compute a trigger rate; threshold **0.5**.

**Is the output better?** (agentskills.io → skill-creation → evaluating-skills)
- `evals/evals.json` with `prompt` / `expected_output` / `files` / `assertions`.
- **Start with 2–3 cases.** Run each **with the skill and without** (or against a snapshot of the previous version), in a **fresh context per run**.
- Grade to `grading.json` with evidence; aggregate `benchmark.json` with pass rate, time, tokens, and a `delta`. Blind A/B for holistic quality. Iterate in `iteration-N/` directories.
- Test across Haiku / Sonnet / Opus.
- Tooling: `/plugin install skill-creator@claude-plugins-official` automates evals, grading, benchmarking, version A/B, and description tuning.

**Diagnostic loop:** read execution *traces*, not just outputs. Wasted steps usually mean vague instructions, non-applicable instructions, or too many options with no default. **"If pass rates plateau despite adding more rules, the skill may be over-constrained — try removing instructions."**

`[J]` This is the published answer to "how do you verify a document whose content is prose." You do not write predicates over the words. You run the guidance against scenarios, with and without, in fresh contexts, and compare outcomes. It is TDD for guidance, and it is the capability most conspicuously absent from process-heavy harnesses.

## 8. Skill discovery and precedence

`[A]` Locations: enterprise (managed settings) · personal `~/.claude/skills/` · project `.claude/skills/` · plugin `<plugin>/skills/`.

**Precedence: enterprise > personal > project.** Note the inversion versus most config systems — personal beats project. Plugin skills are namespaced `plugin:skill` and cannot conflict. Skills beat same-named `.claude/commands/` files. Nested `.claude/skills/` below cwd load lazily and appear as `apps/web:deploy`.

**Cowork, cloud and routine sessions do not read `~/.claude/skills/`** — a skill needed by an unattended run must be committed to the repo or enabled via claude.ai.

There is **no published cap on skill count**. The binding constraint is the 1% listing budget.

## 9. Subagents

`[A]` **Format** — markdown with YAML frontmatter; body is the system prompt. Required: `name` (lowercase-hyphen, no `:`), `description`. Optional: `tools` (allowlist; inherits all if omitted), `disallowedTools`, `model` (`sonnet|opus|haiku|inherit|`full id), `permissionMode`, `maxTurns`, `skills` (preloaded), `mcpServers`, `hooks`, `memory`, `background`, `effort` (`low|medium|high|xhigh|max`), `isolation: worktree`, `color`, `initialPrompt`.

**Precedence:** managed settings > `--agents` flag > `.claude/agents/` > `~/.claude/agents/` > plugin `agents/`. Scanned recursively.

**Hard limits:** combined subagent descriptions **15,000 tokens**; nesting depth **3**; **20** concurrent.

**What a subagent inherits:** its own system prompt (not Claude Code's), the delegation message, CLAUDE.md + git status, preloaded skills.
**What it never sees:** the main conversation, the output style, main auto-memory, previously invoked skills. Context isolation is total — which is the point, and also the cost.

**Use a subagent when:** output is verbose and will not be referenced again; you want tool restrictions; the work is self-contained and returns a summary.
**Use the main conversation when:** the task needs iterative back-and-forth; several phases share significant context; changes are quick and targeted; latency matters.

## 10. Multi-agent economics and the coding warning

`[A]` From *Building a multi-agent research system*:

- **Cost:** "agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats." Only high-value tasks justify it.
- **Payoff:** an Opus lead with Sonnet subagents "outperformed single-agent Claude Opus 4 by 90.2%" on their research eval. Fits "heavy parallelization, information that exceeds single context windows, and interfacing with numerous complex tools."
- **The warning, verbatim:** "most coding tasks involve fewer truly parallelizable tasks than research, and LLM agents are not yet great at coordinating and delegating to other agents in real time."
- **Subagent prompt design:** "Each subagent needs an objective, an output format, guidance on the tools and sources to use, and clear task boundaries."
- **Effort budgets:** "Simple fact-finding requires just 1 agent with 3-10 tool calls, direct comparisons might need 2-4 subagents with 10-15 calls each, and complex research might use more than 10 subagents."
- Improving tool descriptions alone produced "a 40% decrease in task completion time."

`[C]` **Dated:** the post's strict no-sibling-communication model is contradicted by current Claude Code docs, where named subagents "can also message each other" via a `SendMessage` tool. Verify against your version. The 15× and 90.2% figures are from Claude 4-generation models on a research domain and should be treated as directional.

`[J]` For a build pipeline the defensible use of subagents is **context isolation for independence** — a fresh reviewer, a fresh grounding researcher — not parallelism. The parallelism case for tightly-coupled implementation work is explicitly weak.

## 11. Third-party skills, and the delete-first rule

**The prior question is not who maintains a skill — it is whether it should exist.** `[A]` The test is the same one that governs instruction files: *"Would the agent get this wrong without this instruction?" If no, cut it.* And: "Claude is already very smart. Only add context Claude doesn't already have."

A skill that restates common professional knowledge is a cost whether you wrote it or someone else did. Outsourcing it moves the maintenance but keeps the listing-budget cost, keeps the trigger competition, and adds a dependency. **Delete first, then decide who maintains what survives.**

### The product/commodity test

For each skill, ask what it encodes:

| It encodes | Then |
|---|---|
| Your lifecycle — verdict vocabulary, evidence matrix, assurance levels, the artefacts your commands pass between stages | **It is the product.** Never outsource. No external skill can know what your verdicts mean. |
| Provider recipes — tracker APIs, service integrations, format mechanics | **Commodity, and it rots.** Prefer an official plugin or MCP server. Zero differentiation, ongoing maintenance, breaks when the upstream API moves. |
| General craft the model already has | **Delete.** Not replace. |
| General craft the model gets wrong without help, and nobody official covers | **Keep and maintain.** This is the only category where writing your own is clearly right. |

### The official marketplace, as of September 2026

`[A]` Identifier `claude-plugins-official`, added automatically on first startup (`/plugin marketplace add anthropics/claude-plugins-official` if it fails). Repo: [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official). It mixes Anthropic-authored plugins with third-party listings under `external_plugins/`. A separate `claude-plugins-community` marketplace must be added manually. Inclusion is "at Anthropic's discretion"; **no SLA or quality guarantee is published**.

Coverage relevant to a development harness *(enumerated by a research pass, not exhaustively re-verified — check before depending on any single entry)*:

| Category | Official coverage |
|---|---|
| Code review | `code-review`, `pr-review-toolkit`, `code-simplifier` |
| Git / PR workflow | `commit-commands`, `github`, `gitlab` |
| Issue tracking | `github`, `linear`, `atlassian` |
| Security review | `claude-security`, `security-guidance` |
| Frontend / UX | `frontend-design`, `figma` |
| Debugging | Indirect only (`feature-dev`) |
| **Testing / TDD** | **None** |
| **Spec / PRD authoring** | **None** |
| **Prose and writing quality** | **None** |

Note the shape of that list: the marketplace covers *integration* and *generic review* well, and covers *process discipline* not at all. A harness whose value is process discipline will find little to adopt and much to compete with.

### Four costs of depending on marketplace plugins

1. **Listing budget.** `[A]` Installing a plugin brings **all** its skill descriptions into the 1% listing allocation, and on overflow "Claude Code drops descriptions starting with the skills you invoke least" — potentially yours. Adding external skills can make your own less likely to fire.
2. **Semantic collision.** An external `code-review` skill carries its own definition of review and competes for the same trigger as yours. Two skills claiming the same job, one of which does not know your verdict vocabulary, is worse than one skill you maintain. This is the sharpest risk and the least visible.
3. **Auto-update.** Official plugins auto-update by default. For a harness whose premise is versioned, drift-guarded, tested guidance, third-party guidance changing silently mid-lifecycle is a contradiction. `[A]` Pin with semver constraints in `plugin.json` `dependencies`; cross-marketplace dependencies need `allowCrossMarketplaceDependenciesOn` in the marketplace manifest.
4. **Headless and SDK.** `[A]` The Agent SDK accepts local plugins only (`{ type: "local", path: ... }`); marketplace plugins must be downloaded first. Any unattended container path has to handle that.

`[A]` Individual skills from an installed plugin can be hidden with `skillOverrides` in settings, without editing the plugin — the escape hatch when a dependency brings more than you want.

### Decision rule

1. Delete anything failing the "would the agent get this wrong without it" test.
2. Swap commodity integration skills for official plugins or MCP servers — pinned, never auto-updating.
3. Keep and maintain only what encodes the lifecycle, plus genuine craft gaps nobody covers.
4. Where an external plugin overlaps a skill you keep, hide the overlap with `skillOverrides` rather than letting two skills compete for one trigger.

### The model and effort fields — verified, and unused by most harnesses

`[A]` **Skills support `model:` and `effort:` frontmatter in Claude Code** (verified directly against the frontmatter reference; a secondary source claiming these are agent-only is wrong):

- `model` — "Model to use when this skill is active… Accepts the same values as `/model`, or `inherit`." With `context: fork`, it sets the **forked subagent's** model instead.
- `effort` — `low | medium | high | xhigh | max`, overriding the session level; inherits by default.
- `${CLAUDE_EFFORT}` is substitutable inside a skill body, so guidance can adapt to the active level.

`[C]` The belief that official skills systematically pin a cheaper model is **not supported** — the official `code-simplifier` agent pins `model: opus`. There is no published guidance mandating a cheap default for plugin skills; the cost docs suggest Sonnet for agent-team workers only.

`[J]` The transferable point is the mechanism, not the marketplace. **An assurance or tiering scheme expressed as prose instructions is a scheme the agent can fail to honour; expressed as `model:`/`effort:` frontmatter it is applied by the runtime.** That is the same "push enforcement to the lowest rung" move as the test-immutability hook in [05](05-tdd-for-agents.md), applied to cost rather than correctness.

---

## Where the harness stands

**Keep**
- Agent definitions are correctly thin (31–65 lines) and delegate to skills rather than restating them. `agents/reviewer.md` uses `isolation: worktree` and a tool allowlist — both right.
- Skill descriptions mostly follow the "Use when…" pattern with a scoping clause. `engineering`'s description names both the reader and the moment.
- Reviewer-in-fresh-context is exactly Anthropic's stated pattern.

**Cost — nine `command-*` skills duplicate their command files**
`skills/command-build/SKILL.md` (154 lines), `command-promote` (112), `command-init` (75), `command-assess` (69), `command-propose` (49), `command-capture` (46), `command-digest` (46), `command-review` (40), `command-routine` (30) — ~620 lines generated by `scripts/generate_codex_artifacts.py`.

They are **not** pointers, despite their descriptions saying "read and follow the command file completely before acting." Each body states *"The following is the complete command contract, embedded so this skill remains portable when the plugin is installed into a host cache"* and then reproduces the command file verbatim. `command-build` is 154 lines because `commands/build.md` is 143. This is the same generated-full-duplicate pattern as `AGENTS.md` (see [01](01-instruction-files.md)), and the description/body mismatch — telling the agent to go read a file whose contents are already inline — is an inconsistency in the generated artefact.

**Why the Claude Code merge is relevant, precisely.** It does **not** dissolve the need for these: they exist for **Codex**, a different host, and `[A]` "Custom commands have been merged into skills" is a statement about Claude Code's slash-command resolution only. What the merge enables is narrower and better: since `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` "both create `/deploy` and work the same way," **the skill form alone can serve both hosts** — one artefact, no generator, no drift guard, no parity tests. Today both forms ship, so `/harness:build` and `/harness:command-build` are two invocable paths to the same workflow, the second generated from the first.

Secondary cost: nine slots against the 1% listing budget, with nine descriptions opening on the same eleven words — near-worst-case for a matcher that discriminates on description text.

**Before acting on this, verify two things** the audit did not: (a) what Codex actually reads from a packaged plugin — if it reads `skills/` but not `commands/`, collapsing to the skill form works; if it reads neither directly, the generator is doing something else; (b) whether the path-resolution preamble (*"The portable plugin root is two directories above this SKILL.md"*) is load-bearing for host-cache installs in a way a plain skill could not achieve.

**Gap — no evals anywhere**
There is no `evals/` directory, no trigger test set, no with/without comparison for any of the 29 skills. Iron law 2 states that prose "can only check that words are present, and a sentence saying the opposite passes it" — which is correct, and is precisely the problem Anthropic's eval loop solves. The harness has diagnosed the disease and not adopted the published treatment. Given that the harness's *entire product* is guidance, this is the largest single gap in the audit.

Concretely, the missing loop for each skill: 8–10 should-trigger and 8–10 near-miss should-not queries at threshold 0.5; 2–3 output-quality scenarios run with and without the skill in fresh contexts; a recorded delta.

**Gap — `references/craft.md` is 776 lines**
Reference files have no hard cap, but at 776 lines it is 2.5× the largest SKILL.md and well past the point where a partial read is likely. Check it has a table of contents (required above 100 lines) and that nothing references it *through* another reference (the one-level-deep rule).

**Gap — skills are loaded up front, not per stage**
`commands/build.md` names `worktree-isolation`, `engineering`, `architecture`, `ux-design`, `design-system`, `review-discipline`, `spec-authoring`, `writing-quality`, plus a provider skill and `craft.md`. Against the 25,000-token/5,000-per-skill compaction re-attachment budget, a long build run will silently lose the earliest of these. Load each at the stage that needs it, and state in the command that the stage re-loads rather than assuming carry-over.

**Direction set 2026-09-04 — delete first, keep the product**
Of the 29 skills, the seven that encode the lifecycle (`engineering`, `review-discipline`, `spec-authoring`, `assessment-craft`, `process-economy`, `work-discovery`, `worktree-isolation`) are the product and stay. The two provider skills (`github-issues` 126 lines, `linear` 120 lines) are commodity API recipes with zero differentiation that break when the APIs move — the strongest swap candidates, to the official `github` / `linear` plugins, pinned. `ux-design` overlaps `frontend-design`; `design-system` is about the repo's own tokens layer and is a weaker case. `writing-quality` (49 lines) and `systematic-debugging` (45 lines) have no official coverage and should face the deletion test rather than a replacement search — a skill restating what the model already does is a cost regardless of who maintains it.

**Gap — `model:` and `effort:` are unused**
No file under `skills/`, `agents/` or `commands/` sets either field. The assurance levels are a tiering scheme carried entirely in prose, and ADR 0005 retired per-ticket model tiering in August 2026 partly because the label-based mechanism cost a tracker round-trip and five degradation branches to read a label nobody set. The frontmatter fields remove that entire class of plumbing: `effort` on a skill or subagent is applied by the runtime, not requested of the agent. Worth revisiting the retired decision on the new mechanism — the finding that killed it was about the *resolution path*, not about tiering being worthless.

Note also what ADR 0005 already establishes: 110 Opus reviews against 114 Sonnet, fail rates 18.4% vs 17.3%. That 1.1pp delta sits well under the 3pp noise floor in [03](03-quality-principles.md) §8, so the honest reading is **no detectable difference** — a stronger and cheaper conclusion than "Sonnet is adequate", and better evidence than any external source offers.

**Question to settle**
Four agents (`architect`, `dev`, `reviewer`, `steward`) each have a paired `agent-*` skill. Verify that the pairing is not a third layer of indirection — agent file → agent skill → domain skill. `[A]` The one-level-deep rule exists because chained references get partially read; the same failure applies to chained role definitions.
