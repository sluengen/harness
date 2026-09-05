# 99 — Sources and verification notes

Gathered September 2026. Domains moved during 2025–26: `anthropic.com/engineering/claude-code-best-practices` now redirects to `code.claude.com/docs/en/best-practices`; `docs.claude.com` redirects to `platform.claude.com`. Guidance quoting the April 2025 wording is quoting a superseded revision.

## Anthropic — documentation

- [Claude Code best practices](https://code.claude.com/docs/en/best-practices)
- [Memory / CLAUDE.md](https://code.claude.com/docs/en/memory)
- [Extend Claude Code (feature routing table)](https://code.claude.com/docs/en/features-overview)
- [Skills](https://code.claude.com/docs/en/skills) · [Subagents](https://code.claude.com/docs/en/sub-agents) · [Worktrees](https://code.claude.com/docs/en/worktrees) · [/goal](https://code.claude.com/docs/en/goal) · [Hooks](https://code.claude.com/docs/en/hooks) · [MCP](https://code.claude.com/docs/en/mcp)
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) · [Agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop) · [Modifying system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts) · [Approvals and user input](https://code.claude.com/docs/en/agent-sdk/user-input)
- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) · [Skill best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Agent Skills specification](https://agentskills.io/specification) · [best practices](https://agentskills.io/skill-creation/best-practices.md) · [optimizing descriptions](https://agentskills.io/skill-creation/optimizing-descriptions.md) · [evaluating skills](https://agentskills.io/skill-creation/evaluating-skills.md) · [using scripts](https://agentskills.io/skill-creation/using-scripts.md)
- [anthropics/skills](https://github.com/anthropics/skills) — reference SKILL.md files

## Anthropic — engineering and research posts

- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Building a multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Infrastructure noise in agent benchmarks](https://www.anthropic.com/engineering/infrastructure-noise)
- [Building a C compiler with parallel Claudes](https://www.anthropic.com/engineering/building-c-compiler)
- [Claude Code auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode) · [Sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing) · [Scaling managed agents](https://www.anthropic.com/engineering/managed-agents)
- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Natural emergent misalignment from reward hacking](https://www.anthropic.com/research/emergent-misalignment-reward-hacking)
- [Steering Claude Code: skills, hooks, rules, subagents](https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more)
- [A harness for every task: dynamic workflows](https://claude.com/blog/a-harness-for-every-task-dynamic-workflows-in-claude-code)

## Research

- [ImpossibleBench (arXiv 2510.20270)](https://arxiv.org/abs/2510.20270) — test-conflicting benchmarks; cheat taxonomy and intervention effects
- [EvilGenie (arXiv 2511.21654)](https://arxiv.org/html/2511.21654v2) — ambiguity as the precondition for reward hacking; detector comparison
- [SpecBench (arXiv 2605.21384)](https://arxiv.org/html/2605.21384v1) — visible-vs-held-out gaps at scale
- [BaitBench (arXiv 2608.30724)](https://arxiv.org/html/2608.30724) — planted optional shortcuts
- [IFScale (arXiv 2507.11538)](https://arxiv.org/abs/2507.11538) — instruction-density degradation, omission bias, primacy
- [Chroma: Context Rot](https://www.trychroma.com/research/context-rot) — non-uniform context use across 18 models
- [TDD for Code Generation (arXiv 2402.13521)](https://arxiv.org/abs/2402.13521) · [Scaling TDD from Functions to Classes (arXiv 2602.03557)](https://arxiv.org/abs/2602.03557) · [TDD-Agent (arXiv 2608.16742)](https://arxiv.org/abs/2608.16742)
- [METR: Measuring AI ability to complete long tasks](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/) — March 2025, stale numbers, useful shape

## Ecosystem and vendor

- [github/spec-kit](https://github.com/github/spec-kit) · [agentic SDD reference](https://github.github.io/spec-kit/reference/agentic-sdd.html) · [spec-driven.md](https://raw.githubusercontent.com/github/spec-kit/main/spec-driven.md) · [spec-template.md](https://raw.githubusercontent.com/github/spec-kit/main/templates/spec-template.md) · [clarify.md](https://raw.githubusercontent.com/github/spec-kit/main/templates/commands/clarify.md)
- [Kiro: spec concepts](https://kiro.dev/docs/specs/concepts/) · [requirements-first](https://kiro.dev/docs/specs/feature-specs/requirements-first/) · [best practices](https://kiro.dev/docs/specs/best-practices/)
- [EARS — Alistair Mavin (primary source)](https://alistairmavin.com/ears/)
- [GitHub Copilot coding agent — get the best results](https://docs.github.com/en/copilot/tutorials/cloud-agent/get-the-best-results) · [about coding agent](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent) · [WRAP framework](https://github.blog/ai-and-ml/github-copilot/wrap-up-your-backlog-with-github-copilot-coding-agent/) · [assigning issues](https://github.blog/ai-and-ml/github-copilot/assigning-and-completing-issues-with-coding-agent-in-github-copilot/)
- [OpenAI Codex — best practices](https://developers.openai.com/codex/learn/best-practices) · [prompting](https://developers.openai.com/codex/prompting) · [cloud](https://developers.openai.com/codex/cloud/)
- [Linear: agent interaction best practices](https://linear.app/developers/agent-best-practices)
- [Atlassian: writing tickets for AI agents](https://www.atlassian.com/blog/jira/writing-tickets-for-ai-agents)
- [agents.md](https://agents.md/) · [Linux Foundation — Agentic AI Foundation](https://www.linuxfoundation.org/press/linux-foundation-announces-the-formation-of-the-agentic-ai-foundation)
- [Vercel: AGENTS.md outperforms skills in our agent evals](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- [specship: AI agent ticket template](https://specship.dev/templates/ai-agent-ticket-template/) `[P]`
- [Augment Code: AI spec template](https://www.augmentcode.com/guides/ai-spec-template) `[P]`
- [HumanLayer: writing a good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md) `[P]`

---

## Verification notes — read before citing

**Could not be verified from a first-party live source:**

1. **Anthropic's original five-step TDD workflow.** The April 2025 page has been rewritten and no longer contains the numbered steps; web.archive.org was proxy-rejected (403). The wording in [05](05-tdd-for-agents.md) §1 comes from a widely-reproduced third-party mirror, corroborated across independent reproductions. High confidence in the content, not first-party-live.
2. **spec-kit's current constitution template text.** Both plausible raw paths 404'd. The "Test-First Imperative" quote is from the repo's philosophy document quoting the constitution, which may lag the shipped template.
3. **Kiro's task→requirement traceability syntax** (commonly reported as `_Requirements: 1.1, 2.3_`). Kiro's docs describe traceability without showing the literal formatting.
4. **Whether `ultrathink` still functions.** Absent from the live docs; `effort` is the documented mechanism. Not confirmed as a removed alias.
5. **Devin and Cursor background agents.** No primary sources reached; searches returned only SEO content. Do not cite claims about either from this report.
6. **Whether Codex or Copilot gate PR creation on passing tests.** Not documented at overview level for either.
7. **Practitioner numbers in circulation** — a "30% task-completeness reduction" from a poorly structured AGENTS.md, a "2,500-file analysis", named A/B tests. No primary sources located. Unsupported.

**Genuine gaps in the published state of the art.** Nothing was found on any of these; guidance in this report marked `[J]` is proposed, not derived:

- How to verify a failing test failed for the **right reason** (assertion failure vs collection/import error).
- **Proportionate verification for non-behavioural changes** — config, docs, generated artefacts, migrations.
- The rule that a **measurable criterion requires a measuring test** (measurability of the criterion is published; the measuring test is not).
- **Builder/recorder separation** for as-built records — no vendor or research precedent.
- **Mutation testing or coverage-as-guard as anti-reward-hacking controls** — no controlled study.
- Any published **effectiveness measurement of review agents** — bug-catch rate, false-positive rate. Anthropic asserts the self-grading bias qualitatively and repeatedly; nobody has published the number. **This is the largest evidence gap in the report**, and it sits under the most expensive stage in most harness designs.
- Any Anthropic-official treatment of **hallucinated APIs**.
- Any authoritative **schema standard for agent-consumable tickets**.

**Contested, with both sides sourced:**

- Third-person vs imperative in skill descriptions — two Anthropic-controlled sources disagree ([02](02-skills-and-agents.md) §4).
- Always-on instruction file vs on-demand skill — Anthropic's length discipline vs Vercel's 100%-vs-79% eval ([01](01-instruction-files.md) §10).
- Comments as the ticket audit trail — Linear says no, GitHub builds on them ([08](08-tickets-as-specs.md) §5).
- Tests as frozen validators vs evolving artefacts — Anthropic/spec-kit vs TDD-Agent ([05](05-tdd-for-agents.md) §2).
- How much spec is too much — Anthropic defends vague prompts for exploration and warns about over-engineering from adversarial review; the spec-heavy vendors offer no counterweight ([06](06-spec-driven-development.md) §3).

**Two numbers to keep in mind when reading any comparison:**

- `[A]` Benchmark differences **below 3 percentage points** deserve scepticism until eval configuration is documented and matched — infrastructure resourcing alone moved Terminal-Bench 2.0 by 6pp.
- `[A]` Multi-agent systems use **~15× the tokens of chat**; single agents ~4×. Figures are from Claude 4-generation models on a research domain — directional, not current.

---

## Independent verification pass

Thirteen high-stakes claims were re-checked against primary sources by a separate agent that did not write the report. **All thirteen verified**; nothing was contradicted or unreachable. Four changes were applied as a result:

| # | Issue | Change |
|---|---|---|
| 1 | The trigger-eval protocol (20 queries, 3 runs, 0.5 threshold) was attributed to `evaluating-skills.md` | Re-pointed to [optimizing-descriptions.md](https://agentskills.io/skill-creation/optimizing-descriptions.md); `evaluating-skills.md` covers output-quality evals only |
| 2 | "Create evaluations BEFORE writing extensive documentation" was attributed to agentskills.io | Re-pointed to [platform.claude.com Agent Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) |
| 3 | "Read-only test access is the recommended middle ground" overstated ImpossibleBench | The paper recommends "either hiding test files entirely or restricting them to read-only access during implementation". The middle-ground framing is now marked `[J]` |
| 4 | EvilGenie's ambiguous-problem figures were quoted without their sample size | Added: the ambiguous set is **n=9** (2–4 incidents per percentage), and the low unambiguous figures exclude a separate **"heuristic solutions"** category on which Claude scored 20.7% |

**A fifth correction, applied after review (2026-09-04).** The claim that "custom commands have been merged into skills" was re-verified and is exact — [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills): *"**Custom commands have been merged into skills.** A file at `.claude/commands/deploy.md` and a skill at `.claude/skills/deploy/SKILL.md` both create `/deploy` and work the same way. Your existing `.claude/commands/` files keep working."* It is a note on the skills page, not a deprecation.

But the **inference drawn from it** in [02](02-skills-and-agents.md) was wrong and has been rewritten. The report claimed the merge "largely dissolved" the problem the harness's `command-*` adapters solve. It does not: those adapters target Codex, and the merge is a statement about Claude Code's slash-command resolution only. The adapters were also mischaracterised as indirection when they in fact embed their command files verbatim. The corrected callout states the narrower argument that does survive, and names two things that must be verified before acting on it. **Lesson for readers: `[A]` tags certify the quotation, not the conclusion drawn from it.**

Verified verbatim, for anyone re-checking:

- "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence."
- "All discovered files are concatenated into context rather than overriding each other."
- "Splitting into `@path` imports helps organization but doesn't reduce context, since imported files load at launch."
- "Claude Code reads `CLAUDE.md`, not `AGENTS.md`."
- "Claude stops when the work looks done." · "The trust-then-verify gap." · "Claude Code overrides the hook and ends the turn after 8 consecutive blocks."
- "The most useful specs **are self-contained**: they name the files and interfaces involved, state what is out of scope, and end with an end-to-end verification step that proves the feature works." *(the "are self-contained" clause is part of the sentence — keep it when quoting)*
- ImpossibleBench full title: *ImpossibleBench: Measuring LLMs' Propensity of Exploiting Test Cases* (Zhong, Raghunathan, Carlini). "GPT-5 cheats in 76% of the tasks in Oneoff-SWEbench"; "cheats 54.0% of the time on Conflicting-SWEbench"; "appropriate prompt could dramatically reduce GPT-5's cheating from 92% to 1%"; intervention tool "lowering the cheating rate of GPT-5 from 54% to 9% and o3 from 49% to 12%."
- IFScale full title: *How Many Instructions Can LLMs Follow at Once?* Primacy effects "peak around 150-200 instructions, then level off or decrease at extreme densities" — so the finding does **not** support "put important rules first" in a very long prompt.
- Linear Agent Activities are "frozen-in-time snapshots of user input"; the `created` event must be answered "within 10 seconds… or the agent will be shown as unresponsive."
