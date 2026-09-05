# 01 — Instruction files: CLAUDE.md and AGENTS.md

**Read when:** writing or pruning an always-on instruction file, or deciding whether a rule belongs in one at all.

---

## 1. What these files are

`[A]` CLAUDE.md is **always-on context, not enforced configuration**. Anthropic states it plainly: "Claude treats them as context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook instead." The content "is delivered as a user message after the system prompt, not as part of the system prompt itself... there's no guarantee of strict compliance."

Two consequences the redesign must internalise:

1. **Anything stated as a law in CLAUDE.md is a request.** If violating it must be impossible, it belongs in a hook, a CI check, or branch protection. Stating it in CLAUDE.md as well is fine, but the file is the *explanation*, never the *control*.
2. **Every line is paid for on every turn.** The file is re-injected each request and survives compaction (project-root only). Cost is continuous, not one-off.

## 2. Length

`[A]` **Target under 200 lines.** Verbatim: "target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence." And, in the failure-patterns section: "**Bloated CLAUDE.md files cause Claude to ignore your actual instructions!**"

The mechanical limit (4 MiB, files larger are skipped) is irrelevant — 200 lines is the behavioural limit.

**Why 200 and not 500** `[R]`:

- IFScale (arXiv 2507.11538) — at 500 simultaneous instructions the best frontier models reach **68% accuracy**. Degradation is dominated by **omission**, not misapplication: the model silently drops rules. Primacy bias (earlier instructions favoured) peaks around 150–200 instructions and then flattens, meaning past that density you cannot even rely on "put it at the top."
- Chroma's *Context Rot* — across 18 models, "models do not use their context uniformly"; a single distractor degrades accuracy on simple tasks.
- `[A]` Anthropic's own framing: LLMs have an "attention budget"; the target is "the smallest possible set of high-signal tokens."

**Rule:** treat instruction count, not line count, as the real budget. A 150-line file containing 300 discrete obligations is over budget. A 190-line file containing 40 obligations and 150 lines of configuration table is fine.

## 3. The inclusion test

`[A]` One question decides every line: **"Would removing this cause Claude to make mistakes?" If not, cut it.**

Anthropic's include/exclude table:

| Include | Exclude |
|---|---|
| Bash commands Claude cannot guess | Anything derivable by reading the code |
| Style rules that **differ from defaults** | Standard language conventions |
| Test runners and how to run one test | Detailed API docs (link instead) |
| Repo etiquette (branch naming, merge vs rebase) | Frequently-changing information |
| Project-specific architectural decisions | Long explanations or tutorials |
| Environment quirks and non-obvious gotchas | File-by-file descriptions of the codebase |

`[A]` `/doctor` (v2.1.206+) automates the cut: it "cuts content Claude can derive from the codebase, such as directory layouts, dependency lists, and architecture overviews, and keeps pitfalls, rationale, and conventions that differ from tool defaults." That sentence is the sharpest available keep/cut predicate — steal it as the maintenance rule.

`[A]` The add-trigger is equally concrete: **"Claude gets a convention or command wrong twice → add it to CLAUDE.md."** Not once. Not preemptively.

## 4. Where a rule belongs — the routing table

`[A]` This is the decision that keeps the file short. Anthropic's routing, with the trigger that fires it:

| Trigger | Destination | Why |
|---|---|---|
| Claude gets a convention wrong twice | **CLAUDE.md** | Broadly applicable, always needed |
| Rule only matters for one part of the tree | **`.claude/rules/*.md` with `paths:` frontmatter** | Loads only when Claude touches matching files |
| Multi-step procedure, needed sometimes | **Skill** | On-demand, no standing context cost |
| You type the same prompt to start a task | **User-invocable skill** (`disable-model-invocation: true`) | Explicit trigger, off the listing budget |
| It must happen every time, without judgment | **Hook** | "An instruction… is a request, not a guarantee. A PreToolUse hook that blocks the edit is enforcement." |
| Claude needs data from a system it cannot see | **MCP server** (or a CLI tool — cheaper) | Connection + auth handled outside context |
| A second repo needs the same setup | **Plugin** | Distribution |

`[A]` Verbatim on the split: "If an entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped rule instead."

## 5. Structure and phrasing

`[A]` Confirmed guidance:

