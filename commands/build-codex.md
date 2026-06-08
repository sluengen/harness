<!-- guidance:build-codex@1.0.0 -->
# /build-codex — implement, verify, and review a Linear ticket (Codex review)

Usage: `/build-codex <TICKET-ID>`

Full build loop: fetches the ticket, implements it in an isolated worktree, verifies, reviews (Codex CLI), then commits and merges. Requires `LINEAR_API_KEY` in the environment and `codex` on `$PATH`.

---

## 1. Setup

Read `CONTEXT.md`. Note the integration branch (`base_branch`) and the verify/test command (`verify_command`). If either is absent, stop and tell the user what is missing.

Read `CLAUDE.md`. Store its full content as `claude_md` — you will pass it verbatim to the implement sub-agent.

**Mark the ticket In Progress.** Fetch the team's workflow states, find the "in progress" started-type state, and update:

```bash
NODES=$(curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"query{issue(id:\"TICKET_ID\"){team{states{nodes{id name type}}}}}"}' \
  | jq -c '.data.issue.team.states.nodes')
STATE_ID=$(printf '%s' "$NODES" \
  | jq -r 'map(select(.type=="started")) | (map(select((.name|ascii_downcase)=="in progress"))|first)//first|.id//empty')
[ -n "$STATE_ID" ] && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation{issueUpdate(id:\\\"TICKET_ID\\\",input:{stateId:\\\"${STATE_ID}\\\"}){success}}\"}" > /dev/null
```

