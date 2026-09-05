# 04 — Structuring an agentic workflow: ticket → finished product

**Read when:** designing the pipeline — its stages, isolation model, handoff artefacts, review loop, escalation, and definition of done.

---

## 1. The composite pipeline the evidence supports

Assembled from Anthropic's spec-then-fresh-session pattern, the long-running-agent posts, spec-kit, Kiro, and the C-compiler project. Each stage names **its own exit check**, because a stage without one ends when the model feels finished (see [03](03-quality-principles.md) §1).

| # | Stage | Produces | Exit check | Context |
|---|---|---|---|---|
| 1 | **Intake / triage** | Classification: fast-lane · ticket · proposal | Duplicate search done; exactly one weight assigned | Main |
| 2 | **Spec** | A self-contained change spec | No unresolved `[NEEDS CLARIFICATION]`; every criterion has named evidence | Main (interview) |
| 3 | **Ground** | Verified current-reality brief, `path:line` anchored | Every fact the spec rests on is checked, not recalled | **Fresh subagent** |
| 4 | **Isolate** | Worktree + branch off the integration branch | Working tree clean; base pinned and recorded | — |
| 5 | **Design** (large only) | Contracts, scenarios, test strategy | Design answers every criterion, or stops | **Fresh subagent** |
| 6 | **Build** | Diff + tests | Test-first evidence per criterion; lint clean | **Fresh subagent** |
| 7 | **Review** | Verdict + findings | Independent, fresh context, scoped mandate | **Fresh subagent** |
| 8 | **Reconcile** | Merged candidate | Base movement absorbed; bounded attempts | — |
| 9 | **Gate** | Marker bound to a tree oid | Full gate green **over that exact tree** | Deterministic |
| 10 | **Ship** | Merge + tracker transition | Shipped tree == verified tree | Deterministic |
| 11 | **Record** | As-built record | Written by the reviewer, never the builder | Reviewer |

`[A]` Stage 1 is not ceremony to skip: **"If you could describe the diff in one sentence, skip the plan."** Planning earns its cost "when you're uncertain about the approach, when the change modifies multiple files, or when you're unfamiliar with the code." A pipeline with no cheap lane will be routed around.

## 2. Handoff artefacts: what makes context droppable

`[A]` The central mechanism is **spec → fresh session**: "Once the spec is complete, start a fresh session to execute it. The new session has clean context focused entirely on implementation."

`[A]` And, from the long-running-app work, **context resets with structured handoff are preferred over compaction**, because compaction "preserves conversation history but doesn't provide a clean slate."

**The test for a handoff artefact** `[J]`: could the next stage start from this file, with no conversation history, and produce the same result? If not, the artefact is incomplete and the pipeline cannot survive a reset — which means it also cannot survive a crash, a model switch, or a resumed run.

`[A]` The published artefact set from *Effective harnesses for long-running agents*:

- a **progress file** (what has been done, what is next)
- a **feature list in JSON with `passes: true/false`** — JSON deliberately, because **"the model is less likely to inappropriately change or overwrite JSON files compared to Markdown"**
- **git history** as the durable record; sessions end by "writing a git commit and progress update"

`[J]` That JSON finding is directly relevant to any harness whose status ledger is markdown checkboxes. A machine-read state that the agent can casually rewrite is a state that will drift; a JSON file with a schema is measurably stickier.

`[A]` Session start protocol from the same source: read progress + git log, run the app, **run the end-to-end test before implementing anything new**. This catches the case where the previous session left the tree broken and reported success.

## 3. Isolation

`[E]` Git worktrees are the consensus mechanism for branch-per-task parallelism.

`[A]` Claude Code's own worktree isolation is unusually strict and worth copying conceptually — four blocking checks:

1. edits targeting the main checkout
2. commands whose cwd resolves into the main checkout
3. **git redirects** — `git -C`, `--git-dir`, `GIT_DIR`, `GIT_WORK_TREE`, or a `cd` first
4. **command shapes it cannot statically verify** — brace expansion, unquoted heredocs

…and, critically: **"You can't turn this check off."** Subagents inherit it; `isolation: worktree` in subagent frontmatter makes it permanent. `.worktreeinclude` carries gitignored `.env` files into fresh checkouts.

`[J]` Point 4 is the interesting one and is easy to under-build: a guard that parses a command string will be defeated by a command shape it cannot parse. The correct response is to **refuse the unparseable case**, not to let it through. Any harness guard that inspects shell strings should be audited against this rule.

`[A]` **Sandboxing** needs **both** filesystem and network isolation to be worth anything: "Without network isolation, a compromised agent could exfiltrate sensitive files like SSH keys; without filesystem isolation, a compromised agent could easily escape the sandbox." Measured benefit: 84% fewer permission prompts.

