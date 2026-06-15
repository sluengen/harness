# /harness — Harness pipeline commands

Commands for driving the **harness pipeline itself**. `/harness run` is the canonical end-to-end build process for this repo: an agent-orchestrated loop over the three harness verbs (`start`, `review`, `close`). It is distinct from the agent-led backup flow (`/start`, `/review`, `/ship`), which you run when a task does not fit this shape.

---

## /harness run \<ISSUE-ID\>

Drive a Linear ticket end-to-end by orchestrating the three harness verbs: **start → implement → review → (fix → review)\* → close**.

This is **not** a wrapper that hands the ticket to a black-box workflow. *You* — the orchestrating Claude session — run the loop: you call each verb, you write the code and tests inline in the worktree, you read each verdict and act on it. The verbs own every git and tracker mutation; you own the implementation and the control flow between them.

**Why the verbs, and nothing else, touch state (D5):** each verb appends to a single `runs` ledger — `start` opens the row, `review` records a verdict bound to the reviewed SHA, `close` enforces the gate and finalizes. That ledger is the whole audit trail. If you hand-roll a `git merge`, a `git push`, or a Linear GraphQL mutation to move state yourself, the ledger no longer reflects reality and the gate can no longer protect the merge. So: **never** run raw git state-transitions or Linear CURL for the lifecycle in this loop — route every mutation through a verb.

### Usage

- `/harness run <ISSUE-ID>` — orchestrate the build loop for the given Linear ticket

### Prerequisites

`harness` must be on your `PATH` as the Docker wrapper (`~/bin/harness`). If it isn't yet, see `docker/README.md` — one `chmod +x` and a `PATH` line in `.zshrc`. Each verb runs as a one-shot container exactly as the wrapper does: CWD mounted as the workspace, `LINEAR_API_KEY` read from `.env`. You shell out to the verbs from your session — you do **not** run inside a verb container.

`LINEAR_API_KEY` must be in a `.env` file at the target repo root (gitignored). The wrapper reads it automatically — no `source .env` needed.

```bash
# .env (in the target repo root)
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxx   # from linear.app → Settings → API → Personal API keys
```

> **No Linear CLI is installed**, and you do not call Linear directly in this loop anyway — the verbs do. (`start` transitions the ticket to In Progress; `close` transitions it Done.) Do not search for a `linear` binary or hand-roll GraphQL mutations to move ticket state.

> **Claude auth is automatic.** The wrapper extracts the OAuth token from the macOS Keychain on each invocation. No `ANTHROPIC_API_KEY` or manual token setup needed.

### The loop

**Step 1 — `start`.** Open the run and the worktree:

```bash
harness start <ISSUE-ID>            # [--base dev] [--repo .]
```

It validates the ticket, transitions it to In Progress, creates the worktree, and opens a `runs` ledger row. It emits one JSON object (`StartOutput`):

```json
{ "run_id": "...", "ticket": { "identifier": "...", "title": "...", "description": "...", "url": "..." },
  "worktree_path": "...", "worktree_branch": "...", "base_branch": "..." }
```

Parse it. **Record `run_id`** (you need it for `status`, `review`, and `close`). `cd` into `worktree_path`. Read `ticket.title` and `ticket.description` — that is your spec for this run. (Default base is `dev`; pass `--base` only to override.)

**Step 2 — implement.** Write the code and tests in the worktree, **test-first** per this repo's `CLAUDE.md` (write the failing test, watch it fail for the right reason, then make it pass). Stay in scope — every changed file must trace to the ticket. Run the repo's verify gate locally as you go.

**Step 3 — `review`.** When the implementation is ready, review the current worktree HEAD:

```bash
harness review --run-id <run_id>                  # [--repo .] — engine defaults to claude
harness review --run-id <run_id> --engine codex   # opt into a Codex cross-model review
```

The selected engine (`--engine claude|codex`, **default `claude`**) reviews the diff against HEAD and records a verdict bound to that SHA. Both engines are **read-only CLI subprocesses** emitting the same `SUBMIT:` contract — never the Agent SDK; the engine's full reasoning stays inside the verb. You see only the bounded result (`ReviewOutput`), which records the `engine` that produced the verdict:

```json
{ "verdict": "pass|fail|defer", "issues": [ ... ], "reviewed_sha": "...", "run_id": "...", "engine": "claude|codex" }
```

`claude` is the default because it is available on the standard tier and auto-compacts, so the gate does not degrade to a false `fail` when the Codex tier is depleted; `--engine codex` stays available for a cross-model second opinion.

Act on `verdict`:

- **`fail`** — fix the listed `issues` in the worktree (fix the root cause, not just the cited line), then **re-run `harness review`**. This is the `(fix → review)*` loop; repeat until the verdict is `pass` or `defer`. Each new review binds to the new HEAD.
- **`defer`** — the implementation is shippable, but the review surfaced a genuinely out-of-scope finding (needs its own spec or a redesign). Handle the finding by **filing a follow-up** — use `/harness ingest` to create a child ticket capturing it — then proceed to close.
- **`pass`** — proceed to close.

