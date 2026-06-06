# Build Workflow — merge-to-base phase and fix-loop cleanup

**Status:** Proposed  
**Scope:** `workflows/build.yaml`, `workflows/build-codex.yaml`, `prompts/build/`

---

## Problems

1. **No merge to base.** The workflow ends at `commit-and-push`, which pushes the feature branch to `origin` but never merges it into `dev`. Feature branches accumulate on the remote; delivery is incomplete without manual intervention.

2. **`read-target-claude-md` runs on every fix-loop iteration.** CLAUDE.md doesn't change between retries — it should run once before the loop.

3. **`set-in-review` fires on every fix-loop iteration.** On retry iterations the ticket is already "In Review" while `implement` is running — the status is wrong and the Linear API call is redundant. It belongs after the loop exits, once, right before the commit.

---

## Design

### Full step order (success path)

```
setup
set-in-progress
fetch-ticket
read-target-claude-md       ← hoisted out of fix-loop (runs once)
     │
     ▼
┌─── fix-loop (max_iterations: 3) ───────────────────────────────────────┐
│  implement ──► review ──► gate-retry                                    │
│                            │  FAIL → back to top                        │
│                            │  PASS / DEFER → exit loop                  │
└────────────────────────────────────────────────────────────────────────-┘
     │
notify-exhausted             (no-op on PASS/DEFER; posts comment + resets to Todo on exhaustion)
gate-exhausted               (cancel on still-FAIL)
handle-deferred              (no-op on PASS; creates child ticket on DEFER)
set-in-review                ← hoisted out of fix-loop (runs once, on commit path only)
commit                       ← renamed from commit-and-push; no push
     │
     ▼
attempt-merge                (merge local feature branch → base branch in main repo)
     │
     ├─ clean ──────────────────────────────────────────────────────────►─┐
     │                                                                     │
     └─ conflict                                                           │
          │                                                                │
          ▼                                                                │
┌─── conflict-loop (max_iterations: 2) ──────────────────────────────┐   │
│  resolve-conflicts (ai) ──► gate-conflict-resolved                  │   │
│                               │  still conflict → back to top       │   │
│                               │  clean → exit loop                  │   │
└─────────────────────────────────────────────────────────────────────┘   │
     │ (exit: merge_status == "clean" or loop exhausted)                   │
     ▼                                                                     │
notify-merge-exhausted       (no-op on clean; rescue-pushes feature branch on exhaustion;
     │                        Linear comment + Todo reset are best-effort side effects)
gate-merge-clean             (cancel on still-conflict)
     │                                                                     │
     ◄─────────────────────────────────────────────────────────────────────┘
     ▼
push-base                    (git push origin <base_branch>)
teardown                     (removes worktree + local feature branch)
close-task
```

The **remote feature branch is never created on the success path.** The feature branch lives only in the local worktree until `teardown` deletes it. On the conflict-exhaustion failure path, `notify-merge-exhausted` rescue-pushes the feature branch to remote so the work is accessible for manual inspection.

---

## Changes to existing steps

### `read-target-claude-md` — hoist out of `fix-loop`

Move from inside `fix-loop` to a top-level step between `fetch-ticket` and `fix-loop`. No change to the step itself.

### `set-in-review` — hoist out of `fix-loop`

Move from inside `fix-loop` (where it fired before every `review`) to a top-level step between `handle-deferred` and `commit`. It now fires exactly once, on the commit path, when implementation is genuinely ready for human review. No change to the step itself.

### `commit` (renamed from `commit-and-push`)

Remove the `git push` line. The step commits and reports the SHA; pushing is handled later by `push-base` (success) or `notify-merge-exhausted` (failure rescue).

```bash
git add -A >&2
git commit --amend -m "$2" >&2
printf '{"commit_sha": "%s"}' "$(git rev-parse HEAD)"
```

Args: `[$state.worktree_branch, $state.commit_message]`  
Contract / writes: unchanged — `{commit_sha: string}`, writes `[commit_sha]`.

---

## New steps

### `attempt-merge` (script)

Runs in the **main repo** (`cwd: "."`). Switches to the base branch and merges the local feature branch with `--no-ff`. No fetch needed — the feature branch exists locally in the worktree.