**Fetch ticket content.** Store `ticket_title` and `ticket_description`:

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"query{issue(id:\"TICKET_ID\"){title description}}"}' \
  | jq '{title:.data.issue.title, description:(.data.issue.description//"")}'
```

**Create a worktree.** Store `worktree_path` and `worktree_branch`:

```bash
worktree_branch="build/$(date +%s)-${TICKET_ID,,}"
worktree_path="/tmp/worktrees/${TICKET_ID,,}"
git worktree add -b "$worktree_branch" "$worktree_path" "$base_branch"
```

---

## 2. Fix loop — up to 3 iterations

Track `issues` (list, starts empty) and `verdict`. On each iteration: implement → verify → review. Exit the loop when verdict is PASS or DEFER. If 3 iterations complete without that, go to **§4 Exhausted**.

### Implement

Spawn a sub-agent (Agent tool). Its working directory is `worktree_path`. It has Read, Write, Edit, Bash, Grep, Glob. It must not create git commits. Give it this prompt — fill all values before sending:

---

*Your working directory is `WORKTREE_PATH`. All file operations must happen inside it. Do not create git commits.*

*ISSUES_BLOCK — include only on retry:*
*## Prior findings — fix these before anything else*
*This is a retry. Each finding below is a real problem from the previous attempt. Fix the root cause — not just the cited instance. If a finding names one file as an example, fix the whole class of problem it points to.*
*- ISSUE_1*
*- ISSUE_2*
*...*

*## Ticket*

*TICKET_TITLE*

*TICKET_DESCRIPTION*

*## Implementation*

*Follow the conventions in this project's CLAUDE.md:*

*CLAUDE_MD*

*Before finishing:*
*- Update any spec or documentation that refers to code you just changed*
*- Fix obvious inefficiencies introduced or exposed by the change (e.g. N+1 queries)*
*- Remove dead code, stale comments, or placeholder markers on things you just shipped*

*Run LINT_COMMAND and fix any errors before stopping.*

---

Wait for the sub-agent to complete before continuing.

### Verify

Run the verify command inside the worktree:

```bash
cd "$worktree_path" && eval "$verify_command" 2>&1
```

If it exits non-zero: add a finding to `issues` — `"Verify gate failed (exit CODE):\nOUTPUT"` — and restart the iteration (back to **Implement**).

### Review (Codex)

Capture the diff:

```bash
cd "$worktree_path" && git diff "$base_branch"...HEAD 2>/dev/null
```

Build the review prompt — fill all values — and write it to `/tmp/review_TICKET_ID.txt`:

```
Review the implementation of TICKET_ID — **TICKET_TITLE**.

## Acceptance criteria

TICKET_DESCRIPTION

## Project conventions

CLAUDE_MD

## Verification

The verify gate passed. Output for reference:

VERIFY_OUTPUT

## Changes under review

```diff
DIFF
```

## Review criteria

Evaluate: correctness against the acceptance criteria, adherence to the project conventions, adequate test coverage, focused diff (no drive-by changes), no obvious regressions. Use Read/Grep on surrounding files for context where needed. Be concrete — point to file and line.

## Verdict — choose exactly one

- **PASS** — correct, tested, focused; nothing to report. `issues` must be empty.
- **FAIL** — fixable findings. One finding per item in `issues`. Each must be self-contained: state where (file:line), what's wrong, why, and what a correct fix looks like. The next implement agent has no memory of this round — write each finding actionable cold.
- **DEFER** — shippable; one finding is genuinely out of scope (architectural redesign or a separate spec required). Write `commit_message` and `deferred_brief`.

## Commit message

Required for PASS and DEFER: `type(scope): description`, one line, under 72 chars.

## Output

End your response with exactly one line:

SUBMIT: {"verdict":"PASS|FAIL|DEFER","issues":[...],"commit_message":"...","deferred_brief":"..."}
```

Run Codex:

```bash
codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral - < /tmp/review_TICKET_ID.txt
```

Scan stdout for the first line starting with `SUBMIT:`. Parse the JSON. Store `verdict`, `issues`, `commit_message`, `deferred_brief`.

If no valid `SUBMIT:` line appears: treat as FAIL with issue `"Codex reviewer did not emit a valid SUBMIT line"` and restart the iteration.

Act on verdict: PASS or DEFER → **§3 Ship**; FAIL → restart the iteration.

---

## 3. Ship

**Handle DEFER.** If verdict is DEFER, fetch the team ID then create a child ticket:

```bash
TEAM_ID=$(curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"query{issue(id:\"TICKET_ID\"){team{id}}}"}' \
  | jq -r '.data.issue.team.id')
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d "$(jq -n --arg t "$TEAM_ID" --arg title "DEFERRED_BRIEF" --arg p "TICKET_ID" \
    '{"query":"mutation{issueCreate(input:{teamId:$t,title:$title,parentId:$p}){success}}"}')" > /dev/null
```

**Set In Review.** Same pattern as set-in-progress, targeting a started-type state whose name matches "in review".

**Commit.** In the worktree:

```bash
cd "$worktree_path" && git add -A && git commit -m "COMMIT_MESSAGE"
```

**Merge.** From the main checkout:

```bash
git checkout "$base_branch"
git merge --no-ff "$worktree_branch"
```

If conflicts arise: spawn a sub-agent (Read, Edit, Bash) to resolve them, then run `git add -A && git merge --continue --no-edit`. If conflicts remain after 2 attempts, push the feature branch (`git push -u origin "$worktree_branch"`), reset the ticket to Todo, comment explaining what happened, and stop.

**Push and teardown:**

```bash
git push origin "$base_branch"
git worktree remove --force "$worktree_path"
git branch -d "$worktree_branch" 2>/dev/null || true
```

**Close the ticket:**

```bash
STATE_ID=$(curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"query{issue(id:\"TICKET_ID\"){team{states{nodes{id type}}}}}"}' \
  | jq -r '.data.issue.team.states.nodes[]|select(.type=="completed")|.id' | head -1)
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation{issueUpdate(id:\\\"TICKET_ID\\\",input:{stateId:\\\"${STATE_ID}\\\"}){success}}\"}" > /dev/null
```

---

## 4. Exhausted

3 iterations completed without a PASS or DEFER. Comment on the ticket:

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" -H "Content-Type: application/json" \
  -d "$(jq -n --arg id "TICKET_ID" \
    --arg body "Build loop exhausted after 3 iterations. Branch: WORKTREE_BRANCH.\n\nFindings:\nISSUES" \
    '{"query":"mutation{commentCreate(input:{issueId:$id,body:$body}){success}}"}')" > /dev/null
```

Reset the ticket to Todo (same pattern as set-in-progress, targeting `type=="unstarted"`). Teardown the worktree. Report the findings to the user.