**Step 4 — `close`.** Finalize through the gate:

```bash
harness close <ISSUE-ID> --run-id <run_id>    # [--repo .]
```

`close` enforces the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA equals the current HEAD), then commits, merges, pushes, transitions the ticket Done, and marks the run closed. On success it emits `CloseOutput`:

```json
{ "run_id": "...", "ticket": "...", "reviewed_sha": "...", "merged": true, "ticket_done": true, "status": "..." }
```

### Gate-refusal handling

If `close` refuses, it exits non-zero with `{"error": ..., "reason": ...}`. The `reason` is one of:

- **`no_run`** — no `start` row exists for this ticket. You skipped `start`, or are closing the wrong ticket. Run `harness start` first.
- **`dirty_worktree`** — the worktree has uncommitted changes; what would merge was never reviewed. Commit (or discard) the edits, **re-run `harness review`** to bind a fresh `pass` to the new HEAD, then close again.
- **`no_passing_review`** — no `verdict=pass` is on record. You have not run `review`, or its last verdict was `fail`/`defer`. Run `harness review` and reach `pass`.
- **`stale_review`** — there is a passing review, but HEAD moved after it (you committed more work). The passing verdict no longer covers what would merge. **Re-run `harness review`** on the current HEAD to re-establish a fresh `pass`, then close again.

A gate refusal is the gate doing its job. **Do not work around it** — do not hand-roll the merge/push/transition to "finish" the run. If the refusal is something you cannot resolve by re-running a verb (e.g. an unexpected error, or a verb that itself fails), **surface it to the human / Hermes** with the `reason` and the `run_id`; do not improvise a bypass.

### Context economy / compaction

The plan you are following lives only in this session's context — the ledger and the worktree are the durable record. If context is lost or compacted mid-run:

- **Re-orient via the ledger.** Run `harness status <run-id> [--json]` to get the run's terminal-state summary, and inspect the worktree (`git status`, `git log`, the diff) to see what is already implemented. The ledger + worktree are the source of truth — trust them over a half-remembered plan.
- **Checkpoint intent before you risk losing it.** Commit WIP in the worktree and/or write the remaining plan into the ticket or a scratch note, so the one thing that lives only in context survives a compaction. (A `CLAUDE.md` "Compact Instructions" section is an optional refinement, not required.)

---

## /harness ingest \<description\>

Accept user intent, structure it into an agent-ready Linear issue, and create it.

### Usage

- `/harness ingest <description>` — describe what you want; Claude structures and creates the issue
- `/harness ingest` — Claude prompts for intent first

### When to use

- You have an idea, bug, or task you want the harness to work on
- You want to queue something for `/harness run` without hand-writing the issue
- You need to convert a rough note into a spec the implementing agent can act on

### Protocol

**Step 1 — Gather intent**

If a description was provided, use it. If not, ask in one turn:

> What do you want done? Describe the goal, and optionally: what triggered it, how you'll know it's done, any constraints.

Do not ask follow-up questions. One prompt is enough; infer the rest from what the user provides.

**Step 2 — Draft the issue**

**Title** — concise action phrase, verb-first, under 80 characters.

**Description** — Markdown written for the implementing agent, not a human reader. The agent reads this cold with no conversation context, so it must be self-contained.

```markdown
## Context
<One or two sentences: why this matters, what triggered it, relevant background.>

## Goal
<What done looks like. One or two sentences.>

## Acceptance criteria
- [ ] <Specific, observable, checkable item>
- [ ] <Specific, observable, checkable item>
- [ ] Tests cover the new behaviour

## Technical notes
<Optional. Approach hints, files to look at, known constraints, SPEC references.>

## Out of scope
<Optional. Explicit guard rails against scope creep.>
```

**Priority** — infer from the user's language:

| Signal | Priority |
|--------|----------|
| "broken", "blocking", "urgent", "ASAP" | Urgent (1) |
| "important", "high priority", "soon" | High (2) |
| no signal | Medium (3) |
| "nice to have", "low priority", "someday" | Low (4) |

**Step 3 — Preview and confirm**

Show the user the title, priority, and description. Wait for "yes" before calling the API.

**Step 4 — Fetch team ID and create the issue**

```bash
source .env && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query{teams{nodes{id key name}}}"}'
```

Use `jq --arg` to JSON-encode all string fields when calling the create mutation. Check that `success: true` in the response.

**Step 5 — Report**

```
Created: <ISSUE-ID>
URL:     <linear url>

Next: /harness run <ISSUE-ID>
```

### Related

- `/harness run` — orchestrates the `start → review → close` verb loop for a given ticket
- `harness/cli/start.py`, `harness/cli/review.py`, `harness/cli/close.py` — the three verbs `/harness run` drives
- `specs/proposals/harness-as-tool.md` — the proposal behind the verb-loop model
