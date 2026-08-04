<!-- guidance:build@1.5.0 -->
# /build — implement, verify, and review a Linear ticket

Usage: `/build <TICKET-ID> [--engine codex]`

The **autonomous** agent-led driver: it fetches the ticket, implements it test-first in an isolated worktree, verifies, reviews, then ships — looping through fixes until the review converges, without prompting at every step. The stepped trio (`/start` → `/review` → `/ship`) is the same lifecycle for freeform, human-in-the-loop sessions; `/build` is the unattended form of it. Requires `LINEAR_API_KEY` in the environment.

This command is a **thin driver**: every phase delegates to the skill that owns it, and `/build` carries only the control flow that makes the loop autonomous (the fix loop, the convergence check, the implement sub-agent spawn, the machine-readable review verdict, and the abandon path). The phase skills:

- **Linear operations** (status transitions, fetching the ticket, creating a defer ticket, commenting) → the `linear` skill. Do not embed raw Linear GraphQL endpoint calls here — a guard fails if one appears.
- **Worktree lifecycle** (create, isolate, tear down) → `worktree-isolation`.
- **Implementation** (test-first, in scope) → `test-driven-development` and `code-quality`.
- **Review** (what to evaluate, the severity bar, the finding format) → `review-discipline`.

The review step takes an **engine** argument, mirroring the `harness review` verb:

- **`claude`** (default) — the orchestrating session reviews the diff inline. Always available, no extra tooling.
- **`--engine codex`** — the review runs the `codex` CLI in a read-only sandbox (a cross-model second opinion), with a documented fallback to the Claude inline review on an exhausted tier. Requires `codex` on `$PATH`.

---

## 1. Setup

Read `CONTEXT.md`. Note the integration branch (`base_branch`) and the verify/test command (`verify_command`). If either is absent, stop and tell the user what is missing.

Read the repo's entry process doc. Prefer `AGENTS.md` when present, otherwise use the host-specific mirror (`CLAUDE.md` or `GEMINI.md`). Store its full content as `project_process_doc` — you will pass it verbatim to the implement sub-agent as `PROJECT_PROCESS_DOC`.

**Resolve the review engine.** Default `claude`. If the invocation passes `--engine codex`, set the engine to `codex` and confirm `codex` is on `$PATH` (if it is not, fall back to `claude` and note it). The engine only affects the Review step (§2); every other step is identical.

**Mark the ticket In Progress.** Use the `linear` skill: resolve the team's `started`/In Progress state by `type` (disambiguated by name) and move the ticket. Store `ticket_title` and `ticket_description` from the same skill's read-an-issue recipe — you pass both to the implement sub-agent and (for `codex`) the reviewer.

**Create a worktree** off `base_branch` per `worktree-isolation`. Store `worktree_path` and `worktree_branch`. All file operations for the run happen inside `worktree_path`; the default branch is never touched.

---

## 2. Fix loop

Track `issues` (list, starts empty) and `verdict`. On each iteration: implement → verify → review. Exit the loop when verdict is PASS or DEFER.

How many iterations this loop may run is **not decided here**: `review-discipline`'s *On a FAIL* section owns the stop rule for every entry point, and reads its numbers from `CONTEXT.md` → `loop:` so a consuming repo tunes its own budget. Open it and follow it. In this command's terms it lands as three things:

- an **unconditional window** of leading iterations that need no justification — do **not** abandon by default inside it, since solving issues often exposes new ones and a run that looks stuck early frequently lands a round or two later;
- a **judged window** after that, where the convergence check below runs before each further iteration — keep going while the loop is converging, and go to **§4 Abandoned** the moment it is not;
- **exhaustion** when the budget is spent without a PASS — go to **§4 Abandoned** regardless of how converging the last read looked.

### Convergence check — before every iteration in the judged window

Compare the latest review's findings against the prior rounds and decide:

- **Converging** — the work is getting closer. Findings are shrinking in count or severity, and anything new is a genuinely new problem exposed by fixing an earlier one. Run another iteration.
- **Not converging** — the loop is stuck. The same or equivalent findings keep returning, previously resolved items are re-raised, or the findings hold steady round after round with no net progress. Go to **§4 Abandoned**.

