# Build Workflow — steps, prompts, verdict loop, merge phase

The `build` workflow is the primary dog-fooding workflow for the harness itself. It takes a Linear ticket ID, implements the changes in an isolated worktree, reviews them, commits the implementation, merges to the base branch, tears down the worktree, then marks the ticket done.

---

## Purpose

General-purpose implementation workflow for harness issues. Sets a Linear ticket in-progress, fetches its content, reads the target project's CLAUDE.md, runs an AI implementation agent, reviews the output in a loop (up to 3 iterations), commits and merges to base on PASS or DEFER, tears down locally, then marks the task done.

---

## Inputs

| Input | Type | Required | Default | Description |
|---|---|---|---|---|
| `linear_id` | string | yes | — | Linear ticket ID, e.g. `PROJ-512`. Pattern: `^[A-Z]+-\d+$`. Flag: `--linear`. |
| `base_branch` | string | no | `dev` | Branch to merge into. Flag: `--base-branch`. |
| `repo_path` | string | no | `.` | Filesystem root for git worktree operations. Flag: `--repo-path`. |
| `verify_command` | string | no | `bash scripts/verify.sh` | Shell command used as the verification gate. Flag: `--verify-command`. |
| `branch_prefix` | string | no | `harness` | Prefix for feature branches. Flag: `--branch-prefix`. |

---

## Steps

### `setup` (worktree.create)

Creates a worktree at `<repo_root>/.worktrees/<branch_prefix>/<run_id>/` on branch `<branch_prefix>/<run_id>` starting from `$inputs.base_branch`. Writes `worktree_path` and `worktree_branch` to state.

### `set-in-progress` (script)

Queries Linear's GraphQL API to find the "started" state ID for the ticket's team, then updates the ticket to that state. Output is `{}` (no state writes). Uses `$LINEAR_API_KEY` from the environment. Requires `jq` on PATH.

### `fetch-ticket` (script)

Queries Linear's GraphQL API for the ticket's `title` and `description`. Parses the response with `jq` and writes `ticket_title` and `ticket_description` to state.

Contract: `{ticket_title: string, ticket_description: string}`.

### `read-target-claude-md` (script)

Reads `CLAUDE.md` from `$inputs.repo_path` and writes its content to state as `target_claude_md`. Runs once before the fix-loop.

Contract: `{target_claude_md: string}`.

### `fix-loop` (loop, max 3 iterations)

Iterates `implement → verify → gate-verify → capture-diff → review → gate-retry` until the review verdict is not FAIL, or until 3 iterations are exhausted (at which point the loop continues with `on_exhaust: continue`).

The verify step is a deterministic script gate — it runs the verify command and captures output into state before the review agent ever sees the change. If verify fails, `gate-verify` retries the loop immediately (skipping capture-diff and review), and the failure output is appended to `issues` so the implement agent sees it on the next iteration. This keeps destructive Bash access out of the review agent entirely.

**Feedback fidelity across iterations.** The `review` step writes `issues` with `merge: replace`, so each iteration's `issues` reflects only the *current* review's findings — not the union of every prior round. The default list merge is append (`harness.state.store._merge`); left as the default, already-fixed findings would pile up across iterations and the implement agent (a fresh, stateless agent each round) would be told to re-fix them. The `verify` step keeps the default append merge so a verify-failure message rides alongside any still-outstanding review findings rather than clobbering them; the next successful review's replace clears the combined list.

**Diff for the read-only reviewer.** Because the review agent has no Bash (it cannot run `git`), `capture-diff` records the branch's diff against the base into `state.diff` and `review-ticket.j2` embeds it. Without this the reviewer would have no reliable view of *what changed* and could not assess the "focused diff" criterion.

