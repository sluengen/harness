# 09 — Skills-only roles: is the agent file going away, and how to move role content into skills

**Read when:** redesigning how harness ships roles (architect, dev, reviewer, steward, harness-audit), deciding what belongs in an agent file versus a skill, or making the plugin portable beyond Claude Code and Codex.

Researched November 2026. Evidence tags follow INDEX.md (`[A]` Anthropic, `[E]` ecosystem vendor, `[P]` practitioner, `[J]` judgement). `[obs]` marks an observation of this repo.

---

## 1. Verdict

**The premise is half right, and the half that holds is the half that matters for harness.**

- **Not validated:** no major harness has *removed* agent definitions. Codex, opencode and Claude Code all still ship a first-class custom-agent format, and two of them changed or extended theirs this year. Bionic never had one: it launched skills-first, so nothing was abandoned there.
- **Validated:** reusable *instruction content* has converged on `SKILL.md` everywhere, the other instruction containers have been folded into skills (Codex custom prompts, Claude Code commands), and agent files are thinning into **runtime profiles** — model, tools/sandbox, isolation, effort — with skills able to drive delegation themselves.
- **Recommendation for harness:** make skills the only home for role content; keep per-harness agent files only as thin, generated runtime shims (or drop them where the harness can spawn a built-in agent with a skill). Do not go to literally zero agent files on Claude Code: reviewer independence and worktree isolation are runtime boundaries, and today only an agent definition expresses them reliably.

## 2. What each harness actually does (Nov 2026)

| Harness | Custom agent file | Body field | Can the agent attach skills? | Can a skill trigger a subagent? | Plugin can ship agents? |
|---|---|---|---|---|---|
| Claude Code `[A]` | `agents/*.md` | Markdown body | Yes — `skills:` preloads full skill content | Yes — `context: fork` + `agent:` | Yes, but `hooks`, `mcpServers`, `permissionMode` ignored |
| Codex `[E]` | `.codex/agents/*.toml` | `developer_instructions` (required) | No — skills inherit from parent; agent can only disable them | Yes — Codex delegates "when applicable project or skill instructions request it" | **No** — plugins ship skills, MCP, apps, hooks only |
| opencode `[E]` | `.opencode/agents/*.md` (V2) | Body → `system`; V1 fields incl. `prompt`, `tools` deprecated | No `skills` field; skills governed by a `skill` permission | Via `subagent` tool / permissions | n/a (config dirs) |
| Bionic (LM Studio) `[E]` | None documented | — | — | — | Reads skills from Codex/Claude Code |

Details behind the table:

