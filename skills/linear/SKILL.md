---
name: linear
description: Use when the repo's CONTEXT.md says tracker linear and you need to read or update a ticket — opening an issue, filing one, resolving team/state/label IDs, moving status, or commenting. The Linear provider recipes; the backend-neutral policy is in the tracker skill.
---
# Linear

The **Linear provider recipes** for the tracker protocol. Policy — the operation set, the state names, filing and placement, holds, sync rules, the `none` degrade — lives in the **`tracker`** skill. Read that first; this file is only *how* each operation is performed against Linear's API.

Applies when `CONTEXT.md` says `tracker: linear`. The team key is `repo.linear`; the queue scope is `repo.project`.

**You already have access — it is one `curl` away.** Linear's GraphQL API is the same for everyone; the only repo-specific part is the token (in an env file). The workspace identifiers you need are **resolved at runtime** from the API — a state by its stable `type`, a team by its key — so no per-repo ID setup is required (see [Resolving states by type](#resolving-states-by-type-the-default)). Do not conclude you lack access or that a tool is missing. If a repo ships a wrapper CLI, `CONTEXT.md` (`tools.linear_cli`) names it, but the curl below always works.

## Labels

Keep the taxonomy flat and small. The hold labels and what they mean are the `tracker` skill's; this is the Linear-side shape:

| Group | Labels | Rule |
|---|---|---|
| Type | `Feature`, `Bug`, `Improvement` | One per issue. Feature = new capability; bug = broken; improvement = tweak or internal work. |
| Stack | repo-defined (e.g. `frontend`, `backend`) | One or more. Routes to the matching builder; both = fullstack. |
| Source | `review-finding` | Applied when a steward files a finding (`assess`). A steward's *insight* is an improvement and is never filed — it goes to the proposals ledger — so the `review-insight` label is retired vocabulary; leave any already applied, and do not apply it to new work. |
| Hold | `input`, `operator` | Why a human holds a ticket (`tracker` → Filing and placement). Both imply the ticket is **assigned** to that human. |
| Assurance | `assurance:trivial`, `assurance:simple`, `assurance:complex` | Exactly one, always — the lifecycle assurance the ticket was filed with. Which one is `spec-authoring` → *Choosing assurance*; this table only says the group exists and is mandatory. |

> **Case matters — match by group, not a hardcoded case.** The type labels are **workspace-level and capitalized** in the live workspace (`Feature` / `Bug` / `Improvement`); the source, stack, and hold labels are **team-scoped**. A lowercase `feature` lookup silently misses the capitalized workspace label — resolve a label by its group (and case-insensitively) rather than assuming a fixed spelling.

## Placement on create

`projectId` is **mandatory** — a project-less issue is invisible to the Build queue. And a new issue lands in the team's **default state, which is often not Todo**, so resolve the `unstarted` state by `type` and move it explicitly as its own step ([recipes below](#accessing-linear-graphql-via-curl)). This is Linear's form of the placement rule the `tracker` skill states for both backends.

## A merged PR auto-transitions every ticket it names

Linear's GitHub integration links an issue to a PR when the ticket id appears in the PR **branch**, **title**, **body**, or a **commit** message, and moves it to **Done** automatically on merge. This is integration behaviour, not a lifecycle step: `/ship` transitions state on purpose; the integration does it on sight of an id. The deliberate-linking rule is `tracker` sync rule 6.

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

**Pull the held pile** — the set `/decision` drains. Both conditions, and the fields a triage read needs; add a `project` clause to the same filter, matching on the name `repo.project` gives, when that scope is set:
```bash
LINEAR 'query { issues(filter: { team: { key: { eq: \"<team-key>\" } }, labels: { name: { eq: \"input\" } }, assignee: { isMe: { eq: true } } }) { nodes { identifier title url description updatedAt } } }'
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

**Create an issue** (returns its identifier + url). `projectId` is **mandatory** — a project-less issue is invisible to the Build queue ([Placement on create](#placement-on-create)). `assigneeId` holds the ticket for a human (set it when filing held/deferred work). `parentId` is optional — omit it for a top-level issue, set it to the parent's id to create a sub-issue (e.g. a deferred-finding follow-up):
```bash
LINEAR 'mutation { issueCreate(input: { teamId: \"<team-uuid>\", projectId: \"<project-uuid>\", title: \"...\", description: \"...\", labelIds: [\"<label-uuid>\"], assigneeId: \"<user-uuid>\", parentId: \"<parent-id>\" }) { issue { identifier url } } }'
```

`labelIds` **must** include the resolved id of the `assurance:<level>` label the filer chose. Resolve it at runtime from the `issueLabels` query above, the same way as every other label id. An id that does not resolve — the workspace has no such label, or the mutation reports fewer labels than were passed — is an **incomplete filing**, not a filing without the label: report the identifier and URL, say so, and stop. Read the created issue's labels back before reporting; the mutation's `success` field says the call ran, not that the postcondition holds.

Resolve `projectId` at runtime by the name in `CONTEXT.md` → `repo.project`, and `assigneeId` for the current operator via `viewer` (the same runtime-resolution rule as team/state/label IDs — no per-repo UUID setup):
```bash
LINEAR 'query { projects(filter: { name: { eq: \"<repo.project>\" } }) { nodes { id name } } }'
LINEAR 'query { viewer { id name } }'
```

**Comment** (PR links, blocker notes):
```bash
LINEAR 'mutation { commentCreate(input: { issueId: \"<issue-id>\", body: \"...\" }) { success } }'
```

State, team, and label IDs are **resolved at runtime** from the queries above — the same call for every Linear workspace, no per-repo setup. `CONTEXT.md` carries an ID only as an *override* for a custom or renamed state the `type` enum cannot disambiguate; it is not where the standard states live.