**Session continuity (implement only).** The `implement` step sets `persist_session: true`, so the agent adapter resumes the *same* conversation on each retry instead of starting fresh — the agent keeps the reasoning and history of its prior attempt and does not re-derive context from scratch. Sessions are keyed by `step.id` in the adapter, so the implement and review steps (which share one `ClaudeAgent` instance in `build.yaml`) keep independent threads. `review` deliberately omits the flag: each review should judge the diff fresh, without anchoring on its own prior verdict. The session id is captured only after a submit validates (a contract-violating attempt never poisons the next resume), is in-memory on the adapter (does not survive a process restart / `harness resume`), and is cleared by `reset()` so a `fresh_context: true` loop overrides persistence.

#### `implement` (ai, inside fix-loop)

Dispatches a `claude/sonnet` agent in the worktree with `prompts/implement-ticket.j2`. Allowed tools: `Read, Write, Edit, Bash, Grep, Glob`. Declares `writes_files: true`, `persist_session: true` (resume across retries — see "Session continuity" above), and `writes: []`.

The prompt instructs the agent to follow `skills/test-driven-development.md`, run the full verification gate, and call the submit tool once when complete.

#### `verify` (script, inside fix-loop)

Runs `$inputs.verify_command` as a subprocess (cwd defaults to `worktree_path`). Captures `verify_exit_code` (int) and `verify_output` (string) into state. On failure, appends a "Verify gate failed" entry to `issues`. Allowed tools: none (pure shell).

Contract: `{verify_exit_code: integer, verify_output: string, issues: list[string]}`.

#### `gate-verify` (check, inside fix-loop)

Evaluates `state.verify_exit_code == 0`. `on_fail: retry_loop:fix-loop`. Short-circuits to implement when verify fails — review is never called with a failing worktree.

#### `capture-diff` (script, inside fix-loop)

Runs `git diff <base_branch>...HEAD` in the worktree (cwd defaults to `worktree_path`) and writes the result to `state.diff`. The three-dot form diffs against the merge-base, so it captures exactly this branch's changes even if the base advanced during the run. Runs after `gate-verify` (so it only fires on a passing build) and before `review`. Allowed tools: none (pure shell).

Contract: `{diff: string}`. Writes: `[diff]`.

#### `review` (ai, inside fix-loop)

Dispatches a `claude/sonnet` (or `codex` in `build-codex`) agent in the worktree with `prompts/review-ticket.j2`. The prompt embeds `state.diff` (captured by `capture-diff`) and `state.verify_output` so the read-only agent sees what changed and that the gate passed. Writes `verdict`, `issues`, `commit_message`, and `deferred_brief` to state. The `issues` write uses `merge: replace` (see "Feedback fidelity" above). Allowed tools: `[Read, Grep, Glob]` — no Bash: verify already ran as a script step and the diff is supplied via state, so the agent never needs `git` (a prior run with Bash destructively deleted a branch).

Contract:
```yaml
verdict:
  type: string
  enum: [PASS, FAIL, DEFER]
issues:
  type: list
  of: string
commit_message: string
deferred_brief: string
```

Writes: `[verdict, {field: issues, merge: replace}, commit_message, deferred_brief]`.

#### `gate-retry` (check, inside fix-loop)

Evaluates `state.verdict != "FAIL"`. `on_fail: retry_loop:fix-loop`. Retries the loop when verdict is FAIL.

### `notify-exhausted` (script)

No-op unless the loop exhausted with verdict still FAIL. On exhaustion: posts a Linear comment with the branch and reviewer findings, then resets the ticket to Todo state.

### `gate-exhausted` (check)

Evaluates `state.verdict in ("PASS", "DEFER")`. `on_fail: cancel`. Cancels the run if the fix-loop exhausted without an accepted verdict. Using `in ("PASS", "DEFER")` (rather than `!= "FAIL"`) correctly catches both review-FAIL exhaustion and the verify-only failure case where `verdict` was never set by review.

### `handle-deferred` (script)

No-op unless verdict is DEFER. On DEFER: creates a child Linear ticket with `deferred_brief` as the title.