- **Codex.** Custom agents are standalone TOML with required `name`, `description`, `developer_instructions`; optional model/effort fields and capability *reductions*; `sandbox_mode`, `approval_policy`, `model_provider` and `mcp_servers` are inherited, not overridable. Custom prompts were deprecated in favour of skills and removed in v0.117.0 (March 2026). Plugin manifests point at `skills/`, `.mcp.json`, `.app.json` and hooks — there is no agents component. `[E]` A practitioner reports `spawn_agent` takes an agent type plus model/prompt overrides, so a built-in `worker` can be given a role at spawn time. `[P]`
- **opencode.** V2 kept markdown agents (`mode: primary|subagent|all`, `permissions`, `steps`), renamed the prompt to `system`, and deprecated V1 frontmatter. Skills are discovered from `.opencode/skills`, `.claude/skills` and `.agents/skills`, so a repo-level harness skill is visible to opencode with no adapter. `[E]`
- **Claude Code.** Commands were merged into skills. Agents gained `skills:` (preload) and skills gained `context: fork` + `agent:` (run the skill as a subagent's prompt). The two are inverses: with `skills:` the agent owns the system prompt; with `context: fork` the skill content is injected into the named agent. `[A]` `context: fork` has a history of being silently ignored in some versions (issues #16803, #17283, #49559 — the last against 2.1.112, plugin skill dispatching inline). `[P]` Treat it as useful but verify it per release.
- **Bionic.** Launched July 2026; added Agent Skills in August, including reading skills already installed for Codex and Claude Code. No custom agent/persona format is documented. `[E]`
- **Spec.** agentskills.io defines six fields (`name`, `description`, `license`, `compatibility`, `metadata`, experimental `allowed-tools`); everything else is a per-harness extension. `[E]`

`[J]` The pattern across vendors: **agent = runtime boundary + config; skill = what to do and how to think.** Practitioner guidance states it outright: agents justify a separate definition only through a distinct role, permission boundary, model or isolated context — "put reusable procedures in skills instead of creating persona-only agents." `[P]`

## 3. Why this matters for harness specifically

- `[obs]` `agents/*.md` (447 lines) are duplicated as `.codex/agents/*.toml` (437 lines), held in correspondence by `test_codex_agent_adapters.py` after #537 retired the generator. Two copies of every role, one test to keep them honest.
- `[obs]` Every agent body opens with a path-resolution disclaimer because "this file may be a copy vendored into" a consuming repo. That is the cost of Codex plugins being unable to ship agents: the role content cannot travel through the plugin, so it is vendored.
- `[obs]` `.codex-plugin/plugin.json` already declares only `"skills": "./skills/"`. Skills are the one component both plugin manifests carry natively.
- `[J]` Moving role bodies into skills gives one copy, distributed by both plugins, readable by opencode/Bionic/Copilot for free, and removes the vendoring problem for everything except the thin runtime shim.

## 4. Recommended target shape

**Skills-canonical, agents-as-shims.** In order of preference per harness:

1. **Role content → a skill per role** (`skills/reviewer/`, `skills/dev/`, …), or folded into an existing procedure skill where the role and procedure are 1:1 (e.g. reviewer ↔ `review`). The skill states stance, inputs (the packet), output contract and hard constraints, and is written to work both inline and as a forked subagent prompt.
2. **Orchestrating skills own delegation.** `promote`, `build`, `drain` etc. say *"dispatch the `reviewer` role in a fresh context with this packet"* in harness-neutral wording, with a short per-harness note on mechanism. Independence comes from the fresh context, not from the persona text.
3. **Claude Code shim** — an `agents/<role>.md` of roughly 10–15 lines: `name`, `description`, `tools`, `model`, `effort`, `isolation: worktree`, `skills: [<role>]`, and a one-line body ("Follow the preloaded `<role>` skill; your context is the packet you were given"). Kept because `tools` restriction and `isolation` are not reliably expressible from a skill alone.
4. **Codex** — `[J]` prefer **no custom agents**: the orchestrating skill instructs Codex to spawn a built-in `worker`/`explorer` that loads `$<role>`, with a model override where needed. This eliminates vendoring. Fall back to a generated, pointer-only TOML shim only if per-role model/effort can't be set at spawn time — verify this first, the evidence is practitioner-grade.
5. **opencode / Bionic / others** — no adapters. They read the skills; the role runs inline or via their own subagent mechanism. Document this as best-effort support.

## 5. Skill authoring best practice (applies to the migrated roles)

1. **Stay inside the spec for core fields.** `name` = directory name, lowercase-hyphen, ≤64 chars; `description` ≤1024 chars stating what it does, when to use it, and when not to. Harness-specific fields (`disable-model-invocation`, `context`, `agent`, `allowed-tools`) are fine but must be optional hints — the skill must still make sense to a harness that ignores them. `[E]`
2. **Progressive disclosure budget.** Metadata ~100 tokens; body under ~5,000 tokens / 500 lines; detail in `references/`, one level deep. `[E]` `[obs]` `promote` (714 lines) and `tracker` (402) already breach this and should be split as part of the move.
3. **Role skills are explicit-only.** A role skill auto-triggering in the main conversation would make the orchestrator "become" the reviewer and defeat independence. Set `disable-model-invocation: true` (Claude Code) and `policy.allow_implicit_invocation: false` in `agents/openai.yaml` (Codex). Note Claude Code cannot preload a skill marked `disable-model-invocation: true` via `skills:` `[A]` — so for preloaded roles either leave implicit invocation on with a narrow description, or have the shim body load the skill explicitly. The implementation design must pick one.
4. **A forked skill must carry a task, not just knowledge.** `context: fork` with reference-only content produces no output. `[P]` Role skills should open with the job and the return contract.
5. **Enforce with hooks, not prose.** Anything that must always hold (no push from reviewer, no edits outside the worktree) belongs in hooks or tool restrictions on the shim, not in skill text. `[A]`
6. **Paths relative to the skill root; other skills by name.** Drop the plugin-root `skills/...` path convention and its disclaimer; refer to sibling skills as "the `review-discipline` skill". `[E]` `[J]`
7. **Validate mechanically.** Run `skills-ref validate` over `skills/` in CI, plus a test that every shim references an existing skill and contains no role content beyond its pointer line. `[E]` `[J]`
8. **Write descriptions for routing, not marketing.** The description is the only thing loaded for every skill on every turn; front-load trigger words and exclusions. `[E]`

## 6. Decisions to make in the implementation design

1. **Generated vs hand-written shims.** `[J]` With bodies gone, shims are mechanical; regenerating them from one `roles` table (name, description, model, effort, tools, isolation) is cheaper than a correspondence test. Revisit #537's reason for retiring the generator before deciding.
2. **Separate role skills or merge into procedure skills.** Reviewer ↔ `review`/`review-discipline` and dev ↔ `build`/`engineering` overlap heavily; merging reduces skill count and listing budget, separating keeps each body under budget.
3. **Codex: built-in spawn vs TOML shims.** Test whether `spawn_agent` model/effort overrides work in the current CLI before committing.
4. **Preload vs explicit load on Claude Code** (see §5.3).
5. **`harness-audit` (169 lines)** reads like a procedure rather than a role; likely a plain skill with `context: fork`, no shim.
6. **Fallback when a harness has no subagent mechanism** (Bionic): run the role inline and say in the report that independence was not achieved, rather than failing silently.

## 7. Suggested migration order

1. Move each agent body into its skill (or merge target); split oversize skills while there.
2. Replace `agents/*.md` with shims; add the shim/skill CI checks.
3. Rewrite delegation in orchestrating skills to name roles, not agent files.
4. Replace or delete `.codex/agents/*.toml` and `test_codex_agent_adapters.py` per decision 3.
5. Remove vendoring paths and the path disclaimer; dogfood a full ticket on Claude Code and Codex; smoke-test discovery in opencode.

## Sources

- Claude Code subagents — https://code.claude.com/docs/en/sub-agents `[A]`
- Codex custom agents / subagents — https://learn.chatgpt.com/docs/agent-configuration/subagents.md `[E]`
- Codex skills — https://learn.chatgpt.com/docs/build-skills `[E]`
- Codex changelog (custom prompts deprecated) — https://developers.openai.com/codex/changelog `[E]`; removal in v0.117.0 — https://codex.danielvaughan.com/2026/04/10/migrating-custom-prompts-to-skills/ `[P]`
- Codex plugin components — https://developers.openai.com/codex/plugins/build `[E]`; cross-tool comparison — https://awslabs.github.io/aidlc-workflows/reference/research/Cross-Tool%20Plugin%20Comparison/ `[E]`
- Codex spawn_agent overrides — https://codex.danielvaughan.com/2026/03/26/codex-cli-subagents-toml-parallelism/ `[P]`
- opencode agents (V2) — https://opencode.ai/docs/agents ; skills — https://opencode.ai/docs/skills `[E]`
- Bionic skills — https://lmstudio.ai/blog/skills ; https://lmstudio.ai/docs/bionic/agent/skills `[E]`
- Agent Skills spec — https://agentskills.io/specification `[E]`
- `context: fork` issues — https://github.com/anthropics/claude-code/issues/49559 , /17283 `[P]`
- Persona-only agents guidance — https://www.skills.sh/rcdailey/dotfiles/subagent-authoring `[P]`
