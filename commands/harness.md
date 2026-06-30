<!-- guidance:harness@0.1.2 -->
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

Parse it. **Record `run_id`** (you need it for `status`, `review`, and `close`). `cd` into `worktree_path`. Read `ticket.title` and `ticket.description` — that is your spec for this run. (Default base is `dev`; pass `--base` only to override.) If the ticket carries the `reclaimed` label, add `--resume` so the run continues from the dead run's preserved WIP branch when one exists (it falls back to a clean start otherwise) — see the Build routine's resume step.

**Step 2 — implement.** Write the code and tests in the worktree, **test-first** per this repo's `CLAUDE.md` (write the failing test, watch it fail for the right reason, then make it pass). Stay in scope — every changed file must trace to the ticket. Run the repo's verify gate locally as you go.

**Checkpoint your WIP so it survives the container dying.** After each green local verify — i.e. each committed increment — push the run branch:

```bash
harness checkpoint --run-id <run_id>    # [--repo .] — pushes the run branch to origin; records a checkpoint event
```

This is the load-bearing half of run reclamation (proposal `stale-run-reclamation` D4): the orchestrating session runs in an ephemeral container, so if it dies mid-run the only recoverable work is what was **pushed**. `checkpoint` pushes *only* the feature branch — it never merges, so the `close` gate is untouched — and records a `checkpoint` event so a later `harness reclaim` can name the branch as resumable (and a fresh run continue from it rather than restart cold). It is **best-effort**: if a checkpoint push fails (exit 1), note it and keep working — a failed checkpoint loses only durability, not the run. A run that never checkpoint-pushes still works; it just degrades to a clean restart if it dies.

**Step 3 — `review`.** When the implementation is ready, review the current worktree HEAD:

```bash
harness review --run-id <run_id>                  # [--repo .] — engine defaults to claude
harness review --run-id <run_id> --engine codex   # opt into a Codex cross-model review
```

The selected engine (`--engine claude|codex`, **default `claude`**) reviews the diff against HEAD and records a verdict bound to that SHA. Both engines are **read-only CLI subprocesses** emitting the same `SUBMIT:` contract — never the Agent SDK; the engine's full reasoning stays inside the verb. You see only the bounded result (`ReviewOutput`), which records the `engine` that produced the verdict:

```json
{ "verdict": "pass|fail|defer", "issues": [ ... ], "reviewed_sha": "...", "run_id": "...", "engine": "claude|codex" }
```

`claude` is the default because it is available on the standard tier and auto-compacts, so the gate does not degrade to a false `fail` when the Codex tier is depleted; `--engine codex` stays available for a cross-model second opinion. If an explicit `--engine codex` run hits an exhausted tier, the verb falls back **once** to Claude: `engine` then reads `claude`, the ledger event records `fallback_from: "codex"`, and the verdict stays *available* rather than a false `fail`. An ordinary (non-usage-limit) Codex failure does **not** fall back — a real review failure stays a visible `fail`.

Act on `verdict`:

- **`fail`** — fix the listed `issues` in the worktree (fix the root cause, not just the cited line), then **re-run `harness review`**. This is the `(fix → review)*` loop; each new review binds to the new HEAD. The loop is **bounded** by one stop rule (the same one `agents/reviewer.md` states and the `review` verb enforces, thresholds in `CONTEXT.md` → `loop:`): cycles 1–3 run unconditionally; after the 3rd, assess convergence on each FAIL before continuing (the verb flags this with a `convergence_check_required` advisory); and the run **stops and escalates on reaching the 6th review→fix cycle regardless** — a 6th `harness review` is refused with `reason=review_cycle_ceiling` (a `90`-minute per-run wall-clock budget trips the same way, `reason=wall_clock_budget`). On a breaker refusal, **stop and escalate to the human** — do not work around it; the loop is bounded out for a reason.
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

## /harness routine \<loop\>