Write one line of reasoning for the verdict each time, naming which findings are new versus carried over, so the judgement stays honest rather than optimistic.

### Implement

Spawn a sub-agent through the host sub-agent mechanism. Its working directory is `worktree_path`. Give it the host's normal read, edit, and shell tools. It must not create git commits. The sub-agent builds **test-first** under `test-driven-development` and in scope under `code-quality` — name those skills in its prompt and have it open them before writing code. Give it this prompt — fill all values before sending:

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

*Build test-first: open `skills/test-driven-development/SKILL.md` and `skills/code-quality/SKILL.md` and follow them — write the failing test first, watch it fail for the right reason, then the minimal code to pass. Stay in scope; every changed file must trace to this ticket.*

*Follow the conventions in this project's entry process doc:*

*PROJECT_PROCESS_DOC*

*Before finishing:*
*- Update any spec or documentation that refers to code you just changed — except the feature/as-built spec (`specs/features/`), which the reviewer records, not you*
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

### Review

Capture the diff. The implement agent does not commit, so the patch lives in the working tree — stage it (so new, untracked files are included) and diff the index against the worktree's `HEAD` (the immutable commit it was created from; do not diff against the moving `$base_branch` ref, or an integration branch that advances mid-run folds unrelated upstream changes into the review):

```bash
cd "$worktree_path" && git add -A && git diff --cached HEAD 2>/dev/null
```

