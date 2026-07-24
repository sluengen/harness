<!-- guidance:bug@0.1.0 -->
# /bug — capture a bug straight to Todo

Usage: `/bug <description>`

A bug noticed in actual use has nowhere lightweight to land: `/propose`
decides the unconfirmed (a bug is not unconfirmed — something is broken and
should be fixed), and hand-filing a tracker issue is fiddly and trap-laden.
`/bug` is a thin capture command: it fills the shared
`templates/adjustment.md` with `kind: bug` and files it straight to Todo,
ready for `/start` to pick up. It is the inverse of `/propose` — `/propose`
decides, then files; `/bug` files the already-decided.

A bug has **no escape hatch**. The as-built behaviour already contradicts the
intent, so there is nothing to decide — the fix direction is "make it match."
(Contrast `/tweak`, whose "should we?" axis can escalate to `/propose`.)

## Steps

**Step 1 — gather the observed behaviour.** From the description (or by
asking, in one turn, if it is missing): what actually happens today, and a
repro — the steps or input that trigger it. Also capture what tipped you off
(what you were doing, what you expected instead) and the desired behaviour —
the outcome, not the implementation.

**Step 2 — fill the template.** Fill `templates/adjustment.md` with:
- `kind: bug`, `area: <surface/feature>`
- **As-built (observed)** — the wrong behaviour, plus the repro
- **Desired** — what should happen instead, one or two sentences
- **From actual use** — the situation that surfaced it
- **Acceptance criteria** — specific, testable outcomes

**Step 3 — file it (tracker-neutral).** Read `CONTEXT.md`'s `tracker:` field
and file through the matching backend:

- **`tracker: github`** — three steps, in order (skipping the middle one is
  the item-add-no-status trap, tick #90 — a filed item lands with Status
  unset and `work-discovery`'s Todo-scoped read never sees it):

  ```bash
  # 1. create the issue
  gh issue create --repo <github.repo> --title "<title>" --body-file <path>

  # 2. add it to the board (capture the returned item id)
  gh project item-add <github.project number> --owner <github.project owner> \
    --url <issue-url> --format json

  # 3. resolve the Status field + Todo option, then set it explicitly
  gh project field-list <github.project number> --owner <github.project owner> --format json
  gh project item-edit --id <item-id> --field-id <status-field-id> \
    --project-id <project-id> --single-select-option-id <todo-option-id>
  ```

  Resolve `<project-id>` via `gh project view <number> --owner <owner>
  --format json` (its `.id`). None of these ids are stable across
  repos — resolve them at runtime, the same rule the `linear` skill uses for
  Linear's team/state/label ids.

- **`tracker: linear`** — file through the `linear` skill's `issueCreate`
  recipe (`projectId` mandatory — a project-less issue is invisible to the
  Build queue). A new issue lands in the team's default state, which is often
  **not** Todo — resolve the `unstarted` state by `type` (the skill's
  "Resolving states by type" recipe) and move it explicitly with
  `issueUpdate`, the same way a filed-item's Status must be set explicitly on
  GitHub.

## Report

Print the filed ticket's identifier and URL, then:

```
Next: /start <TICKET>   (or /harness run <TICKET>)
```
