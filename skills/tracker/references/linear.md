# The Linear transport

**Load this when `harness.yaml` says `tracker: linear`.** The semantics — what each operation must achieve, what makes a filing incomplete, the hold contract, the ledger — are `tracker`'s `SKILL.md`, already loaded. This file is only *how* each operation is performed against Linear's API.

The queue scope is `repo.project`. The team is resolved at runtime and read from no configuration key — see [Resolving the team](#resolving-the-team) below.

**You already have access — it is one `curl` away.** Linear's GraphQL API is the same for everyone; the only repo-specific part is the token (in an env file). The workspace identifiers you need are **resolved at runtime** from the API — a state by its stable `type`, a team by its key — so no per-repo ID setup is required (see [Resolving states by type](#resolving-states-by-type-the-default)). Do not conclude you lack access or that a tool is missing. If a repo ships a wrapper CLI, `harness.yaml` (`tools.linear_cli`) names it, but the curl below always works.

## Labels

Keep the taxonomy flat and small. The hold labels and what they mean are the spine's contract; this is the Linear-side shape:

| Group | Labels | Rule |
|---|---|---|
| Type | `Feature`, `Bug`, `Improvement` | One per issue. Feature = new capability; bug = broken; improvement = tweak or internal work. |
| Stack | repo-defined (e.g. `frontend`, `backend`) | One or more. Routes to the matching builder; both = fullstack. |
| Source | `review-finding` | Applied when a steward files a finding (`assess`). A steward's *insight* is an improvement and is never filed — it goes to the improvement ledger — so the `review-insight` label is retired vocabulary; leave any already applied, and do not apply it to new work. |
| Hold | `input`, `operator` | Why a human holds a ticket (`tracker` → Filing and placement). Both imply the ticket is **assigned** to that human. |
| Assurance | `assurance:trivial`, `assurance:simple`, `assurance:complex` | Exactly one, always — the lifecycle assurance the ticket was filed with. Which one is `authoring` → *Choosing assurance*; this table only says the group exists and is mandatory. |

> **Case matters — match by group, not a hardcoded case.** The type labels are **workspace-level and capitalized** in the live workspace (`Feature` / `Bug` / `Improvement`); the source, stack, and hold labels are **team-scoped**. A lowercase `feature` lookup silently misses the capitalized workspace label — resolve a label by its group (and case-insensitively) rather than assuming a fixed spelling.

## Placement on create

`projectId` is **mandatory** — a project-less issue is invisible to the Build queue. And a new issue lands in the team's **default state, which is often neither Todo nor Backlog**, so resolve the target state by `type` — `unstarted` for Todo, `backlog` for Backlog — and move it explicitly as its own step ([recipes below](#accessing-linear-graphql-via-curl)). This is Linear's form of the spine contract's placement rule (*Filing*).

## A merged PR auto-transitions every ticket it names

Linear's GitHub integration links an issue to a PR when the ticket id appears in the PR **branch**, **title**, **body**, or a **commit** message, and moves it to **Done** automatically on merge. This is integration behaviour, not a lifecycle step: the landing stage transitions state on purpose; the integration does it on sight of an id. The deliberate-linking rule is in *Shared rules* below.

## Accessing Linear (GraphQL via curl)

**Get the token.** Look for an env file holding `LINEAR_API_KEY`: the one named in `harness.yaml` (`env.file`), else `.env` / `.env.local` in the repo root. Source it (`set -a && source .env && set +a`). Never echo or commit the token; the env file must be gitignored.

**If no `LINEAR_API_KEY` is found in any env file, that is the only blocker — stop and ask the user for one.** Do not conclude you lack access before checking the env files. (If `harness.yaml` defines `tools.linear_cli`, you may use that wrapper instead; the curls below are the universal fallback and always work.)

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

**Pull the held pile.** Both conditions — the hold label and the operator's own assignment — and the fields a triage read needs; add a `project` clause to the same filter, matching on the name `repo.project` gives, when that scope is set:
```bash
LINEAR 'query { issues(filter: { team: { key: { eq: \"<team-key>\" } }, labels: { name: { eq: \"input\" } }, assignee: { isMe: { eq: true } } }) { nodes { identifier title url description updatedAt } } }'
```

### Resolving the team

The API token is **workspace-scoped**, so nothing needs to say which workspace this is, and the team follows from the workspace rather than from a declaration:

```bash
LINEAR 'query { teams { nodes { id key name } } }'
```

**Exactly one node is the team.** Use its `key` wherever a recipe below writes `<team-key>` and its `id` wherever one writes `<team-uuid>`. No configuration field is read for it: `repo.linear` held a workspace hostname in one repo and was absent in another, so a recipe reading it returned an empty queue on both — which only an unattended discovery run would ever have noticed. That key is retired from this recipe's read set; a repo keeping it as a human-facing pointer to its workspace URL is unaffected and it is reported as an ordinary unread key.

**More than one node is genuinely ambiguous — report and hold.** Nothing here can say which team this repo's queue lives in. The escape hatch is the same override the states use: declare the team key in `harness.yaml` as `tracker_address.team`, and this recipe reads that key **only** in the ambiguous case, exactly as a cached state UUID is read only where `type` and name cannot disambiguate. Never guess by name, position or issue count.

### Resolving states by type (the default)

Workflow-state IDs are **per-team UUIDs** — not portable across repos or trackers, and they change if a team renames a state. So resolve a state at runtime by its stable `type` enum; never hard-code the UUID. These are the types the recipes in this file resolve:

| `type` | The state(s) |
|---|---|
| `backlog` | Backlog |
| `unstarted` | Todo |
| `started` | In Progress **or** In Review — two states share this `type` |
| `completed` | Done |
| `canceled` | Canceled (and Duplicate) |

Query the team's states *with* their `type`, then pick the one you need. For the two `started` states, **disambiguate by name** (In Progress vs In Review):

```bash
LINEAR 'query { workflowStates(filter: { team: { key: { eq: \"<team-key>\" } } }) { nodes { id name type } } }'
```

From that result: `backlog` is the Backlog column, `unstarted` is the Todo column, `completed` is Done, `canceled` is the cancel state, and the two `started` states are In Progress and In Review — match the one you want by `name`. This is the same call for every workspace; nothing is cached. Resolve team and label IDs (for `issueCreate`) at runtime the same way:

```bash
LINEAR 'query { teams { nodes { id key name } } }'
LINEAR 'query { issueLabels { nodes { id name } } }'
```

**CONTEXT override (the exception, not the default).** If a repo has *custom or renamed* states that `type` + name cannot disambiguate, cache those specific state UUIDs in `harness.yaml` and use them directly. That override is for the unusual case — the type-based resolution above is the standard path and needs no per-repo setup.

**Move an issue's status** (resolve `<state-id>` by `type` per above; the issue id may be the `<issue-id>` identifier):
```bash
LINEAR 'mutation { issueUpdate(id: \"<issue-id>\", input: { stateId: \"<state-id>\" }) { success } }'
```

**Create an issue** (returns its identifier + url). `projectId` is **mandatory** — a project-less issue is invisible to the Build queue ([Placement on create](#placement-on-create)). `assigneeId` holds the ticket for a human (set it when filing held/deferred work). `parentId` is optional — omit it for a top-level issue, set it to the parent's id to create a sub-issue (e.g. a deferred-finding follow-up):
```bash
LINEAR 'mutation { issueCreate(input: { teamId: \"<team-uuid>\", projectId: \"<project-uuid>\", title: \"...\", description: \"...\", labelIds: [\"<label-uuid>\"], assigneeId: \"<user-uuid>\", parentId: \"<parent-id>\" }) { issue { identifier url } } }'
```

`labelIds` **must** include the resolved id of the `assurance:<level>` label the filer chose. Resolve it at runtime from the `issueLabels` query above, the same way as every other label id. An id that does not resolve — the workspace has no such label, or the mutation reports fewer labels than were passed — is an **incomplete filing**, not a filing without the label: report the identifier and URL, say so, and stop.

**Read both halves of the filing back before reporting it.** The `issueCreate` above passes no `stateId`, so the issue lands in the team's default state and its placement is the separate `issueUpdate` at *Move an issue's status* — a second write whose `success` field says the call ran, not that the postcondition holds. Reading the labels alone leaves that write unconfirmed, so a ticket created but never placed reports as filed and a Todo-scoped queue read never sees it. Read the state alongside the labels:

```bash
LINEAR 'query { issue(id: \"<issue-id>\") { identifier url state { id name type } labels { nodes { id name } } } }'
```

The filing is complete when the labels carry exactly one `assurance:<level>` and the returned `state.id` is the id the placement `issueUpdate` set. **Compare the id, not the state's name:** the state was resolved by `type` ([Resolving states by type](#resolving-states-by-type-the-default)) and a workspace may rename its columns, so matching on a name resolves the state a second time instead of confirming the write.

**Where that read cannot run, the filing is incomplete** — report the identifier, the URL and the operation that could not run, and stop. Never report a ticket placed on the strength of the issue having been created. One branch covers it here, where the GitHub board needs two: both writes and this read go through the one GraphQL endpoint, so a transport that answers answers for both halves of the filing, and one that does not leaves neither confirmable.

Resolve `projectId` at runtime by the name in `harness.yaml` → `repo.project`, and `assigneeId` for the current operator via `viewer` (the same runtime-resolution rule as team/state/label IDs — no per-repo UUID setup):
```bash
LINEAR 'query { projects(filter: { name: { eq: \"<repo.project>\" } }) { nodes { id name } } }'
LINEAR 'query { viewer { id name } }'
```

**Comment** (PR links, blocker notes):
```bash
LINEAR 'mutation { commentCreate(input: { issueId: \"<issue-id>\", body: \"...\" }) { success } }'
```

**Hold** — comment, label, assign; three writes, per `tracker` → *`hold`*. Use `issueAddLabel`, which adds one label without touching the rest: a bare `labelIds` on `issueUpdate` **replaces** the whole set and drops the `assurance:` label with it.
```bash
LINEAR 'mutation { commentCreate(input: { issueId: \"<issue-id>\", body: \"...\" }) { success } }'
LINEAR 'mutation { issueAddLabel(id: \"<issue-id>\", labelId: \"<hold-label-uuid>\") { success } }'
LINEAR 'mutation { issueUpdate(id: \"<issue-id>\", input: { assigneeId: \"<user-uuid>\" }) { success } }'
```

Read all three back before reporting the hold; `success` says only that the call ran:
```bash
LINEAR 'query { issue(id: \"<issue-id>\") { assignee { id } labels { nodes { name } } comments { nodes { id } } } }'
```

State, team, and label IDs are **resolved at runtime** from the queries above — the same call for every Linear workspace, no per-repo setup. `harness.yaml` carries an ID as an *override* in exactly two cases, each named where it applies above: a custom or renamed state the `type` enum cannot disambiguate, and a team key for the ambiguous-workspace case (`tracker_address.team`, [Resolving the team](#resolving-the-team)); it is not where the standard states or the unambiguous team live.

## Relations — blocked-by

Linear models dependencies as **issue relations**, so `blocks` / `blockedBy` is
one mutation and needs no board:

```bash
LINEAR 'mutation { issueRelationCreate(input: { issueId: \"<blocked-id>\", relatedIssueId: \"<blocker-id>\", type: blocks }) { success } }'
LINEAR 'query { issue(id:\"<issue-id>\") { relations { nodes { type relatedIssue { identifier state { type } } } } inverseRelations { nodes { type issue { identifier state { type } } } } } }'
```

Read **both** `relations` and `inverseRelations`: Linear stores one edge and
reports it from each side under a different key, so a reader that consults only
one silently sees an unblocked ticket.

## Priority

`priority` is a native integer field on the issue — `1` is Urgent, and that is
the andon cord's P1. Set it in the same `issueCreate` input, or afterwards:

```bash
LINEAR 'mutation { issueUpdate(id: \"<issue-id>\", input: { priority: 1 }) { success } }'
LINEAR 'query { issues(filter: { priority: { eq: 1 }, state: { type: { neq: \"completed\" } } }) { nodes { identifier title labels { nodes { name } } } } }'
```

## `ledger`

The append is three operations this file already has: a label-scoped issue query
to find the standing issue, `issueCreate` to open it once, `commentCreate` to
append. Find it by the `improvement-ledger` label; when that search is empty,
search the pre-#547 `proposals-ledger` label and migrate the hit
(`issueUpdate` with the resolved new label id, and the old one dropped) rather
than opening a second ledger.

```bash
LINEAR 'query { issues(filter: { labels: { name: { eq: \"improvement-ledger\" } }, state: { type: { neq: \"completed\" } } }) { nodes { id identifier title url } } }'
```