The **unattended loops** that drive the harness between human sessions, versioned as commands so the logic that runs on a schedule lives in the repo — *version the logic, not the schedule* (`four-loops.html`). Each routine is a thin, repeatable task; the scheduled trigger that fires it (cron, a Claude routine) is configured in the app and is **not** part of this command — versioning the *logic* is the point.

Two loops are versioned here: `build` (the hourly work-pull) and `quality` (idle/weekly assessment). Each names a **harness-tooled primary** and an **agent-orchestrated fallback**, selected by tool availability — the same `/harness run` vs `/build` duality the rest of this surface uses.

> **The Linear project is resolved from `CONTEXT.md`, not hardcoded.** Both loops operate on one Linear project — the Build queue. Resolve it at runtime from `CONTEXT.md` → `repo.project` (the same way `/harness ingest` resolves the team from `repo.linear`), so this distributed command needs no per-repo hand-edit. Below, `<repo.project>` stands for that value; in the harness repo it is `Harness v3`.

> **Routines are local-trigger only.** A routine shells out to the **local** `harness` wrapper (`~/bin/harness`) and reads `.env` from the working copy. A cloud routine cannot reach `~/bin/harness` or the local checkout, so these routines must be triggered locally (a local Claude routine, or the macOS scheduled task). Cloud execution is out of scope.

### /harness routine build

The hourly work-pull: take the next logical ticket off the Linear Todo queue and drive it to Done, or — when the queue holds nothing actionable — fall through to the quality loop.

**Primary surface:** `/harness run <TICKET>` (the audited verb loop). **Fallback:** `/build <TICKET>` (agent-orchestrated) when the harness tool is unavailable. In the harness repo itself, the primary is always `/harness run` (per `CLAUDE.md`, the harness drives its own tickets through the verb loop, not `/build`); the fallback is for a consuming repo that lacks the harness app.

**Step 0 — reclaim stranded runs (pre-flight).** Before picking any work, sweep the queue for tickets stranded **In Progress** by a run that died mid-flight. A session that hits a usage/session limit just *stops*, leaving its ticket In Progress; a fresh run can observe nothing about the dead predecessor, so liveness is unobservable and a **time heuristic** is the only fix that survives a hard kill (proposal `stale-run-reclamation`, D2/D3). Run the sweep first:

```bash
harness reclaim --stale --project "<repo.project>"   # <repo.project> = CONTEXT.md → repo.project ("Harness v3" here); default staleness threshold 90m
```

This **runs first, before the pick step**, so the routine **unblocks the backlog** before it chooses work: a ticket left In Progress by a dead predecessor would otherwise wedge the queue until a human intervened. The sweep reverts each idle ticket (Linear `updatedAt` older than the threshold) back to **Todo**, so this same run can then pick it up. It is **idempotent and safe to run every tick**: a ticket already reverted is Todo (not In Progress), so a later sweep does not re-enumerate it, and a sweep that finds nothing stale is a clean no-op. The sweep keys entirely on **Linear** (not the local ledger), so it works in both the local and cloud regimes; it touches only **In Progress** tickets and never **In Review**. *Fallback (`/build`, harness tool unavailable):* run the **equivalent** Linear-keyed pre-flight by hand through the `linear` skill — revert every `<repo.project>` ticket left In Progress past the staleness threshold back to Todo (never touch In Review) — before picking work.

**Then reclaim merged worktrees + branches (housekeeping).** `close` tears down its own worktree and branch when it lands, but a run whose container died before that teardown step — or a long-dead run reverted by the sweep above — can still leave a `.worktrees/harness/<id>/` directory and a branch behind, and over many ticks these accumulate (GB of worktrees, a cluttered branch list). Run the housekeeping sweep as part of the same pre-flight:

```bash
harness worktrees cleanup --merged --age 7d   # delete merged worktrees + their branch; rm orphaned dirs >7d old
```