- **Use markdown headers and bullets.** "Claude scans structure the same way readers do: organized sections are easier to follow than dense paragraphs." There is otherwise no required format.
- **Specificity beats exhortation.** Anthropic's own paired examples:
  - "Use 2-space indentation" ✓ / "Format code properly" ✗
  - "Run `npm test` before committing" ✓ / "Test your changes" ✗
  - "API handlers live in `src/api/handlers/`" ✓ / "Keep files organized" ✗
- **Emphasis is a scarce resource.** "If Claude keeps skipping one instruction, add emphasis such as 'IMPORTANT' to that line alone. **If you emphasize many lines, none of them stands out.**" A file where every rule is bolded, capitalised, or called a law has spent its emphasis budget to zero.
- **Consistency is load-bearing.** "if two rules contradict each other, Claude may pick one arbitrarily."
- **HTML comments are free.** `<!-- maintainer notes -->` block comments are stripped before injection. Put rationale, ownership, and "why this rule exists" here at zero token cost — and keep the visible line to the obligation itself.

`[J]` Derived rule for law-style content: **one obligation per line, stated as an imperative, with the rationale in an HTML comment.** A 120-word paragraph containing five nested obligations reads as one instruction to a human and as five poorly-separated ones to a model, and it burns the primacy slot that a scannable list would use better.

## 6. Hierarchy and merge

`[A]` Load order, broadest → most specific:

1. Managed policy — `/Library/Application Support/ClaudeCode/CLAUDE.md` (macOS), `/etc/claude-code/CLAUDE.md` (Linux), or inlined via `claudeMd` in `managed-settings.json`. Cannot be excluded.
2. User — `~/.claude/CLAUDE.md`
3. Project — `./CLAUDE.md` or `./.claude/CLAUDE.md`
4. Local — `./CLAUDE.local.md` (gitignored, appended after CLAUDE.md at each level)

**Merge is additive, not overriding.** "All discovered files are concatenated into context rather than overriding each other." Ordering runs filesystem-root → working directory, so nearer files are read last. Conflicts are resolved by model judgment, "with more specific instructions typically taking precedence."

**⚠ Divergence from the AGENTS.md standard.** `[E]` agents.md specifies *nearest-wins*: "The closest AGENTS.md to the edited file wins." Claude Code *concatenates everything*. A repo that relies on a nested file suppressing a root rule will not get that behaviour in Claude Code. Do not design a hierarchy that depends on override.

**Nested files load lazily** and are pulled in when Claude reads a file in that subdirectory. **Only the project-root file survives compaction** — after `/compact` it is re-read from disk and re-injected; nested and path-scoped files reload only when re-triggered. `[J]` Therefore anything that must hold across a long session belongs in the root file, not a subdirectory one.

**Agent SDK:** loading is controlled by `settingSources` / `setting_sources`, not by the `claude_code` preset. An empty `settingSources` array loads nothing. The SDK injects content into the conversation and leaves the system prompt untouched, so CLAUDE.md never invalidates a system-prompt cache key.

## 7. Imports

`[A]` Syntax `@path/to/import`, relative to the importing file, recursion to **four hops**, code spans and fences skipped.

**The critical caveat:** "Splitting into `@path` imports helps organization but doesn't reduce context, since imported files load at launch." Imports are a filing system, not a diet. If the file is too long, the fix is a skill or a path-scoped rule — never an import.

## 8. AGENTS.md

`[A]` **"Claude Code reads `CLAUDE.md`, not `AGENTS.md`."** Two supported bridges:

```markdown
@AGENTS.md

## Claude Code
Use plan mode for changes under `src/billing/`.
```

…or `ln -s AGENTS.md CLAUDE.md` where no Claude-specific content is needed (symlinks need Developer Mode on Windows; prefer the import there).

`[E]` AGENTS.md is a real standard — moved to the Agentic AI Foundation under the Linux Foundation on 2025-12-09 alongside MCP, with Anthropic, OpenAI and Block as participants. It claims 60k+ repos and 30+ tools. It is "just standard Markdown. Use any headings you like."

**Recommended shape** `[E]`, ecosystem consensus: **one source of truth in `AGENTS.md`; `CLAUDE.md` is a thin bridge** (`@AGENTS.md` plus Claude-specific deltas). Never maintain two copies of the same content.

`[J]` A generator that emits a second full copy from the first is a third option, and it is the worst of the three: it doubles the maintenance surface, it needs a drift guard to stay honest, and the drift guard needs its own tests. The import/symlink bridge achieves the same portability with no generated artefact, no guard, and no test.

