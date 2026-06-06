<!-- guidance:linear-sync@0.1.3 -->
# Linear Sync

The protocol for keeping Linear and the in-flight work in step. Linear is the standard issue tracker across these repos: **there is no separate `manifest.yaml`** — Linear is the queue of in-flight work, and the change spec for a task lives in its Linear issue. The repo-specific parts — the access command, the workspace/team IDs, the label IDs — live in `CONTEXT.md`, never here. This skill is the *protocol*; `CONTEXT.md` is the *invocation*.

(The rare repo not on Linear sets `linear: false` in `CONTEXT.md` and documents its local fallback there. Everything below assumes the standard: Linear is on.)

## The two-way contract

**Linear is intake; the in-flight spec is execution.** Work flows Linear → in-flight at pull time. Status flows in-flight → Linear as the pipeline progresses. The change spec is written into the Linear issue (its description, or a comment), not into a separate file.

## Status lifecycle

Linear holds the durable lifecycle. Map pipeline events to states:

| Pipeline event | Linear state |
|---|---|
| Ingested, work begins | → In Progress |
| Building, reviewing | In Progress (no change) |
| Handed to reviewer | → In Review |
| Shipped / merged | → Done |
| Blocked on missing info | → Backlog (with a comment naming the questions) |
| Review failed | stay In Review (with a comment listing blockers) |

Only Todo issues are pulled into work. Backlog issues wait for an answer.

## Labels

Keep the taxonomy flat and small. The shape (the actual IDs are in `CONTEXT.md`):

| Group | Labels | Rule |
|---|---|---|
| Type | `feature`, `bug`, `improvement` | One per issue. Feature = new capability; bug = broken; improvement = tweak or internal work. |
| Stack | repo-defined (e.g. `frontend`, `backend`) | One or more. Routes to the matching builder; both = fullstack. |
| Source | `review-finding`, `review-insight` | Applied when a steward files an issue (`assess`). |

## Sync rules

1. **The Linear issue is the front door.** Open it before starting. If work was described in chat, create the issue first.
2. **Never delete an issue.** Cancel it (move to Canceled); do not delete.
3. **Comment, don't clutter.** Post PR links and blocker notes as comments. Do not rewrite the description after intake (beyond adding the change spec).
4. **Blocked → Backlog with the question.** Park with the specific question stated, so it can be answered async.
5. **Don't probe the CLI for usage.** The first positional arg to a create command is usually the title — `create --help` can file an issue titled "--help". Read the invocation in `CONTEXT.md`; do not guess at the tool.

## Invocation

Every Linear operation uses the command in `CONTEXT.md` (`tools.linear_cli`). **Source the env file named in `CONTEXT.md` (`env.file`) first** — it holds `LINEAR_API_KEY` (`env.linear_token`). The file name varies by repo; the variable name does not. Never echo or commit the token, and the env file must be gitignored. If `CONTEXT.md` says access is via raw GraphQL/curl, use that; do not search for a `linear` binary or assume an MCP tool exists unless `CONTEXT.md` says so.

If `env.file` is unset or the token is missing, stop and ask — do not guess a filename or proceed without credentials.