This is **best-effort and idempotent**: `--merged` removes each worktree whose branch has already landed on `dev`/`main`/`master` and deletes that merged branch (local + on `origin`); `--age 7d` reclaims orphaned directories left by runs that died long ago (the cruft a plain `git worktree remove` can no longer touch). It never removes a recent, unmerged worktree — including a reclaimed ticket's preserved WIP branch, which lives on `origin` and is fetched by `--resume`, not from the local directory. *Fallback (`/build`, harness tool unavailable):* run the same `harness worktrees cleanup --merged --age 7d` by hand in the repo as part of the pre-flight.

The loop:

1. **Pick the next ticket.** Look at the current list of items marked **Todo** in Linear in the project `<repo.project>` (resolved from `CONTEXT.md` → `repo.project`). From that list pick the next most logical task to start work on. Take into account the **ID number** (tickets are often added in the order in which they need to be done), **dependencies** in Linear, and the **priority**. Tickets with a `decision` label have been marked as not actionable yet in previous runs — skip them.
2. **Check it is wholly actionable.**
   - If it **cannot** be actioned or needs additional details, add a comment to the ticket about what it needs to be actionable and label it `decision`. Then re-pick (step 1) or, if nothing remains, go to step 5.
   - If it **can** be actioned, implement it: `/harness run <TICKET>` (primary), or `/build <TICKET>` (fallback) where the harness tool is unavailable.
3. **Resume a reclaimed ticket from its preserved WIP branch.** If the picked ticket carries the `reclaimed` label, it was reverted from a run whose orchestrator died (the pre-flight, step 0) and may have a **checkpoint-pushed WIP branch**. Start it with `harness start <TICKET> --resume` so the new run continues from that branch (fetch + continue) instead of a clean branch off `dev`, recovering the dead run's work rather than redoing it. When no durable WIP exists — the reclaim preserved no branch, or the branch no longer fetches — `--resume` **falls back** to a normal clean start automatically; it is best-effort and never blocks the queue. Either path is safe from double-merge: the resumed run still merges into `dev`, and `close`'s HEAD-bound gate (a `pass` whose reviewed SHA == HEAD) holds. The resumed worktree already carries the prior WIP, so re-orient via `git log` before continuing (proposal `stale-run-reclamation` D4). A non-`reclaimed` ticket starts normally (no `--resume`).
4. **Branch off `dev`.** Take your branch off of `dev`. Linear access is via the GraphQL API; the key is in the `.env` file in the repo.
5. **Idle → quality.** If there are no wholly actionable Todo tasks in Linear, fall through to **`/harness routine quality`** (its idle arm runs `/assess code`). If that surfaces nothing to action either, don't invent work — exit cleanly.

### /harness routine quality

The assessment loop that catches what accumulates across many changes — what no per-change review sees. It **advises** (files findings as tickets); it does not block a merge.

**Primary surface:** `/assess code` (the steward, agent-orchestrated). There is no harness-tooled variant — assessment is advisory, not a gated verb run — so this routine is agent-led on every repo.

- **Idle arm** (the Build queue is empty): run `/assess code`. Action the highest-priority finding it surfaces; record any further findings as Linear tasks back into the Build queue (`<repo.project>`, from `CONTEXT.md` → `repo.project`) for other runs to handle.
- **Weekly arm:** run `/assess code --deep` — the broad pass that adds the test-coverage, design-system-adherence (layer-gated), and spec/doc-coherence lenses on top of the `code` lenses. File its findings the same way.

A `/assess` run commits its dated report directly to the integration branch (no branch, no PR — it carries nothing reviewable); the findings live in the tracker. See `commands/assess.md`.

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

**Step 4 — Resolve the team and create the issue**

Create the issue through the **`linear` skill** — the single home for Linear operations. Do not embed raw Linear GraphQL endpoint calls here; a guard fails if one appears. Resolve the team ID at runtime (the skill's team-ID resolution recipe; the team key is `CONTEXT.md` → `repo.linear`), then call its **`issueCreate`** recipe, passing the drafted title and description, the inferred priority, and any label IDs as `issueCreate` input fields. JSON-encode every string field as the skill's recipes show, and confirm the response returns the new issue's `identifier` and `url`.

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
