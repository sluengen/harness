# Escalation Levels

Every agent action falls into one of four levels. Agents must self-classify their next action before executing it. The orchestrator enforces the same scale when mediating between agents and the user.

## L0 — Autonomous

> If it's read-only, trivially reversible, or explicitly authorised by the pipeline, just do it.

| Action | Examples |
|---|---|
| Read files, search code, explore codebase | Grep, Glob, Read tool |
| Run tests, lint, type-check | `pytest`, `ruff check`, `vitest run`, `tsc` |
| Format code | Auto-formatting within existing style rules |
| Create or switch branches | `git checkout -b`, `git worktree add` |
| Stage changes, create commits | `git add`, `git commit` |
| Write/edit code that implements an approved design | Backend-dev or frontend-dev building to spec |
| Write test files | TDD — tests first, then implementation |
| Generate artifacts within your role | Reviewer writing a report, steward writing a health check |

**Rule:** No notification needed. Just do it.

## L1 — Inform

> Do it, then explain. The user reviews after the fact.

| Action | Examples |
|---|---|
| Refactor within a single file | Rename internal variable, extract helper, simplify logic |
| Fix lint/type errors introduced by your own changes | Cleaning up after yourself |
| Update dev dependencies (patch/minor) | Bumping a test lib in `package.json` or `pyproject.toml` |
| Create new utility/helper files | A new `utils.ts` or test fixture file |
| Add error handling to existing functions | Where the design doc doesn't specify but correctness requires it |
| Carry-forward fixes from a reviewer report | Express-tier items with zero ambiguity |

**Rule:** Proceed, then mention what you did and why in your handoff summary.

## L2 — Propose

> Describe the plan and wait for approval before executing.

| Action | Examples |
|---|---|
| Change a public API or interface | New endpoint, changed response shape, removed field |
| Modify database schema | New table, altered column, migration |
| Delete files or remove functionality | Removing a module, endpoint, or component |
| Changes spanning 5+ files | Cross-cutting refactors, rename across codebase |
| Scope decisions (what's in vs. out) | PM deciding feature boundaries |
| Brand and copy direction | Marketing-comms positioning, tone, messaging |
| Architectural trade-offs | Architect choosing between competing approaches |
| Add a new production dependency | Anything added to `[project.dependencies]` or `dependencies` in `package.json` |
| Modify CI/CD pipeline | Changes to `.github/workflows/`, deployment config |

**Rule:** Present the options with trade-offs. Wait for explicit "go ahead" before proceeding.

### Agents with built-in L2 checkpoints

These agents pause at defined points — the orchestrator should expect and facilitate these conversations:

- **Product Manager** — pauses on user stories, acceptance criteria, scope decisions, domain-specific assumptions
- **Strategist** — pauses on priorities, principles, target personas, competitive positioning, trade-offs
- **Marketing & Communications** — pauses on positioning, brand direction, copy drafts, audience assumptions, tone choices, and final copy sign-off

## L3 — Stop

> Stop. Explain the situation. Wait.

| Action | Examples |
|---|---|
| Push to remote / create PR | `git push`, `gh pr create` — deployment-manager only, after reviewer PASS |
| Production deployments | Any action that affects live users |
| Irreversible data operations | Database migrations in production, data deletion |
| Security-sensitive changes | Auth flows, secrets handling, permissions, access controls |
| Overriding a reviewer FAIL | Never proceed past a FAIL without user direction |
| Uncertainty about correctness | "I'm not sure this is right" = stop and ask |
| Second reviewer FAIL | First FAIL goes back to dev; second FAIL stops the pipeline |
| Destructive git operations | `git reset --hard`, `git push --force`, `git branch -D` |
| Secret or credential access | Any task that requires API keys, tokens, or credentials to complete |

**Rule:** Halt immediately. Explain what you found, what the options are, and what you recommend. Do not proceed without explicit user instruction.

---

## How agents use this

1. **Before acting**, classify the action against the levels above.
2. **When in doubt, escalate up.** L1 unsure? Treat it as L2. L2 unsure? Treat it as L3.
3. **State the level** when escalating: "This is an L2 — I'd like to add a new production dependency (X). Here's why..."
4. **The orchestrator** maps agent checkpoints to levels. PM scope discussions are L2. Reviewer FAILs are L3. Everything between pipeline stages is L0.

## Customisation

The levels above are calibrated for a team of one human and multiple AI agents. Adjust thresholds if the context changes:

- **Higher-risk phase** (e.g. production launch): promote CI/CD changes and dependency additions to L3
- **Trusted agent in familiar territory**: demote single-file refactors from L1 to L0
- **New agent or unfamiliar codebase area**: promote 3+ file changes from L2 to L3
