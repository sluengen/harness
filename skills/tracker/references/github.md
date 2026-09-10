# The GitHub transport

**Load this when `harness.yaml` says `tracker: github`.** The semantics — what each operation must achieve, what makes a filing incomplete, the hold contract, the ledger — are `tracker`'s `SKILL.md`, already loaded. This file is only *how* each operation is performed against GitHub Issues plus a Projects v2 board.

The addresses come from `harness.yaml`'s `github:` block:

```yaml
tracker: github
github:
  repo: <owner>/<name>        # the issues repo
  project: <owner>/<number>   # the Projects v2 board
  # status_field omitted -> the built-in "Status" field
```

**The queue is the board.** A GitHub board already scopes the queue, so `repo.project` is not consulted on this backend.

**Credential.** `GITHUB_TOKEN`, with `repo` **and** `project` scopes — the second is easy to miss and is what every board mutation needs. `gh` uses it from the environment. Never echo it.

## Two failures that look the same from the call site

A `gh` command can fail because **the token lacks a scope** or because **the GraphQL transport is refused in front of GitHub**. The error at the call site is a 403 either way, and only the first has a credential remedy — `GITHUB_TOKEN=$(gh auth token)` re-reads the same environment token when one is already set, so it is a no-op against the second and burns a cycle looking like a fix.

**Tell them apart with two probes, before concluding anything about the credential:**

```bash
gh api repos/<owner>/<name> --jq .full_name          # REST
gh api graphql -f query='query { viewer { login } }' # GraphQL
```

- Both fail → a credential or permission problem. `gh auth status` and the REST error body name it; fix the token.
- **REST succeeds and GraphQL returns 403** → the transport is refused. The body says so in words, naming the session rather than a scope. `gh auth status` may separately report the environment token invalid *while REST keeps working*, so do not read that line as the diagnosis.

### What is reachable when GraphQL is refused

**Every `gh issue` subcommand goes through GraphQL** — `gh issue view`, `gh issue list`, with or without `--json` — so the recipes below fail wholesale on such a host even though the underlying data is fine. **Issue-level work has a full REST surface**; reach it with `gh api` and the operations are complete:

| Operation | REST |
|---|---|
| `open` | `gh api repos/<owner>/<name>/issues/<n>` |
| `create` | `gh api -X POST repos/<owner>/<name>/issues -f title=... -F body=@<path> -f 'labels[]=assurance:<level>'` |
| `comment` | `gh api -X POST repos/<owner>/<name>/issues/<n>/comments -F body=@<path>` |
| `hold` | the `comment` POST above, then `gh api -X POST repos/<owner>/<name>/issues/<n>/labels -f 'labels[]=<input\|operator>'`, then `gh api -X POST repos/<owner>/<name>/issues/<n>/assignees -f 'assignees[]=<login>'`, then a read-back |
| `queue` / `held` | `gh api 'repos/<owner>/<name>/issues?state=open&labels=<label>&assignee=<login\|none>&per_page=100'` |
| `close` | `gh api -X PATCH repos/<owner>/<name>/issues/<n> -f state=closed` |
| dependencies | the `dependencies/blocked_by` and `dependencies/blocking` calls below — already REST |

Three differences from the `gh issue` forms. REST `/issues` **returns pull requests as well as issues**, so filter `select(.pull_request == null)`. The REST `assignee` parameter takes a login or the literal `none`; there is no `@me`. And **adding a label is its own `POST .../labels` endpoint** — a `PATCH` carrying `labels[]` replaces the whole set and silently drops the assurance label, which is an incomplete filing you inflicted on yourself.

**Projects v2 has no REST API at all** — no `repos/{owner}/{repo}/projectsV2`, nothing under the repo scope, by design; the board is GraphQL-only. So on a GraphQL-refused host every `gh project` call fails (often as the unhelpful `unknown owner type`, which is a 403 underneath), and with it **Status, Priority, and therefore `create`'s mandatory placement**. That is not a step to skip quietly: the issue exists and the board does not know about it, which is precisely the item-add-no-status trap arriving by another route. **Report the filing incomplete** — the identifier, the URL, and which board operations could not run — and stop. Never report a ticket as placed, queued, or prioritised on the strength of the issue having been created.

#### `create` stops there; `transition` does not

The rule above is `create`'s. A **`transition`** on the same host takes the
opposite disposition, and the asymmetry is the point rather than an
inconsistency.

An unplaced filing is **invisible**: no Todo-scoped queue read will ever return
it, so a run that continued past one would leave a ticket nobody can find. A
transition moves an issue that is **already on the board and already reachable
by REST**, so what goes stale is the board's currency, not the ticket's
existence. Stopping there would also refuse every run on such a host — `/build`
transitions twice (In Progress, In Review) and `/promote` once (Done), so
"report incomplete and stop" applied to transitions is a refusal to work at all.

So where `item-edit` cannot run:

1. **Post the state change as an issue comment**, naming the state and saying
   the board could not be written. That comment is the record of the
   transition.