### `set-in-review` (script)

Transitions the Linear ticket to the "In Review" state. Runs exactly once, after the fix-loop exits on the commit path.

### `commit` (script)

Runs in the worktree (`cwd` defaults to `state.worktree_path`):

```bash
git add -A >&2
git commit --amend -m "$commit_message" >&2
printf '{"commit_sha": "%s"}' "$(git rev-parse HEAD)"
```

Writes `commit_sha` to state. Contract: `{commit_sha: string}`. **No push** — pushing is handled by `push-base` after the merge phase succeeds.

---

## Merge phase

After `commit`, the workflow merges the local feature branch into the base branch in the main repository and pushes the result to origin. The remote feature branch is **never created on the success path** — the feature branch lives only in the local worktree until `teardown` deletes it.

### `attempt-merge` (script)

Runs in the **main repo** (`cwd: "."`, resolved to `repo_root`). Checks out the base branch and merges the local feature branch with `--no-ff`. No fetch needed — the feature branch exists locally.

Args: `[$inputs.base_branch, $state.worktree_branch]`

Contract:
```yaml
merge_status:
  type: string
  enum: [clean, conflict]
conflict_files: string   # comma-separated; empty when clean
```

Writes: `[merge_status, conflict_files]`

### `conflict-loop` (loop, max 2 iterations)

Only meaningfully traversed when `merge_status == "conflict"`. Uses `on_exhaust: continue` so post-loop steps handle the failure path.

The `gate-still-conflicted` guard inside the loop prevents `resolve-conflicts` from running when `merge_status` is already "clean" (harness loops are post-tested; this guard short-circuits the loop body on the clean path via `retry_loop:conflict-loop`).

#### `gate-still-conflicted` (check, inside conflict-loop)

Evaluates `state.merge_status == "conflict"`. `on_fail: retry_loop:conflict-loop`. When the merge is already clean, this check fails and the loop body is short-circuited — resolve-conflicts is not invoked.

#### `resolve-conflicts` (ai, inside conflict-loop)

Dispatches a `claude/sonnet` agent in the main repo (`cwd: "."`) with `prompts/build/resolve-conflicts.j2`. Reads conflicting files, resolves all `<<<<<<<`/`=======`/`>>>>>>>` markers, verifies correctness, and commits.

Contract:
```yaml
merge_status:
  type: string
  enum: [clean, conflict]
merge_commit_message: string
```

Writes: `[merge_status, merge_commit_message]`

#### `gate-conflict-resolved` (check, inside conflict-loop)

Evaluates `state.merge_status == "clean"`. `on_fail: retry_loop:conflict-loop`. Retries the conflict-loop when resolution left conflicts.

### `notify-merge-exhausted` (script)

No-op when `merge_status == "clean"`. On conflict exhaustion:

1. **Rescue-pushes the feature branch to remote** so in-progress work is accessible for manual inspection.
2. Posts a Linear comment with the conflict file list and branch name.
3. Resets the ticket to Todo state.

### `gate-merge-clean` (check)

Evaluates `state.merge_status == "clean"`. `on_fail: cancel`. Cancels if still conflicted after the conflict-loop. On cancellation, `push-base` and `teardown` do not run; the worktree is left for manual inspection.

### `push-base` (script)

Runs in the main repo (`cwd: "."`, resolved to `repo_root`). Pushes the base branch to origin:

```bash
git push origin "$1" >&2
printf '{}'
```

Args: `[$inputs.base_branch]`

### `teardown` (worktree.cleanup)

Policy: `delete_unconditionally`. Removes the worktree directory and force-deletes the local feature branch. At this point the branch has been merged into the base branch locally and the base branch has been pushed to origin; the local feature branch is safe to delete.

### `close-task` (script)

Queries Linear for the "completed" state ID and transitions the ticket to done. Runs from `cwd: "."` (the repo root, since the worktree was just deleted).