## 4. Parallelism and merge

`[A]` The **C-compiler project** is the largest published data point: 16 parallel Claude instances, ~2,000 sessions, 2B input tokens, ~$20,000, two weeks, a 100k-line Rust C compiler that builds Linux 6.9. Its coordination layer:

- **File-based task locking through git.** Agents claim work by committing a file to `current_tasks/`. "If two agents try to claim the same task, git's synchronization forces the second agent to pick a different one." **No orchestration layer at all.**
- On conflicts: "Merge conflicts are frequent, but Claude is smart enough to figure that out."
- Agents broke existing functionality on every new feature **until CI enforcement was added**.
- A single monolithic task destroyed parallelism: "every agent would hit the same bug, fix that bug, and then overwrite each other's changes."

`[A]` And the counterweight from the multi-agent post: **"most coding tasks involve fewer truly parallelizable tasks than research, and LLM agents are not yet great at coordinating and delegating to other agents in real time."** Cost is ~15× chat tokens for multi-agent, ~4× for single agents.

`[J]` The reconciliation: parallelism across *independent tickets* is proven at scale and needs almost no orchestration (git itself is the lock). Parallelism *within* a ticket is where the warning applies. Design the queue for the first and resist the second.

**Base movement** is normal concurrency, not an exception. Treat it as a bounded, unattended-safe step: fetch, merge, resolve on plain meaning, cap the attempts, escalate only on genuine functional conflict.

`[J]` One trap worth stating in any reconciliation guidance: **a monotonic field both sides advanced independently converges on identical text and raises no conflict marker** — a version number, a migration ordinal, a sequence id. Identical text is not agreement. Detect same-valued monotonic fields explicitly.

## 5. Bounded loops and escalation

`[A]` Anthropic's own systems all have ceilings, and none loop forever:

| Mechanism | Ceiling |
|---|---|
| Stop hook | **8 consecutive blocks**, then Claude Code overrides and ends the turn |
| `/goal` | Halts with a warning after several turns of answering without tool use |
| Agent SDK | `max_turns`, `max_budget_usd` |
| Subagents | depth 3, 20 concurrent |

`[A]` The reason a *floor* on review passes is the wrong shape: "A reviewer prompted to find gaps will usually report some, even when the work is sound… Chasing every finding leads to over-engineering." Mitigation is scoping the mandate — "flag only gaps that affect correctness or the stated requirements" — not more passes.

`[J]` **Escalate, don't loop.** When the cycle budget is spent, the correct terminal state is a preserved branch, a written reason, and a human hold — not a fresh loop under a new name. This is one of the few places where doing less is strictly safer: an agent that keeps trying past its budget is an agent producing an unbounded diff nobody reviewed.

## 6. Human-in-the-loop placement

`[E]` GitHub's coding agent keeps a **mandatory human review before merge**, and it publishes an explicit do-it-yourself list: broad cross-repo refactors, work needing deep domain knowledge or substantial business logic, production-critical issues, anything touching security or PII, and **"tasks lacking clear definition: tasks with ambiguous requirements, open-ended tasks."**

`[E]` **Linear** publishes the only agent-state semantics I found:
- an agent that needs the human emits an `AgentActivity` of type **`elicitation`** or **`error`** rather than completing;
- an implementing agent with no delegate **sets itself as delegate**;
- but automation-routed work **stays in triage for a human to assign**;
- move to the first `started` status when work begins; acknowledge the created webhook within **10 seconds**.

`[A]` For unattended runs where a question arises, the SDK's published answer is a `PreToolUse` hook returning the **`defer` decision**, so the process exits and resumes later from the persisted session. **Suspend and resume, not guess.**

`[J]` The design rule: **a hold is a typed terminal state with the question recorded**, not a silent assumption and not a stall. The three things it must carry are why (a reason class), what is needed (the specific answer), and what was preserved (the branch and its findings).

## 7. Definition of done and provenance

`[A]` Two rules, both stated:

1. **Evidence, not assertion** — "the test output, the command it ran and what it returned, or a screenshot."
2. **Fresh** — the check must have been run against the current state, not recalled.

`[J]` The strong form is **binding the verification to a content identity**: a gate result names the exact tree it verified, so one further edit invalidates it mechanically rather than by judgment. This is the single most useful primitive in the current harness and should survive the redesign unchanged.

`[E]` Contested: **is the ticket comment thread the audit trail?** Linear says explicitly no — "Comments may not be reliable to read from, as they are editable and may have changed since your agent's last run" — and directs agents to immutable Agent Activities. GitHub builds its whole iteration loop on PR comments, with one useful efficiency rule: **"Start a review" to batch comments into a single work session** rather than firing one agent run per comment. Pick per tracker; do not assume.

