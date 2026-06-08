---
name: linear-sync
description: Use when reading or updating Linear — opening a ticket, pulling the queue, setting status, commenting, or discovering team/state/label IDs. Load for any issue-tracker operation; Linear is the queue of in-flight work.
---
<!-- guidance:linear-sync@0.3.0 -->
# Linear Sync

The protocol *and* the commands for keeping Linear and the in-flight work in step. Linear is the standard issue tracker across these repos: **there is no separate `manifest.yaml`** — Linear is the queue of in-flight work, and the change spec for a task lives in its Linear issue.

**You already have access — it is one `curl` away.** Linear's GraphQL API is the same for everyone; the only repo-specific parts are the token (in an env file) and the workspace IDs (in `CONTEXT.md`). Do not conclude you lack access or that a tool is missing. The recipes are in [Accessing Linear](#accessing-linear-graphql-via-curl) below; if a repo ships a wrapper CLI, `CONTEXT.md` (`tools.linear_cli`) names it, but the curl below always works.

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

**Discover the workspace IDs you need once, then cache them in `CONTEXT.md`** (team id, workflow-state ids for status changes, label ids):
```bash
LINEAR 'query { teams { nodes { id key name } } }'
LINEAR 'query { workflowStates(filter: { team: { key: { eq: \"<team-key>\" } } }) { nodes { id name } } }'
LINEAR 'query { issueLabels { nodes { id name } } }'
```

**Move an issue's status** (use the state id from the query above; the issue id may be the `<issue-id>` identifier):
```bash
LINEAR 'mutation { issueUpdate(id: \"<issue-id>\", input: { stateId: \"<state-uuid>\" }) { success } }'
```

**Create an issue** (returns its identifier + url):
```bash
LINEAR 'mutation { issueCreate(input: { teamId: \"<team-uuid>\", title: \"...\", description: \"...\", labelIds: [\"<label-uuid>\"] }) { issue { identifier url } } }'
```

**Comment** (PR links, blocker notes):
```bash
LINEAR 'mutation { commentCreate(input: { issueId: \"<issue-id>\", body: \"...\" }) { success } }'
```

The workspace-specific ids (team, states, labels) belong in `CONTEXT.md` so you do not re-discover them each run. The query shapes above do not — they are the same for every Linear workspace.
