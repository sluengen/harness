# Build Workflow — steps, prompts, verdict loop

The `build` workflow is the primary dog-fooding workflow for the harness itself. It takes a Linear ticket ID, implements the changes in an isolated worktree, reviews them, and merges if the review passes.

---

## Purpose

General-purpose implementation workflow for harness issues. Sets a Linear ticket in-progress, fetches its content, runs an AI implementation agent, reviews the output, commits and pushes on PASS, then marks the ticket done.

---

## Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `linear_id` | string | yes | — | Linear ticket ID, e.g. `PROJ-512`. Pattern: `^[A-Z]+-\d+$`. Flag: `--linear`. |
| `base_branch` | string | no | `main` | Branch to create the worktree from. Flag: `--base-branch`. |

---

## Steps

### `setup` (worktree.create)

Creates a worktree at `<repo_root>/.worktrees/harness/<run_id>/` on branch `harness/<run_id>` starting from `$inputs.base_branch`. Writes `worktree_path` and `worktree_branch` to state.

### `set-in-progress` (script)

Queries Linear's GraphQL API to find the "started" state ID for the ticket's team, then updates the ticket to that state. Output is `{}` (no state writes). Uses `$LINEAR_API_KEY` from the environment. Requires `jq` on PATH.

### `fetch-ticket` (script)

Queries Linear's GraphQL API for the ticket's `title` and `description`. Parses the response with `jq` and writes `ticket_title` and `ticket_description` to state.

Contract: `{ticket_title: string, ticket_description: string}`.

### `implement` (ai)

Dispatches a `claude/sonnet` agent in the worktree with `prompts/build/implement.j2`. Allowed tools: `Read, Write, Edit, Bash, Grep, Glob`. Declares `writes_files: true` and `writes: []` — file mutations are the output; no state fields are written.

The prompt instructs the agent to follow `skills/test-driven-development.md`, run the full verification gate (`ruff check .`, `mypy harness`, `pytest`), and call the submit tool once when complete.

### `review` (ai)

Dispatches a `claude/sonnet` agent in the worktree with `prompts/build/review.j2`. Allowed tools: `Read, Grep, Glob, Bash`. Writes `verdict`, `issues`, and `commit_message` to state.

Contract:
```yaml
verdict:
  type: string
  enum: [PASS, FAIL]
issues:
  type: list
  of: string
commit_message: string
```

The prompt instructs the agent to evaluate correctness against the acceptance criteria, tag findings HIGH/MEDIUM/LOW, and write a `type(scope): description` commit message describing what was actually built.

### `gate` (check)

Evaluates `state.verdict == "PASS"`. `on_fail: cancel`. A FAIL verdict cancels the run here with exit code 1; `worktree_path` remains set so the runner logs `cleanup_skipped=True` in the `workflow_failed` event.

### `commit-and-push` (script)

Runs in the worktree (`cwd` defaults to `state.worktree_path` because it is set on state):

```bash
git add -A
git commit -m "$state.commit_message"
git push -u origin $state.worktree_branch
printf '{"commit_sha": "%s"}' "$(git rev-parse HEAD)"
```

Writes `commit_sha` to state. Contract: `{commit_sha: string}`.

### `teardown` (worktree.cleanup)

Policy: `delete_unconditionally`. Removes the worktree directory and force-deletes the branch. At this point the branch has already been pushed to `origin`, so the local branch is safe to delete.

### `close-task` (script)

Queries Linear for the "completed" state ID and transitions the ticket to done. Output is `{}` (no state writes). Runs from `cwd: "."` (the repo root, not the worktree, which was just deleted).

---

## State fields (derived)

| Field | Type | Written by |
|---|---|---|
| `worktree_path` | `Path` | `setup` |
| `worktree_branch` | `str` | `setup` |
| `ticket_title` | `str` | `fetch-ticket` |
| `ticket_description` | `str` | `fetch-ticket` |
| `verdict` | `str` | `review` |
| `issues` | `list[str]` | `review` |
| `commit_message` | `str` | `review` |
| `commit_sha` | `str` | `commit-and-push` |

Plus `BaseState` fields: `run_id`, `workflow_name`, `base_branch`, `artifacts_dir`, `started_at`, `notes`.

---

## Prompts

### `prompts/build/implement.j2`

Instructs the agent to implement the changes for `{{ inputs.linear_id }}`, showing the ticket title and description from state. Three phases: implement (TDD), verify (`ruff check .`, `mypy harness`, `pytest`), submit. Calls `{{ submit_tool_name | default('submit') }}` once with no arguments on completion.

### `prompts/build/review.j2`

Instructs the agent to review the implementation against the acceptance criteria from `{{ state.ticket_description }}`. Evaluates correctness, test coverage, focused diff, regressions. Tags findings HIGH/MEDIUM/LOW. Writes a commit message describing what was built. Calls submit once with `verdict`, `issues`, and `commit_message`.

---

## Notable constraints

- `set-in-progress` and `close-task` both use `printf '{}'` to emit an empty JSON object to stdout. This is the `writes: []` sidecar pattern — no contract, no state writes.
- The `commit-and-push` step sends git output to stderr (`>&2`) and only writes the JSON commit SHA to stdout, so the script contract can parse stdout cleanly.
- `teardown` uses `delete_unconditionally` (not `merge_to_base`) because the push to `origin` is the merge mechanism; the local branch is ephemeral.
- If `gate` cancels the run, `teardown` never runs. The worktree is left in place for manual inspection. The `workflow_failed` event carries `cleanup_skipped=True` as a hint.
- Linear API calls require `LINEAR_API_KEY` in the environment and `jq` on PATH. No harness-level retry is applied to these script steps; a failed Linear API call exits non-zero and cancels the run.