## 8. Vendor pipelines, for shape comparison

`[E]` All self-descriptions; note the incentive.

- **GitHub Copilot coding agent** — issue / `@copilot` mention / Slack / Jira / Linear → ephemeral GitHub Actions environment → "research a repository, create an implementation plan, and make code changes on a branch" → "can execute automated tests and linters" → PR → mandatory human review. Hard limits: **59-minute execution ceiling**, single repository, one branch at a time. Notably the docs **do not** state that tests must pass for a PR to be raised — the verification gate is under-specified relative to Anthropic's guidance.
- **OpenAI Codex cloud** — parallel cloud tasks, configurable environments, sandboxing with auto-review, `@codex` GitHub delegation, PR creation. Verification mechanics not documented at overview level.
- Devin and Cursor background agents: **no primary sources reached.** Do not cite claims about them.

`[J]` The transferable observation: the mainstream vendor pipelines are *thinner* than a spec-driven harness and put the human at the merge boundary. Their bet is that human review catches what the pipeline does not. A harness that automates review instead must be able to show its review stage catches more than it manufactures — which is exactly the measurement nobody has published (see [03](03-quality-principles.md) §5).

---

## Where the harness stands

**Keep**
- The stage list is close to the composite in §1, and in one respect ahead of it: **reconciliation is placed immediately before the final binding**, which removes the review-wide window in which the base can move under a completed review. That is a genuinely good piece of design and nothing published states it as clearly.
- Tree-oid binding, with PASS invalid over any other tree, is stronger than any vendor equivalent found.
- DEFER as a distinct verdict from FAIL — "cannot ship as scoped" versus "fix and retry" — is a real distinction that the published verdict vocabularies lack.
- Abandon-safely (commit, push, comment, hold, keep the worktree) matches the "escalate, don't loop" rule and the preserved-state requirement.
- Hold = comment + label + assignment, always all three, is the concrete version of Linear's typed `elicitation` state.

**Cost — `commands/build.md` is a 143-line normative procedure**
It carries the assurance table, the design stage, the implement stage, visual-evidence capture rules (viewport slicing, pixel ceilings, capture naming, a 12-capture cap), implementation evidence, a nine-stage machine-readable lifecycle block, review dispatch, reconciliation with the monotonic-field trap, trivial certification, the full gate, three verdict branches, a four-step post-verdict re-bind path, and abandon-safely.

Two concerns, one procedural and one evidentiary:

1. It is read as *one* artefact at the start of a run that then spans many subagent contexts. Per [02](02-skills-and-agents.md) §3, invoked content is re-attached after compaction at 5,000 tokens per skill within a 25,000-token pool — a long run will lose parts of this. The visual-evidence rules, which apply at one stage only, are a clear candidate for extraction to a stage-loaded skill.
2. `[A]` "Grade what the agent produced, not the path it took." Several elements here certify that a stage ran in a prescribed order. Some of that is load-bearing (the tracker/git authority intervals prevent a real class of bug); some may be ceremony. The `process-economy` skill has the right test for this and has not been pointed at `build.md`.

**Gap — no cheap lane in practice**
CLAUDE.md defines a fast lane ("'fix X' is the whole invocation"), which is correct per `[A]` "skip the plan if you could describe the diff in one sentence." But every path still requires worktree + full gate, and there is no stated boundary for when the fast lane's *evidence* burden also shrinks. If the fast lane costs the same as a ticket minus the tracker write, agents will route small work through neither and the boundary will erode.

**Gap — handoff artefacts are conversational in places**
The change spec, the grounding brief and the design artefact are strong handoffs. The **run state** is not: `issues`, `verdict`, `reviewed_tree` are tracked *by the orchestrator* rather than persisted to a schema'd file. Per `[A]` "nothing in the harness needs to survive a crash" and the JSON-over-markdown durability finding, run state belongs in a JSON file the orchestrator reads at every stage boundary. This is also what makes a resumed or crashed run recoverable, and what would let `/routine` resume rather than restart.

**Gap — parallelism is per-ticket only, with no claim mechanism**
Iron law 5 gets isolation right, but there is no published equivalent of the C-compiler project's git-based task claiming. For an unattended `/routine` running more than one instance, two agents can pick the same Todo ticket. The fix is cheap and proven: claim by committing a file, and let git's synchronisation resolve the race.

**Check — tracker-comment reliance**
`/build` reads ticket comments as carried-forward findings. Per Linear's warning, comments are mutable and may have changed since the last run. Iron law 6 already treats ticket text as data, which covers the injection risk but not the staleness risk. Where the tracker offers an immutable activity stream, prefer it for anything the run *depends on*.