```bash
git checkout "$BASE_BRANCH" >&2
if git merge --no-ff "$FEATURE_BRANCH" >&2; then
  printf '{"merge_status": "clean", "conflict_files": ""}'
else
  CONFLICTS=$(git diff --name-only --diff-filter=U | tr '\n' ',' | sed 's/,$//')
  printf '{"merge_status": "conflict", "conflict_files": "%s"}' "$CONFLICTS"
fi
```

Args: `[$inputs.base_branch, $state.worktree_branch]`

Contract:

```yaml
contract:
  merge_status: string    # "clean" | "conflict"
  conflict_files: string  # comma-separated; empty string when clean
writes: [merge_status, conflict_files]
```

The worktree is still alive on the feature branch when this runs. Git worktrees allow concurrent branch checkouts, so switching the main repo to `base_branch` is safe.

---

### `conflict-loop` (loop)

Only traversed when `merge_status == "conflict"`. Uses `on_exhaust: continue` so the post-loop steps handle the failure path.

```yaml
- id: conflict-loop
  type: loop
  loop:
    max_iterations: 2
    until: 'state.merge_status == "clean"'
    on_exhaust: continue
    steps:

      - id: resolve-conflicts
        type: ai
        agent: claude
        model: sonnet
        cwd: "."
        prompt: prompts/build/resolve-conflicts.j2
        allowed_tools: [Read, Write, Edit, Bash, Grep, Glob]
        writes_files: true
        contract:
          merge_status:
            type: string
            enum: [clean, conflict]
          merge_commit_message: string
        writes: [merge_status, merge_commit_message]

      - id: gate-conflict-resolved
        type: check
        expr: 'state.merge_status == "clean"'
        on_fail: "retry_loop:conflict-loop"
```

`max_iterations: 2` — if the AI cannot resolve conflicts in two attempts, the conflict is likely semantic and requires human judgment. A third attempt with the same context won't help.

The `resolve-conflicts` AI step runs in `cwd: "."` (main repo root) because the merge conflict lives in the main checkout. The agent:

1. Reads each file listed in `state.conflict_files`
2. Resolves all `<<<<<<<` / `=======` / `>>>>>>>` markers — prefer feature branch intent for functionality, base branch for infrastructure/config unless the feature explicitly changes it
3. Runs the verify command to confirm correctness
4. Runs `git add -A && git commit -m "merge: <feature> into <base>"`
5. Emits `{merge_status: "clean", merge_commit_message: "<msg>"}` on success, or `{merge_status: "conflict", merge_commit_message: ""}` if it cannot resolve and verify (never commit broken code)

---

### `notify-merge-exhausted` (script)

No-op when `merge_status == "clean"`. On exhaustion (still conflict), this step:

1. **Rescue-pushes the feature branch to remote** so the in-progress work is accessible
2. Posts a Linear comment with the conflict file list and branch name
3. Resets the ticket to Todo

```yaml
- id: notify-merge-exhausted
  type: script
  cwd: "."
  command: |
    MERGE_STATUS="$1"
    LINEAR_ID="$2"
    BRANCH="$3"
    CONFLICTS="$4"
    if [ "$MERGE_STATUS" = "conflict" ]; then
      git push -u origin "$BRANCH" >&2
      TODO_STATE_ID=$(curl -s -X POST https://api.linear.app/graphql \
        -H "Authorization: $LINEAR_API_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"query\":\"query{issue(id:\\\"${LINEAR_ID}\\\"){team{states{nodes{id type}}}}}\"}" \
        | jq -r '.data.issue.team.states.nodes[] | select(.type=="unstarted") | .id' \
        | head -1)
      COMMENT=$(printf 'Merge conflict loop exhausted. Feature branch pushed for manual inspection: %s\n\nConflicting files: %s\n\nResolve manually and push.' "${BRANCH}" "${CONFLICTS}")
      curl -s -X POST https://api.linear.app/graphql \
        -H "Authorization: $LINEAR_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg issue_id "$LINEAR_ID" --arg body "$COMMENT" \
          '{"query":"mutation{commentCreate(input:{issueId:\($issue_id),body:\($body)}){success}}"}')" \
        > /dev/null
      curl -s -X POST https://api.linear.app/graphql \
        -H "Authorization: $LINEAR_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$(jq -n --arg id "$LINEAR_ID" --arg state_id "$TODO_STATE_ID" \
          '{"query":"mutation{issueUpdate(id:\($id),input:{stateId:\($state_id)}){success}}"}')" \
        > /dev/null
    fi
    printf '{}'
  args: ["$state.merge_status", "$inputs.linear_id", "$state.worktree_branch", "$state.conflict_files"]
  writes: []
```

