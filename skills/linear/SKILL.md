---
name: linear
description: Use when reading or updating Linear — opening a ticket, pulling the queue, setting status, commenting, or resolving a workflow state. Load for any issue-tracker operation; Linear is the queue of in-flight work.
---
<!-- guidance:linear@0.4.0 -->
# Linear

The protocol *and* the commands for keeping Linear and the in-flight work in step — and the **single home** for Linear operations: a command references this skill, it does not re-encode the GraphQL. Linear is the standard issue tracker across these repos: **there is no separate `manifest.yaml`** — Linear is the queue of in-flight work, and the change spec for a task lives in its Linear issue.

**You already have access — it is one `curl` away.** Linear's GraphQL API is the same for everyone; the only repo-specific part is the token (in an env file). Workspace state IDs need no setup: resolve them at runtime by their stable `type` (see [Resolving a workflow state](#resolving-a-workflow-state)). Do not conclude you lack access or that a tool is missing. The recipes are in [Accessing Linear](#accessing-linear-graphql-via-curl) below; if a repo ships a wrapper CLI, `CONTEXT.md` (`tools.linear_cli`) names it, but the curl below always works.

(The rare repo not on Linear sets `linear: false` in `CONTEXT.md` and documents its local fallback there. Everything below assumes the standard: Linear is on.)

## The two-way contract

**Linear is intake; the in-flight spec is execution.** Work flows Linear → in-flight at pull time. Status flows in-flight → Linear as the pipeline progresses. The change spec is written into the Linear issue (its description, or a comment), not into a separate file.

## Status lifecycle

Linear holds the durable lifecycle. Map pipeline events to states — each state names its stable `type` (the enum you resolve by; see [Resolving a workflow state](#resolving-a-workflow-state)):

| Pipeline event | Linear state | `type` |
|---|---|---|
| Ingested, work begins | → In Progress | `started` |
| Building, reviewing | In Progress (no change) | `started` |
| Handed to reviewer | → In Review | `started` |
| Shipped / merged | → Done | `completed` |
| Blocked on missing info | → Backlog (with a comment naming the questions) | `backlog` |
| Review failed | stay In Review (with a comment listing blockers) | `started` |

Only Todo (`unstarted`) issues are pulled into work. Backlog issues wait for an answer. **In Progress** and **In Review** share the `started` type — disambiguate them **by name**.

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

## Accessing Linear (GraphQL via curl)

**Get the token.** Look for an env file holding `LINEAR_API_KEY`: the one named in `CONTEXT.md` (`env.file`), else `.env` / `.env.local` in the repo root. Source it (`set -a && source .env && set +a`). Never echo or commit the token; the env file must be gitignored.

**If no `LINEAR_API_KEY` is found in any env file, that is the only blocker — stop and ask the user for one.** Do not conclude you lack access before checking the env files. (If `CONTEXT.md` defines `tools.linear_cli`, you may use that wrapper instead; the curls below are the universal fallback and always work.)

Every call posts to the same endpoint with the token in the `Authorization` header:

```bash
LINEAR() { curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d "{\"query\":\"$1\"}"; }
```

**Read an issue** (brief, description, labels, state):
```bash
LINEAR 'query { issue(id:\"<issue-id>\") { identifier title description url state { name } labels { nodes { name } } } }'
```

**Pull the Todo queue** for a team (the work to pick up):
```bash
LINEAR 'query { issues(filter: { team: { key: { eq: \"<team-key>\" } }, state: { name: { eq: \"Todo\" } } }) { nodes { identifier title } } }'
```

### Resolving a workflow state

**State IDs are per-team UUIDs — not portable across repos, and not required up front.** Resolve a state at runtime by its stable `type` (`unstarted` / `started` / `completed` / `canceled` — plus `backlog` / `triage` where a team uses them), which is identical in every Linear workspace. Query the team's states *with* their `type`, then pick the one you need:

```bash
LINEAR 'query { workflowStates(filter: { team: { key: { eq: \"<team-key>\" } } }) { nodes { id name type } } }'
```

- Todo is `unstarted`; Done is `completed`; Backlog is `backlog`; Canceled is `canceled`.
- **In Progress** and **In Review** both carry `type: started` — disambiguate them **by name**.

Pick the `id` whose `type` (and, for the two `started` states, `name`) matches the target, then move the issue:

```bash
LINEAR 'mutation { issueUpdate(id: \"<issue-id>\", input: { stateId: \"<resolved-state-id>\" }) { success } }'
```

**Override — the exception, not the default.** A repo that has *renamed* states or added custom ones whose name/type is ambiguous may cache the resolved state UUIDs in `CONTEXT.md` to pin them. The default path needs no such cache: type-based resolution works from a clean checkout, so setup is never mandatory. Team and label IDs are likewise discoverable on demand:

```bash
LINEAR 'query { teams { nodes { id key name } } }'
LINEAR 'query { issueLabels { nodes { id name } } }'
```

**Create an issue** (returns its identifier + url):
```bash
LINEAR 'mutation { issueCreate(input: { teamId: \"<team-uuid>\", title: \"...\", description: \"...\", labelIds: [\"<label-uuid>\"] }) { issue { identifier url } } }'
```

**Comment** (PR links, blocker notes):
```bash
LINEAR 'mutation { commentCreate(input: { issueId: \"<issue-id>\", body: \"...\" }) { success } }'
```

The query shapes above are the same for every Linear workspace — they carry no repo-specific IDs. Resolve workspace IDs at runtime (states by `type`, team and labels by name); only the token is repo-specific, and cached UUIDs in `CONTEXT.md` are the override for renamed/custom states, not a setup step.
