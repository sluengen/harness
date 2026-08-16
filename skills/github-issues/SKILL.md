---
name: github-issues
description: Use when the repo's CONTEXT.md says tracker github and you need to read or update a ticket — opening an issue, filing one onto the Projects v2 board, setting its Status, commenting, holding it, or pulling the Todo queue. The GitHub provider recipes; the backend-neutral policy is in the tracker skill.
---
<!-- guidance:github-issues@0.2.1 -->
# GitHub Issues

The **GitHub provider recipes** for the tracker protocol. Policy — the operation set, the state names, placement, holds, sync rules, the `none` degrade — lives in the **`tracker`** skill. Read that first; this file is only *how* each operation is performed against GitHub Issues plus a Projects v2 board.

Applies when `CONTEXT.md` says `tracker: github`. The addresses come from its `github:` block:

```yaml
tracker: github
github:
  repo: <owner>/<name>        # the issues repo
  project: <owner>/<number>   # the Projects v2 board
  # status_field omitted -> the built-in "Status" field
```

**The queue is the board.** A GitHub board already scopes the queue, so `repo.project` is not consulted on this backend.

**Credential.** `GITHUB_TOKEN`, with `repo` **and** `project` scopes — the second is easy to miss and is what every board mutation needs. `gh` uses it from the environment; `GITHUB_TOKEN=$(gh auth token)` refreshes an expired one. Never echo it.

## No id here is stable — resolve at runtime

Project ids, status field ids, and single-select option ids differ per board and change when a field is renamed. Resolve them each time; never hard-code or cache one.

```bash
# the board's node id
gh project view <number> --owner <owner> --format json        # -> .id

# the Status field id + its option ids (Todo / In Progress / In Review / Done)
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

```bash
# 1. create the issue, carrying the chosen assurance level (use --body-file;
#    never interpolate untrusted text into the shell)
gh issue create --repo <owner>/<name> --title "<title>" --body-file <path> \
  --label assurance:<level>

# 2. add it to the board, capturing the returned item id
gh project item-add <number> --owner <owner> --url <issue-url> --format json

# 3. set Status explicitly (ids from the field-list call above)
gh project item-edit --id <item-id> --field-id <status-field-id> \
  --project-id <project-id> --single-select-option-id <todo-option-id>

# 4. verify the postcondition by re-reading the issue, not by exit status
gh issue view <number> --repo <owner>/<name> --json labels
```

`<level>` is the level the filer chose per `spec-authoring` → *Choosing assurance* — this recipe maps a value, it never selects one. `gh issue create` **errors when the label does not exist in the repo**, which is the correct fail-closed behaviour and is exactly the incomplete filing the `tracker` protocol names: report the identifier and URL, say the filing is incomplete, and stop. Step 4 is what turns "the command exited zero" into evidence that exactly one assurance label is on the issue.

**Quote titles; pass bodies as `--body-file`.** Issue text is frequently lifted from a report, a review finding, or a design section, and may carry backticks, `$(…)`, or newlines. A heredoc of tracker-derived text interpolated into a shell command is a command-injection boundary — the same rule as never using `shell=True` with untrusted input.

### `transition` — move an issue's Status

The same `gh project item-edit` call as step 3 above, with the option id of the target state. Resolve the item id for an already-filed issue from the board:

```bash
gh project item-list <number> --owner <owner> --format json
```

> **The `status` field in `item-list` output has been observed unreliable** — it has reported every item `Done` on a healthy board. To read the queue, prefer the issue-level view (`queue`, below) and treat `item-list` as the way to resolve **item ids**, not as the source of truth for state.

### `comment`

```bash
gh issue comment <number> --repo <owner>/<name> --body-file <path>
```

### `hold` — label **and** assign

Both, per the `tracker` skill: the assignee is the machine-readable skip signal, the label explains why.

```bash
gh issue edit <number> --repo <owner>/<name> \
  --add-label <input|operator> --add-assignee <operator-login>
```

### `queue` — the Todo work

```bash
gh issue list --repo <owner>/<name> --state open --limit 100 \
  --json number,title,labels,assignees
```

Skip anything with a non-empty `assignees` (a human holds it) or a hold label. Cross-reference the board for Status when the distinction between Todo and In Progress matters.

## Closing an issue

Moving Status to Done is the board-side transition; closing the issue itself is separate:

```bash
gh issue close <number> --repo <owner>/<name> --comment "<merge or PR link>"
```

A merged PR naming the issue (`Fixes #<n>`, or the bare id in a branch, title, body or commit) closes it automatically — so name an id only when the PR actually completes that ticket (`tracker` sync rule 6).