## 9. What does *not* have evidence

- **Positive vs negative framing** (`always do X` vs `never do Y`). No Anthropic or research source compares them. Anthropic's own docs use both freely. Do not assert a preference.
- **"Rules near the top."** Supported only indirectly, by IFScale's primacy finding, and that finding weakens above ~200 instructions. Weak-to-moderate confidence.
- **Practitioner numbers in circulation** ("30% task-completeness reduction", "2,500-file analysis", named A/B tests) — no primary sources located. Treat as unsupported.

## 10. The unresolved tension: always-on vs on-demand

`[E]` Vercel's January 2026 eval is the strongest published counter-evidence to "move it to a skill." Testing Next.js 16 APIs outside the model's training data:

| Approach | Score |
|---|---|
| Baseline (no help) | 53% |
| Skill, default triggering | 53% |
| Skill, explicit instruction to use it | 79% |
| 8 KB compressed docs index in AGENTS.md | **100%** |

Their conclusion: "The 'dumb' approach (a static markdown file) outperformed the more sophisticated skill-based retrieval, even when we fine-tuned the skill triggers." Their own caveats: skills are better for "vertical, action-specific workflows," and the gap "may close as models get better at tool use." Vendor-run eval, not independent.

`[J]` **Reconciliation.** The failure Vercel measured is *retrieval not firing*, not context cost. So:

> Keep in the always-on file: knowledge that is **needed on most tasks**, **not derivable from the repo**, and where **failure is silent** (the agent produces plausible-looking wrong output rather than an error).
> Move to a skill: knowledge that is **needed on some tasks** and where **failure is loud** (the agent notices it lacks the procedure and can go get it).

8 KB ≈ 200 lines, so Vercel's result sits *at* the recommended ceiling rather than licensing sprawl. It argues against reflexively emptying the file into skills, not for a long file.

---

## Where the harness stands

Audited at v6.0.1, 2026-09-04.

**Keep**
- CLAUDE.md is **98 lines / 8.7 KB** — inside the 200-line target, and near the size Vercel found optimal.
- The routing intent is right: "Skills carry the depth — load them by task."
- The generated block is version-stamped (`spine:generated harness@6.0.1`), so the installed surface is identifiable.

**Gap — obligation density, not line count**
Six "iron laws" occupy roughly 700 words. Law 1 is a single ~130-word sentence-chain containing at least eight distinct obligations (name the outcome; prefer native enforcement; cheapest evidence; RED then GREEN for behaviour; declaration plus functional execution for runtime floors; validator/producer/smoke for config; review prose directly; recorded risk decision for preventive guards; do not duplicate producer evidence). Against IFScale's omission finding, a paragraph like this is close to the worst possible packaging: the obligations are undifferentiated, so the ones that get dropped are unpredictable. Split into one imperative per line, rationale in HTML comments.

**Gap — emphasis is fully spent**
Every law is bolded and titled a law. Per `[A]`, "if you emphasize many lines, none of them stands out." There is no remaining way to raise the priority of a rule that is actually being skipped.

**Cost — AGENTS.md is a generated duplicate**
`AGENTS.md` is **151 lines / 18.7 KB**, generated from CLAUDE.md plus a guidance inventory by `scripts/generate_codex_artifacts.py`, with a drift guard and tests behind it. It is 2.1× the size of the file it derives from. The published pattern is the reverse — AGENTS.md as source, CLAUDE.md as a two-line bridge — and it eliminates the generator, the guard, and the tests in one move. If Codex genuinely needs a flattened inventory that Claude does not, that is an argument for a Codex-specific *appendix*, not a full second copy.

**Gap — no path-scoped rules**
`.claude/rules/*.md` with `paths:` frontmatter is unused. Several current CLAUDE.md contents are path-local by nature (design-system layer, `scripts/` stdlib-only rule, coverage scope). These are exactly what path-scoped rules exist for, and moving them frees always-on budget.

**Open question for the redesign**
The spine's config block (`repo:`, `tracker:`, `commands:`, `branches:`, `loop:`, `paths:`) is machine-read configuration living inside a prose instruction file. `[J]` Splitting it into a `harness.yaml` that both the guidance and the hooks read would (a) let the prose shrink to obligations only, (b) give the hooks a schema to validate instead of a markdown block to parse, and (c) remove a whole class of drift between what the file says and what the guards enforce. Nothing in the research requires this; it follows from "hooks are the control, prose is the explanation."