2. **Continue the run.**
3. **Say in the run's report that the board is stale**, naming the issue and the
   state the board ought to show. Never report the ticket as *moved*: no board
   write happened, and a call that did not run returns no evidence.

The comment is what stands in for the board, so it carries what a board read
would have told someone: which state, and that the board disagrees.

**This is the item-add-no-status trap arriving through the transition door**,
and step 3 is what keeps it visible. The cost is real and is accepted rather
than solved here: the queue's selector and the queue's truth stay apart until a
session with GraphQL reconciles them, and a closed ticket can sit with its board
Status still reading Todo. Nothing in this section reaches Projects v2 by
another route; the refusal is the carry recorded in
`specs/harness-assumptions.md`, and it stays carried.

## No id here is stable — resolve at runtime

Project ids, status field ids, and single-select option ids differ per board and change when a field is renamed. Resolve them each time; never hard-code or cache one.

```bash
# the board's node id
gh project view <number> --owner <owner> --format json        # -> .id

# the Status field id + its option ids (Backlog / Todo / In Progress / In Review / Done)
gh project field-list <number> --owner <owner> --format json
```

## The operations

### `open` — read an issue

```bash
gh issue view <number> --repo <owner>/<name> \
  --json number,title,body,state,assignees,labels,url
```

### `create` — file an issue **onto the board, with Status set**

Four steps, in order. **Skipping the third is the item-add-no-status trap:** an item added to the board lands with **Status unset**, and a Todo-scoped queue read never sees it — the issue exists, looks filed, and is invisible to the loop.

**Backlog is a Status option like any other**, and a board that declares none gives a ticket nowhere to wait. Report the filing incomplete, naming the missing option, rather than placing it in Todo past the limit.

```bash
# 1. create the issue, carrying the chosen assurance level (use --body-file;
#    never interpolate untrusted text into the shell)
gh issue create --repo <owner>/<name> --title "<title>" --body-file <path> \
  --label assurance:<level>

# 2. add it to the board, capturing the returned item id
gh project item-add <number> --owner <owner> --url <issue-url> --format json

# 3. set Status explicitly (ids from the field-list call above) — the Todo
#    option where the project has a free slot, the Backlog option where it
#    does not (`tracker` -> The limit)
gh project item-edit --id <item-id> --field-id <status-field-id> \
  --project-id <project-id> --single-select-option-id <status-option-id>

# 4. verify the postcondition by re-reading both properties, not by exit
#    status: the label on the issue, and the Status on the board item
gh issue view <number> --repo <owner>/<name> --json labels
gh project item-list <number> --owner <owner> --format json
```

`<level>` is the lane the filer chose per `authoring` → *Choosing assurance* — this recipe maps a value, it never selects one. `gh issue create` **errors when the label does not exist in the repo**, which is the correct fail-closed behaviour and is exactly the incomplete filing the spine's filing contract names: report the identifier and URL, say the filing is incomplete, and stop.

**Step 4 reads back two properties, because a filing has two halves.** `gh issue view --json labels` turns "the command exited zero" into evidence that exactly one assurance label is on the issue, and it says nothing about the board: a silent step-3 failure passes it unseen, which is the item-add-no-status trap surviving its own verification. The placement `create` owes is established when the item's Status comes back as the option step 3 set.

**Where `gh project item-list` runs,** compare the Status it reports for this item against that option. Agreement confirms the write landed; a mismatch is unresolved rather than a diagnosis, because this is the field recorded unreliable under `transition` below. Either way, report the ticket as placed only once the two agree.

**Where it does not run, say which case you are in.** On the GraphQL-refused host of *What is reachable when GraphQL is refused* above, every `gh project` call fails and Projects v2 offers no REST read to substitute, so step 4 cannot confirm placement at all. The filing is incomplete under the rule stated in that section: report the identifier, the URL, and the board operation that could not run, and stop. The issue existing and its label reading back is evidence about the issue, never about the board.

**Quote titles; pass bodies as `--body-file`.** Issue text is frequently lifted from a report, a review finding, or a design section, and may carry backticks, `$(…)`, or newlines. A heredoc of tracker-derived text interpolated into a shell command is a command-injection boundary — the same rule as never using `shell=True` with untrusted input.

### `transition` — move an issue's Status

The same `gh project item-edit` call as step 3 above, with the option id of the target state. Resolve the item id for an already-filed issue from the board:

```bash
gh project item-list <number> --owner <owner> --format json
```

> **The `status` field in `item-list` output has been observed unreliable** — it has reported every item `Done` on a healthy board. To read the queue, prefer the issue-level view (`queue`, below) and treat `item-list` as the way to resolve **item ids**, not as the source of truth for state.

