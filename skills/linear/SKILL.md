---
name: linear
description: Use when reading or updating Linear — opening a ticket, pulling the queue, setting status, commenting, or resolving team/state/label IDs. Load for any issue-tracker operation; Linear is the queue of in-flight work. This is the single home for Linear operations — a command references this skill, it does not re-encode the API.
---
<!-- guidance:linear@0.4.2 -->
# Linear

The protocol *and* the commands for keeping Linear and the in-flight work in step. Linear is the standard issue tracker across these repos: **there is no separate `manifest.yaml`** — Linear is the queue of in-flight work, and the change spec for a task lives in its Linear issue. This skill is the **one home** for Linear operations: a command or agent that touches Linear references this skill rather than re-encoding `api.linear.app` calls — a guard fails if raw Linear GraphQL appears in a command.

**You already have access — it is one `curl` away.** Linear's GraphQL API is the same for everyone; the only repo-specific part is the token (in an env file). The workspace identifiers you need are **resolved at runtime** from the API — a state by its stable `type`, a team by its key — so no per-repo ID setup is required (see [Resolving states by type](#resolving-states-by-type-the-default)). Do not conclude you lack access or that a tool is missing. The recipes are in [Accessing Linear](#accessing-linear-graphql-via-curl) below; if a repo ships a wrapper CLI, `CONTEXT.md` (`tools.linear_cli`) names it, but the curl below always works.

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
6. **A merged PR auto-transitions every ticket it names — link deliberately.** Linear's GitHub integration links an issue to a PR when the ticket id appears in the PR **branch**, **title**, **body**, or a **commit** message, and moves it to **Done** automatically on merge. So put a ticket id in those surfaces only when the PR actually *completes* that ticket. A PR that merely **spawns** or references tickets it is not finishing — a proposal-acceptance PR listing its breakdown, a doc PR mentioning related work — must keep those ids out of the branch / title / body / commit (name them in prose without the bare id, or omit them), or merging it falsely closes the tickets it just created. This is integration behaviour, not a harness verb: the audited verbs transition state on purpose; the integration does it on sight of an id.

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

### Resolving states by type (the default)

Workflow-state IDs are **per-team UUIDs** — not portable across repos or trackers, and they change if a team renames a state. So resolve a state at runtime by its stable `type` enum; never hard-code the UUID. Every Linear workspace has the same four state types:

| `type` | The state(s) |
|---|---|
| `unstarted` | Todo |
| `started` | In Progress **or** In Review — two states share this `type` |
| `completed` | Done |
| `canceled` | Canceled (and Duplicate) |

Query the team's states *with* their `type`, then pick the one you need. For the two `started` states, **disambiguate by name** (In Progress vs In Review):

```bash
LINEAR 'query { workflowStates(filter: { team: { key: { eq: \"<team-key>\" } } }) { nodes { id name type } } }'
```

From that result: `unstarted` is the Todo column, `completed` is Done, `canceled` is the cancel state, and the two `started` states are In Progress and In Review — match the one you want by `name`. This is the same call for every workspace; nothing is cached. Resolve team and label IDs (for `issueCreate`) at runtime the same way:

```bash
LINEAR 'query { teams { nodes { id key name } } }'
LINEAR 'query { issueLabels { nodes { id name } } }'
```

**CONTEXT override (the exception, not the default).** If a repo has *custom or renamed* states that `type` + name cannot disambiguate, cache those specific state UUIDs in `CONTEXT.md` and use them directly. That override is for the unusual case — the type-based resolution above is the standard path and needs no per-repo setup.

**Move an issue's status** (resolve `<state-id>` by `type` per above; the issue id may be the `<issue-id>` identifier):
```bash
LINEAR 'mutation { issueUpdate(id: \"<issue-id>\", input: { stateId: \"<state-id>\" }) { success } }'
```

**Create an issue** (returns its identifier + url). `parentId` is optional — omit it for a top-level issue, set it to the parent's id to create a sub-issue (e.g. a deferred-finding follow-up):
```bash
LINEAR 'mutation { issueCreate(input: { teamId: \"<team-uuid>\", title: \"...\", description: \"...\", labelIds: [\"<label-uuid>\"], parentId: \"<parent-id>\" }) { issue { identifier url } } }'
```

**Comment** (PR links, blocker notes):
```bash
LINEAR 'mutation { commentCreate(input: { issueId: \"<issue-id>\", body: \"...\" }) { success } }'
```

State, team, and label IDs are **resolved at runtime** from the queries above — the same call for every Linear workspace, no per-repo setup. `CONTEXT.md` carries an ID only as an *override* for a custom or renamed state the `type` enum cannot disambiguate; it is not where the standard states live.