---

### `gate-merge-clean` (check)

```yaml
- id: gate-merge-clean
  type: check
  expr: 'state.merge_status == "clean"'
  on_fail: cancel
```

Cancels if still conflicted. The feature branch was rescue-pushed by `notify-merge-exhausted`. The worktree and local branch are left in place for inspection (`teardown` does not run on cancel).

---

### `push-base` (script)

```yaml
- id: push-base
  type: script
  cwd: "."
  command: |
    git push origin "$1" >&2
    printf '{}'
  args: ["$inputs.base_branch"]
  writes: []
```

---

## Removed step

`prune-remote-branch` — eliminated. The remote feature branch is never created on the success path, so there is nothing to prune. On the failure path, `notify-merge-exhausted` pushes the branch as a rescue operation; cleanup of that branch is a manual step.

---

## New prompt: `prompts/build/resolve-conflicts.j2`

```jinja
You are resolving a git merge conflict in this repository.

## Context

Feature branch `{{ state.worktree_branch }}` was being merged into `{{ inputs.base_branch }}`.
The merge left conflicts in the following files:

{{ state.conflict_files }}

## Task

1. Read each conflicting file and resolve all `<<<<<<<` / `=======` / `>>>>>>>` markers.
   Prefer the feature branch's changes for functionality. Prefer the base branch's version
   for infrastructure or configuration unless the feature explicitly changes them.

2. Run the verify command to confirm the resolved code is correct:
   ```
   {{ inputs.verify_command | default('bash scripts/verify.sh') }}
   ```
   If verification fails, fix the issues before committing.

3. Stage and commit:
   ```bash
   git add -A
   git commit -m "merge: {{ state.worktree_branch }} into {{ inputs.base_branch }}"
   ```

4. Submit with:
   - `merge_status`: `"clean"` if the commit succeeded and verify passed.
     `"conflict"` if you were unable to fully resolve and verify — do not commit broken code.
   - `merge_commit_message`: the commit message used, or empty string on conflict.
```

---

## State fields (new)

| Field | Type | Written by |
|---|---|---|
| `merge_status` | `str` | `attempt-merge`, `resolve-conflicts` |
| `conflict_files` | `str` | `attempt-merge` |
| `merge_commit_message` | `str` | `resolve-conflicts` |

---

## What does NOT change

- `teardown` — `delete_unconditionally` removes worktree directory and local branch. Unchanged.
- `close-task` — marks Linear ticket done. Unchanged.
- `notify-exhausted` / `gate-exhausted` / `handle-deferred` — fix-loop failure handling. Unchanged.
- On fix-loop exhaustion, the cancel from `gate-exhausted` stops execution before `commit` and the entire merge phase. No merge, no push, no teardown.
- On conflict exhaustion, the cancel from `gate-merge-clean` stops execution before `push-base` and `teardown`. The feature branch was rescue-pushed; the worktree is left for inspection.

---

## Applies to both workflows

Both `build.yaml` and `build-codex.yaml` need all changes. The only difference between them remains the `review` step's `agent: claude` vs `agent: codex`. All other steps are identical.

---

## Implementation order

1. **Workflow** — hoist `read-target-claude-md` and `set-in-review` out of `fix-loop` in both YAMLs.
2. **Workflow** — rename `commit-and-push` → `commit`, remove the `git push` line.
3. **Prompt** — write `prompts/build/resolve-conflicts.j2`.
4. **Workflow** — add `attempt-merge`, `conflict-loop`, `notify-merge-exhausted`, `gate-merge-clean`, `push-base` between `commit` and `teardown` in both YAMLs.
5. **Tests** — unit test `attempt-merge` (clean path, conflict path); integration test for clean merge end-to-end.