---

## State fields (derived)

| Field | Type | Written by |
|---|---|---|
| `worktree_path` | `Path` | `setup` |
| `worktree_branch` | `str` | `setup` |
| `ticket_title` | `str` | `fetch-ticket` |
| `ticket_description` | `str` | `fetch-ticket` |
| `target_claude_md` | `str` | `read-target-claude-md` |
| `verify_exit_code` | `int` | `verify` |
| `verify_output` | `str` | `verify` |
| `diff` | `str` | `capture-diff` |
| `verdict` | `str` | `review` |
| `issues` | `list[str]` | `verify` (append), `review` (replace) |
| `commit_message` | `str` | `review` |
| `deferred_brief` | `str` | `review` |
| `commit_sha` | `str` | `commit` |
| `merge_status` | `str` | `attempt-merge`, `resolve-conflicts` |
| `conflict_files` | `str` | `attempt-merge` |
| `merge_commit_message` | `str` | `resolve-conflicts` |

Plus `BaseState` fields: `run_id`, `workflow_name`, `base_branch`, `artifacts_dir`, `started_at`, `notes`.

---

## Prompts

### `prompts/implement-ticket.j2`

Instructs the agent to implement the changes for the ticket, showing the ticket title and description from state. Uses `target_claude_md` for repo context. Three phases: implement (TDD), verify, submit. On a retry (`state.issues` non-empty) it renders an "Open findings from the previous attempt" block that frames each finding as a description of an *underlying* problem — directing the agent to fix the root cause and the whole class of problem, not just the literal text or the cited example. This counters the failure mode where a fresh, stateless retry agent makes a shallow, literal fix.

### `prompts/review-ticket.j2`

Instructs the agent to review the implementation against the acceptance criteria. Embeds `state.diff` ("Changes under review") and `state.verify_output` so the read-only agent works from the actual change. Evaluates correctness, test coverage, focused diff, regressions. On FAIL, each element of `issues` must be a self-contained, actionable finding — *where, what, why, and what a correct fix looks like* — because the implementer is a fresh agent that sees only these strings (no memory of the review). Writes a commit message describing what was built. Calls submit once with `verdict`, `issues`, `commit_message`, and `deferred_brief`.

### `prompts/build/resolve-conflicts.j2`

Instructs the agent to resolve git merge conflicts. Reads each conflicting file (listed in `state.conflict_files`), resolves all conflict markers, runs the verify command, stages and commits, then submits with `merge_status` and `merge_commit_message`.

---

## Notable constraints

- `set-in-progress`, `notify-exhausted`, `handle-deferred`, `set-in-review`, `push-base`, `notify-merge-exhausted`, and `close-task` all use `printf '{}'` to emit an empty JSON object. This is the `writes: []` sidecar pattern — no contract, no state writes.
- The `commit` step sends git output to stderr (`>&2`) and only writes the JSON commit SHA to stdout, so the script contract can parse stdout cleanly.
- `teardown` uses `delete_unconditionally` because the feature branch is merged locally and the base branch has been pushed to `origin`; the local feature branch is ephemeral.
- The remote feature branch is **never created on the success path**. On the conflict-exhaustion failure path, `notify-merge-exhausted` rescue-pushes the feature branch; cleanup of that branch is a manual step.
- If `gate-exhausted` cancels the run (fix-loop exhaustion), `commit` and the entire merge phase never run. No merge, no push, no teardown.
- If `gate-merge-clean` cancels the run (conflict-loop exhaustion), `push-base` and `teardown` never run. The worktree is left for inspection; `cleanup_skipped=True` appears on the `workflow_failed` event.
- Linear API calls require `LINEAR_API_KEY` in the environment and `jq` on PATH.
- Cross-repo execution: set `--repo /path/to/target` (CLI flag, wires to `Runner.repo_root`) so main-repo steps with `cwd: "."` resolve to the target repository.
