# The Linear transport

**Load this when `harness.yaml` says `tracker: linear`.** The semantics — what each operation must achieve, what makes a filing incomplete, the hold contract, the ledger — are `tracker`'s `SKILL.md`, already loaded. This file is only *how* each operation is performed against Linear's API.

The queue scope is `repo.project`. The team is resolved at runtime and read from no configuration key — see [Resolving the team](#resolving-the-team) below.

**Access is one `curl` away.** Linear's GraphQL API is the same for everyone; the only repo-specific part is the credential: a key in the environment or an env file, or one the host holds for the run. The workspace identifiers you need are **resolved at runtime** from the API — a state by its stable `type`, a team by its key — so no per-repo ID setup is required (see [Resolving states by type](#resolving-states-by-type-the-default)). Do not conclude you lack access or that a tool is missing until the probe in [Accessing Linear](#accessing-linear-graphql-via-curl) has answered. If a repo ships a wrapper CLI, `harness.yaml` (`tools.linear_cli`) names it, but the curl below is the universal fallback.

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

## A breakdown files under one umbrella issue

An accepted proposal spawns several tickets that share one decision, and on a flat board nothing says so. Linear models the grouping natively — `parentId` on `issueCreate` ([Create an issue](#accessing-linear-graphql-via-curl)) — so a breakdown files **one umbrella issue and every ticket as its sub-issue**. The board then shows what goes together without anyone opening the proposal spec, and the umbrella is a standing place to audit the initiative against what the proposal decided, which a set of closed siblings does not give anybody.

The umbrella is a container. Nothing builds it, and it carries no change spec: reaching for `templates/change.md` here writes acceptance criteria for work that lives in the children.

| What it carries | Value | Why |
|---|---|---|
| Title | the proposal's own title | It names an initiative rather than a change, so the *verb + where* convention does not reach it |
| Description | the problem in brief, the recommendation, a link to the proposal spec, and the breakdown list | What an auditor needs in order to judge the children against the decision |
| `projectId` | the children's project | Mandatory on this backend (*Placement on create* above), and it is the initiative's own queue |
| Label | `operator` | Says why a human holds it: this one is never built |
| `assigneeId` | the operator | **The half the loop acts on.** `work-discovery` skips a ticket because it is *assigned*, and reads the label only for why — so an umbrella carrying the label alone sits in Todo until an unattended tick takes a container it cannot build |
| Assurance | `assurance:trivial` | The spine's *Filing* contract requires exactly one on every created ticket, and no lane describes a ticket nobody builds. The cheapest lane is the honest placeholder |
| State | Todo | Placement is mandatory and a held ticket is excluded from the queue count, so Todo costs no slot. It sits beside the children it groups, where Backlog would claim it is waiting to be pulled |

**This is not a `hold`.** That operation is three writes including a question for the operator, and nothing is being asked here. What the umbrella borrows is the label-and-assignment shape the standing ledger issue already uses as a never-built-directly marker (`tracker` → *`ledger`*).

**The operator closes it**, whenever the audit is done. Nothing rolls up, checks completeness, or closes it on the last child.

Each child then passes `parentId` on its own `issueCreate`. Placement, dependencies, priority and assurance are unchanged: the first `wip_limit` children into Todo, the rest into Backlog.

**Keep the umbrella's id off a PR.** An id in a branch, title, body or commit auto-transitions that issue to Done on merge (*A merged PR auto-transitions every ticket it names* below), and a child's PR that names its parent closes the audit point while the initiative is still running.

## A merged PR auto-transitions every ticket it names

Linear's GitHub integration links an issue to a PR when the ticket id appears in the PR **branch**, **title**, **body**, or a **commit** message, and moves it to **Done** automatically on merge. This is integration behaviour, not a lifecycle step: the landing stage transitions state on purpose; the integration does it on sight of an id. The deliberate-linking rule is in *Shared rules* below.

## Accessing Linear (GraphQL via curl)

**Every call is one literal `curl`, and on the two paths a rule can approve, every call starts with the same words:**

```bash
curl -sS -X POST https://api.linear.app/graphql
```

So one rule approves them all: `Bash(curl -sS -X POST https://api.linear.app/graphql *)`, in the consuming repo's own `.claude/settings.json`. That file is the only settings file a cloud session reads, and nothing installs the rule for the repo. The host refuses two shapes before it consults any rule: a shell function wrapping the call, and a shell variable expanded on the command line (#747 measured both). No recipe here does either, outside the one path below that cannot avoid it.

**Choose the path by probing, never by looking at the key.** Three paths reach Linear. Probe them in this order with `query { viewer { id } }`, and use the first one that answers for every call in the run:

1. **The host holds the credential.** The host adds `Authorization` as the request leaves (Claude Code's cloud-environment API credentials work this way), so the call sends none:

   ```bash
   curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { viewer { id } }"}'
   ```

2. **The key is in the environment**, set by an injecting host or a CI secret. curl reads `LINEAR_API_KEY` itself, so the command line expands nothing:

   ```bash
   curl -sS -X POST https://api.linear.app/graphql --variable %LINEAR_API_KEY --expand-header 'Authorization: {{LINEAR_API_KEY}}' -H 'Content-Type: application/json' -d '{"query":"query { viewer { id } }"}'
   ```

   Where the variable is unset, curl stops with "variable expansion failure" and sends nothing. That is this path's failed probe, and it settles whether the variable is set without printing it. `--variable` needs curl 8.3 or later.

3. **The key is in the env file**: the one named in `harness.yaml` (`env.file`), else `.env` / `.env.local` in the repo root. A shell variable does not survive from one tool call to the next where the host keeps no shell state, as Claude Code's Bash tool does not, so every call on this path reads the file in the same command:

   ```bash
   LINEAR_API_KEY=$(sed -n 's/^[[:space:]]*LINEAR_API_KEY=//p' "<env-file>" | head -n1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/") curl -sS -X POST https://api.linear.app/graphql --variable %LINEAR_API_KEY --expand-header 'Authorization: {{LINEAR_API_KEY}}' -H 'Content-Type: application/json' -d '{"query":"query { viewer { id } }"}'
   ```

   This path expands a variable, so no allow rule can approve it, and each call prompts wherever `Bash(*)` is not in effect, which includes auto mode. To leave it, put the key in the environment the host starts the session with, and the run takes path 2.

Never echo or commit the key; the env file must be gitignored. The read strips one layer of matching single or double quotes and keeps any `=` inside the value. An empty read is no key, never a token.

**Read the env file with `sed`, never `source` it.** Until #639 this step read `set -a && source .env && set +a`, and it caused two observed failures, each a property of `source` rather than of any particular file:

- **Sourcing destroys a working credential.** An env file is gitignored and seeded from a committed `.env.example`, so it routinely carries an empty `LINEAR_API_KEY=` placeholder. Where the host injects the real key, sourcing overwrites it with the empty string and Linear answers **401** on the first call. That failure is silent in the direction that costs most: an agent appending a ledger entry or posting a comment gets an error it may not read closely, and *"I recorded that"* is a claim the next reader has no reason to doubt. Two agents in one observed run reached opposite conclusions about whether a tracker write had landed. It also reaches the run's ticket **reads**, not only its writes.
- **Sourcing executes the file.** An unquoted value carrying a backtick, `$( )` or a redirect is run rather than assigned, on a gitignored file the agent did not write and no review saw. The `sed` above assigns text whatever the file holds: a value of `` `touch /tmp/x` `` comes back as those literal characters, and nothing runs.

Nothing here reads or prints a credential the host holds; path 1's probe is the only test that one exists.

**Access is a non-empty `data.viewer.id` in the response body, and nothing else.** Do not read the HTTP status: GraphQL reports an authentication failure as an `errors` array, sometimes under a 200. An `errors` array, an empty body, or a body that is not Linear's JSON is a failed probe.

**When every path's probe fails, stop and ask the operator, quoting what came back:** Linear's `errors[].message` as returned, or curl's own error where Linear never answered. That is the rule where you are the process the operator is talking to; a dispatched sub-agent reports and stops instead (`tracker` → *Shared rules*). Never fall back to a Linear connector or any other route to the workspace, and never read a failed read as an empty one: a queue read that failed returns no issues, and reads as a clear queue. The operator can supply a key, or give the host a credential for host `api.linear.app` in the `Authorization` header with **no prefix**: Linear takes a personal key bare, and a form that defaults to `Bearer` must be cleared. (If `harness.yaml` defines `tools.linear_cli`, you may use that wrapper instead; the curls below are the universal fallback.)

**The recipes below are written for path 1.** On path 2, put `--variable %LINEAR_API_KEY --expand-header 'Authorization: {{LINEAR_API_KEY}}'` after the URL. On path 3, also put the env-file read from path 3 in front of `curl`. A recipe that reads or writes only ids keeps its GraphQL document inside the single-quoted `-d` body, writing a string argument as `\"`. The `<placeholders>` are ids resolved at runtime, and none contains a quote, except `<repo.project>`, which is a project name: a name carrying a quote goes in a variables body file instead.

**A write that carries ticket text goes as a file.** That covers a title, a description and a comment body. Write a JSON object holding `query` and `variables` to a scratch file outside the tree with a file-writing tool, never a shell heredoc of the text, and send it with `-d @<file>`. The tool that wrote the file owns the JSON escaping, an apostrophe cannot end the shell argument, and the text never reaches the command line (`tracker` → *Shared rules*: quote titles, pass bodies as a file). For example, a comment:

```json
{"query": "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success comment { id } } }",
 "variables": {"input": {"issueId": "<issue-id>", "body": "<the comment text>"}}}
```

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d @<file>
```

**Read an issue** (brief, description, labels, state):
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issue(id:\"<issue-id>\") { identifier title description url state { name } labels { nodes { name } } comments { nodes { body createdAt } } } }"}'
```

**Pull the Todo queue** for a team (the work to pick up):
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issues(filter: { team: { key: { eq: \"<team-key>\" } }, state: { name: { eq: \"Todo\" } } }) { nodes { identifier title } } }"}'
```

**Pull the held pile.** Both conditions — the hold label and the operator's own assignment — and the fields a triage read needs; add a `project` clause to the same filter, matching on the name `repo.project` gives, when that scope is set:
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issues(filter: { team: { key: { eq: \"<team-key>\" } }, labels: { name: { eq: \"input\" } }, assignee: { isMe: { eq: true } } }) { nodes { identifier title url description updatedAt } } }"}'
```

### Resolving the team

The API token is **workspace-scoped**, so nothing needs to say which workspace this is, and the team follows from the workspace rather than from a declaration:

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { teams { nodes { id key name } } }"}'
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
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { workflowStates(filter: { team: { key: { eq: \"<team-key>\" } } }) { nodes { id name type } } }"}'
```

From that result: `backlog` is the Backlog column, `unstarted` is the Todo column, `completed` is Done, `canceled` is the cancel state, and the two `started` states are In Progress and In Review — match the one you want by `name`. This is the same call for every workspace; nothing is cached. Resolve team and label IDs (for `issueCreate`) at runtime the same way:

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { teams { nodes { id key name } } }"}'
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issueLabels { nodes { id name } } }"}'
```

**CONTEXT override (the exception, not the default).** If a repo has *custom or renamed* states that `type` + name cannot disambiguate, cache those specific state UUIDs in `harness.yaml` and use them directly. That override is for the unusual case — the type-based resolution above is the standard path and needs no per-repo setup.

**Move an issue's status** (resolve `<state-id>` by `type` per above; the issue id may be the `<issue-id>` identifier):
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"mutation { issueUpdate(id: \"<issue-id>\", input: { stateId: \"<state-id>\" }) { success } }"}'
```

**Create an issue** (returns its identifier + url). `projectId` is **mandatory** — a project-less issue is invisible to the Build queue ([Placement on create](#placement-on-create)). `assigneeId` holds the ticket for a human (set it when filing held/deferred work). `parentId` is optional — omit it for a top-level issue, set it to the parent's id to create a sub-issue — a deferred-finding follow-up, or every item of a breakdown under its umbrella ([A breakdown files under one umbrella issue](#a-breakdown-files-under-one-umbrella-issue)):

The title and description are ticket text, so the input travels as `variables` in a body file (*A write that carries ticket text goes as a file*, above):

```json
{"query": "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { issue { id identifier url } } }",
 "variables": {"input": {"teamId": "<team-uuid>", "projectId": "<project-uuid>", "title": "<title>", "description": "<description>",
   "labelIds": ["<label-uuid>"], "assigneeId": "<user-uuid>", "parentId": "<parent-id>"}}}
```

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d @<file>
```

`labelIds` **must** include the resolved id of the `assurance:<level>` label the filer chose. Resolve it at runtime from the `issueLabels` query above, the same way as every other label id. An id that does not resolve — the workspace has no such label, or the mutation reports fewer labels than were passed — is an **incomplete filing**, not a filing without the label: report the identifier and URL, say so, and stop.

**Read both halves of the filing back before reporting it.** The `issueCreate` above passes no `stateId`, so the issue lands in the team's default state and its placement is the separate `issueUpdate` at *Move an issue's status* — a second write whose `success` field says the call ran, not that the postcondition holds. Reading the labels alone leaves that write unconfirmed, so a ticket created but never placed reports as filed and a Todo-scoped queue read never sees it. Read the state alongside the labels:

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issue(id: \"<issue-id>\") { identifier url state { id name type } labels { nodes { id name } } } }"}'
```

The filing is complete when the labels carry exactly one `assurance:<level>` and the returned `state.id` is the id the placement `issueUpdate` set. **Compare the id, not the state's name:** the state was resolved by `type` ([Resolving states by type](#resolving-states-by-type-the-default)) and a workspace may rename its columns, so matching on a name resolves the state a second time instead of confirming the write.

**Where that read cannot run, the filing is incomplete** — report the identifier, the URL and the operation that could not run, and stop. Never report a ticket placed on the strength of the issue having been created. One branch covers it here, where the GitHub board needs two: both writes and this read go through the one GraphQL endpoint, so a transport that answers answers for both halves of the filing, and one that does not leaves neither confirmable.

Resolve `projectId` at runtime by the name in `harness.yaml` → `repo.project`, and `assigneeId` for the current operator via `viewer` (the same runtime-resolution rule as team/state/label IDs — no per-repo UUID setup):
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { projects(filter: { name: { eq: \"<repo.project>\" } }) { nodes { id name } } }"}'
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { viewer { id name } }"}'
```

**Comment** (PR links, blocker notes). The body is ticket text, so send the body file shown under *A write that carries ticket text goes as a file*:
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d @<file>
```

**Hold** — comment, label, assign; three writes, per `tracker` → *`hold`*. Use `issueAddLabel`, which adds one label without touching the rest: a bare `labelIds` on `issueUpdate` **replaces** the whole set and drops the `assurance:` label with it.
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d @<comment-file>
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"mutation { issueAddLabel(id: \"<issue-id>\", labelId: \"<hold-label-uuid>\") { success } }"}'
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"mutation { issueUpdate(id: \"<issue-id>\", input: { assigneeId: \"<user-uuid>\" }) { success } }"}'
```

Read all three back before reporting the hold; `success` says only that the call ran:
```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issue(id: \"<issue-id>\") { assignee { id } labels { nodes { name } } comments { nodes { id } } } }"}'
```

State, team, and label IDs are **resolved at runtime** from the queries above — the same call for every Linear workspace, no per-repo setup. `harness.yaml` carries an ID as an *override* in exactly two cases, each named where it applies above: a custom or renamed state the `type` enum cannot disambiguate, and a team key for the ambiguous-workspace case (`tracker_address.team`, [Resolving the team](#resolving-the-team)); it is not where the standard states or the unambiguous team live.

## Relations — blocked-by

Linear models dependencies as **issue relations**, so a dependency is one
mutation and needs no board. There is one type, `blocks`, and it reads
**`issueId` blocks `relatedIssueId`**. The blocker goes first, so a ticket that
waits on another is the `relatedIssueId`. Linear has no `blocked_by` type to
write it the other way round.

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"mutation { issueRelationCreate(input: { issueId: \"<blocker-id>\", relatedIssueId: \"<blocked-id>\", type: blocks }) { success } }"}'
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issue(id:\"<issue-id>\") { relations { nodes { type relatedIssue { identifier state { type } } } } inverseRelations { nodes { type issue { identifier state { type } } } } } }"}'
```

Read **both** `relations` and `inverseRelations`: Linear stores one edge and
reports it from each side under a different key, so a reader that consults only
one silently sees an unblocked ticket. Read on the blocked ticket, each blocker is
a `blocks` node in `inverseRelations`, named by `issue`. Read on the blocker,
each ticket it holds up is a `blocks` node in `relations`, named by
`relatedIssue`. A `blocks` node under `relations` never means the ticket you
queried is waiting.

## Priority

`priority` is a native integer field on the issue, and Linear renders each value
with a word of its own. The whole scale, because a run that knows only the cord
has to guess at the rest:

| `priority` | Linear renders | harness priority |
|---|---|---|
| `0` | No priority | unset — a filing that reaches Todo or Backlog without one is incomplete |
| `1` | Urgent | **P1**, the andon cord |
| `2` | High | **P2** |
| `3` | Medium | **P3** |
| `4` | Low | below P3; the harness scale stops at P3, so prefer `3` |

Two consequences worth stating, because the mismatch is what misleads:

- **The word is louder than the number.** A P2 filed here displays as "High" and
  a P1 as "Urgent" — an operator reading the board sees Linear's vocabulary, not
  the harness's. Say `P1`/`P2` in a slate or report and let the tracker render it;
  never translate a harness priority into Linear's word in prose.
- **The scale tops out at `1`.** There is no value above Urgent, which matches the
  spine: P1 is the top and it is the cord. A run that wants a tier above P1 wants
  a P1 and a sentence saying why it is the most urgent one.

Set it in the same `issueCreate` input, or afterwards:

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"mutation { issueUpdate(id: \"<issue-id>\", input: { priority: 1 }) { success } }"}'
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issues(filter: { team: { key: { eq: \"<team-key>\" } }, state: { type: { neq: \"completed\" } } }) { nodes { identifier title priority labels { nodes { name } } } pageInfo { hasNextPage } } }"}'
```

The read asks for the open queue with its priority rather than filtering on
`priority: { eq: 1 }` (`tracker` → *The andon cord*). One query carries both
halves here, since `priority` and the labels sit on the same issue.

**`0` is unpriced, and on this backend it arrives looking priced.** `priority` is
a non-null integer, so every row returns one and a bug carrying `0` is indistinguishable
from a bug carrying `3` to a check that asks only whether the field came back.
The table above already calls `0` unset. Coverage is therefore met only by a row
whose `priority` is `1` through `4`; a row priced `0` counts as unpriced, and an
open bug among those leaves the anchor unmet exactly as an absent field does.
The divergence is worth stating because GitHub has no equivalent trap: an unset
Priority there is a missing board field, which already reads as absent. A check
written against GitHub's behaviour and carried over unchanged lets a Linear-backed
tick report a clear line over an unprioritised bug.

`pageInfo.hasNextPage` is how the connection reports that it stopped: `true` is a
truncated read whatever the nodes contain, and a truncated read cannot support an
empty cord answer.

## `ledger`

The append is three operations this file already has: a label-scoped issue query
to find the standing issue, `issueCreate` to open it once, `commentCreate` to
append. Find it by the `improvement-ledger` label; when that search is empty,
search the pre-#547 `proposals-ledger` label and migrate the hit
(`issueUpdate` with the resolved new label id, and the old one dropped) rather
than opening a second ledger.

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issues(filter: { labels: { name: { eq: \"improvement-ledger\" } }, state: { type: { neq: \"completed\" } } }) { nodes { id identifier title url } } }"}'
```

**Read the appended comment back.** `commentCreate` returns `success`, which
says the call ran — not that the entry is on the issue carrying the body you
meant to store. This is the same postcondition rule the rest of this file
applies to `create` and `hold`, and the append is the one write that had been
left outside it. The entry goes as a body file, the comment shape under
*A write that carries ticket text goes as a file* with `issueId` set to the
ledger's id. Take the id from the mutation, then read the body:

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d @<entry-file>
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { comment(id: \"<comment-id>\") { body } }"}'
```

Compare that body against the entry you composed. A ledger entry has **no
second copy**: the reflection it holds exists nowhere else, so an append that
reports success and stored something else is lost with nothing to say it ever
existed. Where the body came from a file, confirm it is the entry's text rather
than the file's path.

### Prune — removing decided entries

`commentDelete` removes one comment. The ids come from the disposition comment
(`tracker` → *`ledger`* → *Prune*), one mutation per id, each written literally
rather than looped over a query's output, about fifteen to a batch. That bound
comes from an agent host screening destructive calls rather than from any API,
so it applies here as much as to GitHub: see that reference's *Prune* for the
refusals it was measured against.

```bash
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"query { issue(id:\"<ledger-id>\") { comments { nodes { id createdAt body } pageInfo { hasNextPage } } } }"}'
curl -sS -X POST https://api.linear.app/graphql -H 'Content-Type: application/json' -d '{"query":"mutation { commentDelete(id: \"<comment-id>\") { success } }"}'
```

`success` says the call ran. Verify by re-reading the comments connection and
comparing identities against the ids the pre-delete read returned: every pruned
id absent, every other one of them still present. **`pageInfo.hasNextPage` is
the completeness signal here** — `true` is a read that stopped, whatever the
nodes contain, exactly as under *Priority* above, and a stopped read reports
every comment it never returned as absent, which is the answer the check exists
to refuse. That signal is order-agnostic, so it carries the check on its own:
this file does not state which end of the connection the newest comment arrives
from, and nothing here should assume one.

Linear hides archived resources from an ordinary read, so absence from the
connection is what this operation promises and all it promises: the entry no
longer appears when the ledger is read.