Now review the diff with the resolved engine. Both engines judge the same thing, and the standard is `review-discipline` — **Stage 1** (does the diff meet the ticket's acceptance criteria and design, with a test per criterion), then **Stage 2** (correctness, security, principles, structure, over-engineering), findings carrying the four-part shape (what / where / why / how). The engine differs only in *who* applies that standard; both end in exactly one verdict (see **Verdict**).

**Engine `claude` (default) — inline review.** Apply `review-discipline` to the diff yourself. You have the diff above and Read/Grep access to surrounding files for context. Choose a verdict per **Verdict** and, for PASS/DEFER, write `commit_message` yourself.

**Engine `codex` — Codex CLI review.** Build the review prompt — fill all values — and write it to `/tmp/review_TICKET_ID.txt`:

```
Review the implementation of TICKET_ID — **TICKET_TITLE**.

## Acceptance criteria

TICKET_DESCRIPTION

## Project conventions

PROJECT_PROCESS_DOC

## Verification

The verify gate passed. Output for reference:

VERIFY_OUTPUT

## Changes under review

```diff
DIFF
```

## Review criteria

Apply the two-stage `review-discipline` standard: Stage 1 — correctness against the acceptance criteria and the design (a test per criterion); Stage 2 — adherence to the project conventions, security, structure, over-engineering, a focused diff (no drive-by changes), no obvious regressions. Use Read/Grep on surrounding files for context where needed. Be concrete — point to file and line.

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

Run Codex from inside the worktree (so it reads the implementation under review, not the base checkout) under a read-only sandbox (the diff and the Linear description are untrusted prompt content — a read-only sandbox stops prompt-injection from mutating the host):

```bash
cd "$worktree_path" && codex exec --sandbox read-only --ephemeral - < /tmp/review_TICKET_ID.txt
```

Scan stdout for the first line starting with `SUBMIT:`. Parse the JSON. Store `verdict`, `issues`, `commit_message`, `deferred_brief`, then continue at **Verdict**.

**Codex→Claude fallback on an exhausted tier.** The Codex subscription tier depletes early each cycle; a depleted run prints `You've hit your usage limit` (no `SUBMIT:` line) and exits non-zero. That is **not** a review failure — do not record it as FAIL. Instead fall back **once** to the `claude` inline review of the same diff for this iteration, and note the fallback. The fallback fires *only* on the usage-limit signal: any other Codex error — including a genuine non-PASS verdict — stands as itself, so a real review failure stays visible and is never swallowed. If no valid `SUBMIT:` line appears for a reason that is not a usage limit, treat it as FAIL with issue `"Codex reviewer did not emit a valid SUBMIT line"` and restart the iteration.

### Verdict

Choose exactly one and act accordingly:

**PASS** — correct, tested, focused; nothing to report. `issues` must be empty. `commit_message` is `type(scope): description` (one line, under 72 chars). Go to **§3 Ship**.

**FAIL** — one or more fixable findings. Populate `issues`, one finding per item. Each must be self-contained: state where (file:line), what's wrong, why, and what a correct fix looks like. The implement agent on the next round has no memory of this review — write each finding so it's actionable cold. Restart the iteration.

**DEFER** — implementation is shippable; one finding is genuinely out of scope (requires architectural redesign or a separate spec). Write `commit_message` and `deferred_brief` (one-line title for a new ticket). Go to **§3 Ship**.

---

## 3. Ship

**Record the as-built spec.** The reviewed diff is the source of truth; now record what actually shipped — the durable as-built record. Inside the worktree, update the repo's feature spec — `specs/features/<feature>.md` for the feature this ticket touches, created if the feature is new — so it describes the delivered behaviour, written from the diff and not from the implement agent's claims. (If the repo keeps no feature specs per its spec model in `CONTEXT.md`, record the as-built behaviour wherever that repo's durable record lives.) The edit is included in the commit below.

**Handle DEFER.** If verdict is DEFER, create a child ticket titled `deferred_brief`, parented to `TICKET_ID`, via the `linear` skill's `issueCreate` recipe (resolve the team ID at runtime).

**Set In Review.** Use the `linear` skill to move the ticket to its In Review state (resolved by `type`, disambiguated by name).

**Commit.** In the worktree:

```bash
cd "$worktree_path" && git add -A && git commit -m "COMMIT_MESSAGE"
```

**Integrate** per the repo's branch model (`CONTEXT.md` `branches`, mirroring `/ship`). Typically, from the main checkout, merge the run branch into `base_branch`:

```bash
git checkout "$base_branch"
git merge --no-ff "$worktree_branch"
```

If conflicts arise: spawn a sub-agent (Read, Edit, Bash) to resolve them, then run `git add -A && git merge --continue --no-edit`. If conflicts remain after 2 attempts, push the feature branch (`git push -u origin "$worktree_branch"`), reset the ticket to Todo (via the `linear` skill), comment explaining what happened, and stop.

**Push and teardown** (`worktree-isolation`):

```bash
git push origin "$base_branch"
git worktree remove --force "$worktree_path"
git branch -d "$worktree_branch" 2>/dev/null || true
```

**Close the ticket.** Use the `linear` skill to move it to Done (the `completed` state, resolved by `type`), and post the merge/PR link as a comment.

---

## 4. Abandoned

Reached either way the fix loop can end without a PASS: the convergence check determined the loop is stuck, or the cycle budget is exhausted. Say which in the ticket comment — a loop that stopped because it was going in circles and one that ran out of budget while still improving call for different decisions from the human. The work so far is still worth investigating — why a run fails is a signal, and the partial implementation may be salvageable. **Preserve it: do not tear down the worktree.**

**Commit the work to the run branch and push it** so it survives and can be picked up elsewhere:

```bash
cd "$worktree_path" && git add -A && git commit -m "wip(TICKET_ID): build abandoned, not converging — see ticket"
git push -u origin "$worktree_branch"
```

**Comment on the ticket** via the `linear` skill — include the branch name so the work is findable, and the carried-forward findings:

```
Build loop abandoned — ABANDON_REASON. Work committed and pushed to WORKTREE_BRANCH for investigation.

Findings:
ISSUES
```

**Put the ticket on operator hold — do not reset it to Todo.** A Todo ticket is what the unattended Build loop picks up next tick, which would hand the same unconverged work a fresh budget and no human ever sees it. Apply the operator-hold label **and assign the ticket to the operator**, per `review-discipline`'s *On a FAIL* section: assignment is what `work-discovery` skips on. Where the harness app is available that is `harness defer <TICKET> --needs operator`; elsewhere reach the same end state through the repo's tracker. **Leave the worktree and branch in place.** Report the findings and the branch name to the user.