Where GraphQL is refused, neither call runs. Record the transition as a comment
and continue, per [`create` stops there; `transition` does not](#create-stops-there-transition-does-not) above.

### `comment`

```bash
gh issue comment <number> --repo <owner>/<name> --body-file <path>
```

### `hold` — comment, label, assign

Three writes, per `tracker` → *`hold`*. `gh issue edit` does the label and the assignment in one call and no comment, so the comment is its own call and goes first:

```bash
gh issue comment <number> --repo <owner>/<name> --body-file <path>
gh issue edit <number> --repo <owner>/<name> \
  --add-label <input|operator> --add-assignee <operator-login>
```

Then read all three back. A login the repository cannot assign — no push access — is dropped silently and the edit still reports success, which is the incomplete hold that leaves a ticket pickable:

```bash
gh issue view <number> --repo <owner>/<name> --json assignees,labels,comments
```

### `queue` — the Todo work

```bash
gh issue list --repo <owner>/<name> --state open --limit 100 \
  --json number,title,labels,assignees
```

Skip anything with a non-empty `assignees` (a human holds it) or a hold label. Cross-reference the board for Status when the distinction between Todo and In Progress matters.

**The held pile is the same operation with that filter inverted.** Ask for the hold label *and* the operator's own assignment, both conditions, plus the fields a triage read needs (the queue read above returns neither `url` nor `body`):

```bash
gh issue list --repo <owner>/<name> --state open \
  --label <input|operator> --assignee @me \
  --json number,title,url,body,updatedAt
```

## Closing an issue

Moving Status to Done is the board-side transition; closing the issue itself is separate:

```bash
gh issue close <number> --repo <owner>/<name> --comment "<merge or PR link>"
```

A merged PR naming the issue (`Fixes #<n>`, or the bare id in a branch, title, body or commit) closes it automatically — so name an id only when the PR actually completes that ticket (`tracker` sync rule 6).

### `create`, continued — dependencies and priority

**Blocked-by is a first-class REST relationship**, not a board field, so it
works wherever `gh api` does — including on a host where GraphQL is refused:

```bash
# read what a ticket waits on, and what waits on it
gh api repos/<owner>/<name>/issues/<n>/dependencies/blocked_by \
  --jq '.[] | "\(.number) \(.state) \(.title)"'
gh api repos/<owner>/<name>/issues/<n>/dependencies/blocking --jq '.[].number'

# declare one: <n> waits on <blocker>. The body takes the blocker's node id,
# not its number — resolve it first.
BLOCKER_ID=$(gh api repos/<owner>/<name>/issues/<blocker> --jq '.id')
gh api -X POST repos/<owner>/<name>/issues/<n>/dependencies/blocked_by \
  -F issue_id="$BLOCKER_ID"
```

**Priority is a board field**, so it goes through the same `item-edit` call as
Status, with the Priority field's id and the option id for the level. Resolve
both from `gh project field-list` at runtime, exactly as for Status — a field id
is per-board and changes when a field is renamed. Being a board field, it is
also unreachable when GraphQL is refused; a filing that could not set it is
incomplete, and says so.

> **The board is the one operation with no MCP equivalent.** The official GitHub
> MCP server exposes no Projects v2 operation of any kind — no board read, no
> item add, no field write — so a repo whose transport is the MCP plugin still
> needs `gh` (or an equivalent GraphQL call) for Status and Priority. Recorded in
> `specs/harness-assumptions.md` with the test that would retire it.

### `ledger`

The append is three operations this file already has: `queue` scoped by label to
find the standing issue, `create` to open it once, `comment` to append.

```bash
# find it — by label, never by number
gh issue list --repo <owner>/<name> --state open --label improvement-ledger \
  --json number,title,url
# ... and if that is empty, try the older name before creating anything
gh issue list --repo <owner>/<name> --state open --label proposals-ledger \
  --json number,title,url
# migrate a hit rather than opening a second ledger
gh issue edit <n> --repo <owner>/<name> \
  --add-label improvement-ledger --remove-label proposals-ledger
```

All three are `gh issue` calls, so on a GraphQL-refused host run them through
the REST equivalents in the table above; the ledger needs no board, and the
append completes there.

**Read the appended comment back.** The append is a write like every other one
in this file, and `create` and `hold` already carry the rule it was missing:
verify the postcondition by re-reading, never by exit status. Capture the id the
POST returns, then read the body it stored:

```bash
COMMENT_ID=$(gh api -X POST repos/<owner>/<name>/issues/<n>/comments \
  -F body=@<path> --jq '.id')
gh api repos/<owner>/<name>/issues/comments/"$COMMENT_ID" --jq '.body'
```

Compare it against the entry you composed. **A body that reads back as a
filesystem path was posted by `-f` where `-F` was meant** — and by the time
anyone reads the ledger, the scratchpad that path names is gone.

> **`-F` reads `@<path>` as a file; `-f` sends the string verbatim.** One
> character between them, and `gh` exits **0** either way, so nothing surfaces
> the mistake at the call site. #450's comment `5601650321` is the live
> instance: its body is the literal path, to a scratchpad belonging to a
> session that no longer exists, and the entry it was meant to carry is
> unrecoverable.
> It is left in place as the record.
>
> The trap applies to every `-F body=@` form in this file — `create`,
> `comment`, `hold` — but it costs most here. A ticket body posted wrongly is
> visible to the next person who opens the issue, and can be edited. **A ledger
> entry has no second copy**, and nobody re-reads it until the drain, by which
> time the file is gone.
