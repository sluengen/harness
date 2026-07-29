<!-- guidance:harness@0.2.10 -->
# /harness — Harness pipeline commands

Commands for driving the **harness pipeline itself**. `/harness run` is the canonical end-to-end build process for this repo: an agent-orchestrated loop over the four harness verbs (`start`, `design`, `review`, `close`). It is distinct from the agent-led backup flow (`/start`, `/review`, `/ship`), which you run when a task does not fit this shape.

---

## /harness run \<ISSUE-ID\>

Drive a Linear ticket end-to-end by orchestrating the four harness verbs: **start → design → implement → review → (fix → review)\* → close**.

This is **not** a wrapper that hands the ticket to a black-box workflow. *You* — the orchestrating Claude session — run the loop: you call each verb, you write the code and tests inline in the worktree, you read each verdict and act on it. The verbs own every git and tracker mutation; you own the implementation and the control flow between them.

**Why the verbs, and nothing else, touch state (D5):** each verb appends to a single `runs` ledger — `start` opens the row, `design` records the design attempt and the SHA it grounded against, `review` records a verdict bound to the reviewed SHA, `close` enforces the gate and finalizes. That ledger is the whole audit trail. If you hand-roll a `git merge`, a `git push`, or a Linear GraphQL mutation to move state yourself, the ledger no longer reflects reality and the gate can no longer protect the merge. So: **never** run raw git state-transitions or Linear CURL for the lifecycle in this loop — route every mutation through a verb.

### Usage

- `/harness run <ISSUE-ID>` — orchestrate the build loop for the given Linear ticket

### Prerequisites

`harness` must be on your `PATH` as the Docker wrapper (`~/bin/harness`). If it isn't yet, set it up per the harness app's Docker-wrapper instructions — one `chmod +x` and a `PATH` line in `.zshrc`. Each verb runs as a one-shot container exactly as the wrapper does: CWD mounted as the workspace, `LINEAR_API_KEY` read from `.env`. You shell out to the verbs from your session — you do **not** run inside a verb container.

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

**Step 1.5 — `design`.** Before writing a line, produce the run's technical design:

```bash
harness design --run-id <run_id>            # [--repo .] [--model <alias>]
```

A read-only **Opus** engine studies the worktree and the ticket in a fresh, dedicated context — uncontaminated by your orchestration state — and produces the change spec's Design section (data model, interface/contract, scenarios, security, test strategy). The verb records it in three places: the ticket, as a marked comment; the ledger, as a `design` event carrying the design's content hash and the `grounded_sha` it studied; and stdout, as `DesignOutput`:

```json
{ "run_id": "...", "design_markdown": "### Data model\n...", "design_hash": "...",
  "grounded_sha": "...", "model": "opus", "status": "ok" }
```

**Run it as a single top-level background command — never chain a bare `&` inside a command that is *also* launched with your runtime's own background flag (#236).** A nested-background invocation detaches a process your session no longer tracks: it looks dead, but it is often still running to completion. If a redirected output file reads empty shortly after launch, that means **not finished yet**, never *dead* — wait and re-read, or check `harness events <run_id> --type design`, rather than relaunching. If two invocations do run, the **last one to finish silently becomes the run's bound design**, and it may not be the one you read — `harness design`'s own output then carries `concurrent_prior_at` (and the underlying `design` event does too) as the machine-readable warning that this happened; a stderr `warning:` line says the same. The recovery is not a bypass: run `harness design` once, cleanly, and implement from *that* output — the idempotent re-run contract below is unchanged.

**Implement against that design** — that is the whole point of the stage (ADR 0007): top-tier thinking happens in a verb-owned subprocess and your session executes against its output, instead of designing by rejection across `(fix → review)*` cycles. **Save `design_markdown` to a file** and pass it to `review` as `--design-file` (Step 3) so the review engine sees the same design. **Stage that file inside the repo tree** (e.g. under the worktree) — the `~/bin/harness` wrapper mounts only the invoking CWD into each verb's container, so a host-only path like `/tmp` never resolves there. `review` refuses a `--design-file` outside that mount up front (`reason=design_file_outside_workspace`, AC-2 #247) rather than silently reviewing design-blind.

The stage is **unconditional** — it runs for every ticket, whatever its judged difficulty; the `build:<tier>` / `review:<tier>` labels do not gate it (ADR 0005 semantics are untouched).

**Failure degrades and records (ADR 0007 D4).** Every way the stage can fail to produce a design — a killed engine, an engine that cannot be spawned, no `SUBMIT` line, a malformed one, an unreadable ticket spec — records a `design` event with `status="failed"` and a stable `reason`, posts no comment, and exits **3**. That is not a stop: **proceed to implement without a design**. A design attempt that *failed* still **satisfies** `review`'s enforcement, so an infra flake costs the run its design but never its ability to ship. Do not re-run `design` in a loop chasing a green one — a re-run is legitimate (the latest event is authoritative, nothing is mutated), but the run is not blocked either way.

**`review` refuses a run with no recorded design attempt** — exit `5`, `reason=no_design`, before any engine is invoked and with no verdict recorded. It mirrors `no_gate_evidence`: silence is not a pass. Skipping this step does not save a step; it buys a refusal at Step 3.

**Step 2 — implement.** Write the code and tests in the worktree, **test-first** per this repo's `CLAUDE.md` (write the failing test, watch it fail for the right reason, then make it pass). Stay in scope — every changed file must trace to the ticket. Run the repo's verify gate (`CONTEXT.md` → `verify:`) in the worktree as you go: **you** run the gate — `review` refuses to review a tree you cannot show is green (Step 3), so this is not optional.

**Checkpoint your WIP so it survives the container dying.** After each green local verify — i.e. each committed increment — push the run branch:

```bash
harness checkpoint --run-id <run_id>    # [--repo .] — pushes the run branch to origin; records a checkpoint event
```

This is the load-bearing half of run reclamation (proposal `stale-run-reclamation` D4): the orchestrating session runs in an ephemeral container, so if it dies mid-run the only recoverable work is what was **pushed**. `checkpoint` pushes *only* the feature branch — it never merges, so the `close` gate is untouched — and records a `checkpoint` event so a later `harness reclaim` can name the branch as resumable (and a fresh run continue from it rather than restart cold). It is **best-effort**: if a checkpoint push fails (exit 1), note it and keep working — a failed checkpoint loses only durability, not the run. A run that never checkpoint-pushes still works; it just degrades to a clean restart if it dies.

**Step 3 — `review`.** When the implementation is ready, review the current worktree HEAD:

```bash
harness review --run-id <run_id>                  # [--repo .] — engine defaults to claude
harness review --run-id <run_id> --engine codex   # cross-model review — host-only (see below)
```

**You run the gate; the verb enforces and records the evidence.** Run `CONTEXT.md` → `verify:` in the worktree, capture its output to a file, and hand the result to `review`:

```bash
bash <your verify gate> > /tmp/gate.log 2>&1; echo $?     # whatever CONTEXT.md → verify: says
harness review --run-id <run_id> --gate-exit <code> --gate-log /tmp/gate.log \
  --design-file design.md                                 # Step 1.5's design_markdown, staged in the worktree — NOT /tmp
```

`--design-file` carries the `design_markdown` Step 1.5 printed, and the recorded `design_hash` authenticates it: the engine then reviews the diff **against the design**, so the fix loop converges on conformance instead of re-deriving intent each cycle. It is **enrichment, not enforcement** — an unreadable or hash-mismatched file (both inside the workspace) drops the context rather than failing the run (a supplied-but-unmatched file warns on stderr), and it can neither satisfy nor bypass the `no_design` check, which keys on the ledger alone. A path the container cannot even resolve under its mounted workspace is a *different* case — a caller error, refused outright before the engine runs (see the `design_file_outside_workspace` refusal below), rather than a design to drop. Whether a review actually saw the design — and, if not, why (`not_supplied` / `unreadable` / `hash_mismatch` / `design_failed`) — is recorded on the `review` event as `design_context` / `design_context_reason` (AC-1 #247).

The verb does **not** run the gate itself — the toolchain lives on your side, not in the verb's container, and no image can carry every target repo's toolchain (an Xcode target never runs in a Linux container). What the verb does is refuse to certify what it cannot show was verified:

- **No recorded `design` event for the run** → exit `5`, `reason=no_design`, checked **first** (a run that never recorded a design stage is malformed whatever its gate colour — root cause before symptom). Run Step 1.5 and review again; a *failed* design attempt satisfies it.
- **`--design-file` names a path outside the mounted workspace** → exit `5`, `reason=design_file_outside_workspace`, checked before the file is even opened. The message names the rejected path and the workspace root(s) — stage the file inside the repo tree and re-run.
- **No `--gate-exit` while `verify:` is configured** → exit `5`, `reason=no_gate_evidence`. Silence is not a pass.
- **`--gate-exit` non-zero** → exit `5`, `{"error": ..., "reason": "gate_failed", "gate_output_tail": ...}`. **No engine, no verdict recorded.** Fix what the tail reports and re-run.
- **Green** → the engine runs, and the `review` event records `gate_ran`, `gate_command`, `gate_exit_code`, and the log tail, bound to the reviewed SHA — so a recorded `pass` means *the gate ran green*, not *a reviewer read the diff*.
- **No `verify:` configured** → recorded honestly (`gate_ran=false, gate_reason="not_configured"`) and review proceeds; the harness cannot gate what a repo does not define.

Do not route around a refusal: `close` refuses a pass carrying no gate evidence (`no_gate_evidence`). Reporting a green exit code for a gate you did not run is falsifying the record the whole loop rests on.

The selected engine (`--engine claude|codex`, **default `claude`**) reviews the diff against HEAD and records a verdict bound to that SHA. Both engines are **read-only CLI subprocesses** emitting the same `SUBMIT:` contract — never the Agent SDK; the engine's full reasoning stays inside the verb. You see only the bounded result (`ReviewOutput`), which records the `engine` that produced the verdict:

```json
{ "verdict": "pass|fail|defer", "issues": [ ... ], "reviewed_sha": "...", "run_id": "...", "engine": "claude|codex" }
```

`claude` is the default because it is available on the standard tier and auto-compacts, so the gate does not degrade to a false `fail` when the Codex tier is depleted; `--engine codex` stays available for a cross-model second opinion. If an explicit `--engine codex` run hits an exhausted tier, the verb falls back **once** to Claude: `engine` then reads `claude`, the ledger event records `fallback_from: "codex"`, and the verdict stays *available* rather than a false `fail`. An ordinary (non-usage-limit) Codex failure does **not** fall back — a real review failure stays a visible `fail`.

**In-container, the review engine is Claude; `--engine codex` is host-only** (the harness's in-container-review-engine decision, ADR 0002). Because you drive `/harness run` through the `~/bin/harness` Docker wrapper, `harness review` runs in the unprivileged `harness:dev` container, where Codex's `bwrap` sandbox cannot open a user namespace and a `--engine codex` review degrades. The container is deliberately kept unprivileged — it reviews untrusted diffs — so a genuine cross-model Codex pass is a **host-side** run (native `harness` install, where `bwrap` and `~/.codex` auth work), not an in-container one. In the verb loop here, review on Claude.

**The claude engine's model is a per-ticket tier, not fixed** (ADR 0005, #177). `review` resolves the ticket's `review:<tier>` label (`sonnet` default, `opus` opt-in) and passes it to the claude engine as `--model <alias>`; codex is unaffected. Pass `--model <alias>` yourself to override the resolved tier (host/testing only).

Act on `verdict`:

- **`fail`** — fix the listed `issues` in the worktree (fix the root cause, not just the cited line), then **re-run `harness review`**. This is the `(fix → review)*` loop; each new review binds to the new HEAD. The loop is **bounded** by one stop rule (the same one `agents/reviewer.md` states and the `review` verb enforces, thresholds in `CONTEXT.md` → `loop:`): cycles 1–3 run unconditionally; after the 3rd, assess convergence on each FAIL before continuing (the verb flags this with a `convergence_check_required` advisory); and the run **stops and escalates on reaching the 6th review→fix cycle regardless** — a 6th `harness review` is refused with `reason=review_cycle_ceiling` (a `90`-minute per-run wall-clock budget trips the same way, `reason=wall_clock_budget`). On a breaker refusal, **stop and escalate to the human** — do not work around it; the loop is bounded out for a reason.
- **`defer`** — the implementation is shippable, but the review surfaced a genuinely out-of-scope finding (needs its own spec or a redesign). Handle the finding by **filing a follow-up** — use `/harness ingest` to create a child ticket capturing it — then proceed to close.
- **`pass`** — proceed to close.

**Recovering from a breaker trip.** A breaker refusal escalates to the human, and the human may authorise continuing. If they do, the recovery is *not* `harness start <TICKET> --resume` on its own: the tripped run is still `open`, and `start` — with or without `--resume` — resolves a ticket's existing open run and **returns it unchanged** (same `run_id`, same `started_at`), so the wall-clock window and the review-cycle count carry straight over and the next `harness review` trips the identical breaker immediately. `--resume` chooses the *start point of a new run*; it does not reset an existing one. Recover in four steps, in order:

1. `harness checkpoint --run-id <run_id>` — push the WIP, because `--resume` recovers what is on `origin`, nothing local.
2. **Post the handoff comment** naming that branch (format and rationale under *Proactive context-rollover handoff* below) — resume resolution reads that comment, not the ledger.
3. `harness cancel <run_id>` — mark the tripped run `cancelled`: a ledger-only write that records the abandon event, leaves the ticket **In Progress**, and touches no branch, so the `close` gate is unaffected. This clears the ticket's open row; without it, step 4 is a no-op that hands back the tripped run.
4. `harness start <TICKET> --resume` — a **new** `run_id` with a fresh `started_at`, worktree based on the preserved branch tip. Confirm with `harness status <run_id>`: `started_at` reads as now, and the old run still reads `cancelled`.

Do this **once**, on an explicit human decision. Cancel + resume opens a new budget window — it resets *both* breakers, wall-clock and cycle count — so looping it is exactly the runaway spend the breakers exist to bound.

**Step 4 — `close`.** Finalize through the gate:

```bash
harness close <ISSUE-ID> --run-id <run_id>    # [--repo .]
```

`close` enforces the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA equals the current HEAD), then commits, merges, pushes, transitions the ticket Done **and confirms it landed against that same mutation's own post-write response** (#233 — a transition that merely did not raise is not proof it took), and marks the run closed. On success it emits `CloseOutput`, whose `ticket_done: true` means the tracker was *observed* Done, not merely that a transition was attempted:

```json
{ "run_id": "...", "ticket": "...", "reviewed_sha": "...", "merged": true, "ticket_done": true, "status": "..." }
```

### Gate-refusal handling

If `close` refuses, it exits non-zero with `{"error": ..., "reason": ...}`. The `reason` is one of:

- **`no_run`** — no `start` row exists for this ticket. You skipped `start`, or are closing the wrong ticket. Run `harness start` first.
- **`dirty_worktree`** — the worktree has uncommitted changes; what would merge was never reviewed. Commit (or discard) the edits, **re-run `harness review`** to bind a fresh `pass` to the new HEAD, then close again.
- **`no_passing_review`** — no `verdict=pass` is on record. You have not run `review`, or its last verdict was `fail`/`defer`. Run `harness review` and reach `pass`.
- **`stale_review`** — there is a passing review, but HEAD moved after it (you committed more work). The passing verdict no longer covers what would merge. **Re-run `harness review`** on the current HEAD to re-establish a fresh `pass`, then close again.
- **`no_gate_evidence`** — a `pass` covers HEAD, but it carries no evidence that the repo's verify gate ran (it was recorded by a harness predating the gate). **Re-run `harness review`** to record a pass backed by a green gate, then close again.

There is no `dirty_base_checkout` refusal: `close` merges in a throwaway worktree and never touches the main checkout, so the state of the main checkout — clean, dirty, or even mid-merge — cannot block a close. A **merge conflict** with what landed on `origin/<base>` during the run, or a **push rejected non-fast-forward** because a concurrent close won the race, is an exit-1 error (not a gate refusal, so no `reason` key). Both are retryable: for a conflict, rebase the run branch on the updated base, re-review, and close again; for a rejected push, simply close again — it re-fetches the winner's tip.

**A ticket-transition failure is exit 1, not a gate refusal (#233).** The merge has already landed by the time the ticket-Done transition is attempted, so a confirmed-failed transition cannot use exit 2's "refused, nothing happened" contract — it exits **1** with `{"error": ..., "reason": ..., "merged": true, "run_id": "..."}`, `reason` being one of two tags: `ticket_transition_failed` (the tracker raised — an outage, a permission error) or `ticket_transition_unconfirmed` (the mutation reported success, but its own response shows the requested state never took). Re-run `harness close` once the tracker is healthy — the merge/push step is idempotent for an already-landed run branch, so the retry only needs the transition to succeed this time.

A gate refusal is the gate doing its job. **Do not work around it** — do not hand-roll the merge/push/transition to "finish" the run. If the refusal is something you cannot resolve by re-running a verb (e.g. an unexpected error, or a verb that itself fails), **surface it to the human / Hermes** with the `reason` and the `run_id`; do not improvise a bypass.

#### Shared invocation refusal: `no_ledger` (#244)

`checkpoint`, `review`, `close`, and `design` all resolve their open run the same way, and can all refuse the same way before they even get to their own gate or refusal logic: if the resolved `.harness/harness.db` **does not exist on disk**, the verb exits `2` with `{"error": ..., "reason": "no_ledger", "ledger_path": "..."}` — distinct from `no open run found for worktree ...` (which means the ledger *was* read but held no matching open row). If you see `no_ledger`, the cause is almost always that the verb ran from the wrong place — outside the repo that owns the run, or a container mounting only a worktree whose main checkout isn't reachable — not that the run is dead. `cd` to the repo (or worktree) `start` reported, or pass the run's `--repo` / `--db` explicitly, and re-run.

### Context economy / compaction

The plan you are following lives only in this session's context — the ledger and the worktree are the durable record. If context is lost or compacted mid-run:

- **Re-orient via the ledger.** Run `harness status <run-id> [--json]` to get the run's terminal-state summary, and inspect the worktree (`git status`, `git log`, the diff) to see what is already implemented. The ledger + worktree are the source of truth — trust them over a half-remembered plan.
- **Checkpoint intent before you risk losing it.** Commit WIP in the worktree and/or write the remaining plan into the ticket or a scratch note, so the one thing that lives only in context survives a compaction. (A `CLAUDE.md` "Compact Instructions" section is an optional refinement, not required.)

#### Proactive context-rollover handoff

When a build is **alive but nearing its context limit** mid-ticket, hand off gracefully rather than risk a mid-thought cutoff — **compose the existing verbs, no new machinery** (proposal `ground-specs-and-context-rollover` WS-B):

1. **`harness checkpoint --run-id <run_id>`** — push the WIP branch so it is durable (the existing verb; pushes only the feature branch, so the `close` gate is untouched).
2. **Post a handoff comment** on the ticket naming the checkpoint-pushed branch, in the single-sourced `harness.reclaim_marker.format_handoff_comment` format — marker `Context-rollover handoff by \`harness checkpoint\`` with a ``Preserved branch: `<branch>` `` clause. Post it through the `linear` skill (`commentCreate`). **Leave the ticket In Progress** — do **not** revert it to Todo and do **not** apply the `reclaimed` label.
3. **A fresh session continues the same ticket** with `harness start <TICKET> --resume`: resume resolution reads the handoff marker (`LinearClient.fetch_handoff_branch`), fetches the branch from `origin`, and starts the worktree from its tip while keeping `base_branch` = `dev` — so `close`'s HEAD-bound gate keeps the resumed run safe from double-merge. Re-orient via `git log` on the recovered WIP before continuing.

The same mechanic applies here: `start --resume` opens a new run only when the ticket has **no** open run. A handoff that leaves its run `open` hands the fresh session the *same* row — same `run_id`, same `started_at` — so the prior session's wall-clock window and cycle count keep running against it. Cancel the handed-off run (`harness cancel <run_id>`, after step 2's comment) so the continuing session gets its own budget; the ordered recipe is *Recovering from a breaker trip* above.

**This is distinct from death-keyed reclamation** (`harness reclaim`, Step 0 of `/harness routine build`), and the two never collide:

| | Proactive context-rollover handoff | Death-keyed reclamation |
|---|---|---|
| Trigger | session **alive**, near its context limit | orchestrator **dead** (stalled past the staleness threshold) |
| Linear state | ticket **stays In Progress** | ticket reverted to **Todo** |
| Label | **none** | **`reclaimed`** |
| Comment marker | `Context-rollover handoff by \`harness checkpoint\`` | `Reclaimed by \`harness reclaim\`` |
| Resume reader | `fetch_handoff_branch` (marker-gated, no label) | `fetch_resume_branch` (`reclaimed`-label-gated) |

Because the two use **distinct marker strings** and occupy **distinct Linear states**, `start --resume` resolves the right branch for each — a handoff comment is never read as a reclaim comment, and vice versa (pinned by the harness's reclaim-marker tests). `start --resume` tries the reclaim source first, then falls through to the handoff source, so one flag serves both.

---

## /harness routine \<loop\>

The **unattended loops** that drive the harness between human sessions, versioned as commands so the logic that runs on a schedule lives in the repo — *version the logic, not the schedule* (`four-loops.html`). Each routine is a thin, repeatable task; the scheduled trigger that fires it (cron, a Claude routine) is configured in the app and is **not** part of this command — versioning the *logic* is the point.

Two loops are versioned here: `build` (the hourly work-pull) and `quality` (idle/weekly assessment). Each names a **harness-tooled primary** and an **agent-orchestrated fallback**, selected by tool availability — the same `/harness run` vs `/build` duality the rest of this surface uses.

> **Scope is resolved from `CONTEXT.md`, not hardcoded.** Both loops operate on the Build queue, whose scope is set by the **optional** `repo.project`. Resolve it at runtime (the same way `/harness ingest` resolves the team from `repo.linear`), so this distributed command needs no per-repo hand-edit. When `repo.project` is **set**, scope to that one project; when it is **unset**, work the whole tracker queue — for a `tracker: linear` repo the team named in `repo.linear`, for a `tracker: github` repo the board (already the full queue). Below, `<repo.project>` stands for that value when it is set; in the harness repo it is `Harness`.

> **Default: always-on local. Cloud is optional.** A routine normally runs on the always-on device via a **local trigger**: it shells out to the `~/bin/harness` Docker wrapper and reads `.env` from the working copy (an always-on scheduled task driving `/harness routine build`). This is local-trigger because a cloud runner cannot reach `~/bin/harness` or the local checkout — and it is the default because it already works and costs nothing per run. The trigger itself is configured in the app and is **not** part of this command; whatever fires it must be a **thin caller** that invokes `/harness routine build` and nothing more (*version the logic, not the schedule*). An **off-machine** path is *possible* — the harness's own loop runs against the native `harness` entry point (`uv tool install .`, no Docker) with credentials as secrets and the **Claude** review engine — but if ever needed it is a **Claude cloud routine**, **not** GitHub Actions (rejected: a private repo meters Actions minutes and the loop is a long agent run, not a cheap CI gate). The optional cloud path and the **per-target-repo gate rule** (a target whose gate needs Xcode/macOS stays local or on a macOS runner) are the harness's own recorded design decisions. Cloud-enabling self-hosting *target* repos remains out of scope.

### /harness routine build

The hourly work-pull: take the next logical ticket off the tracker's Todo queue and drive it to Done, or — when the queue holds nothing actionable — fall through to the quality loop.

**Primary surface:** `/harness run <TICKET>` (the audited verb loop). **Fallback:** `/build <TICKET>` (agent-orchestrated) when the harness tool is unavailable. In the harness repo itself, the primary is always `/harness run` (per `CLAUDE.md`, the harness drives its own tickets through the verb loop, not `/build`); the fallback is for a consuming repo that lacks the harness app.

**Scope (resolve from `CONTEXT.md` at runtime).** Read `repo.project`. When it is **set**, every step below is scoped to that one project — the reclaim pre-flight passes `--project "<repo.project>"` and the pick considers only that project's Todo queue. When it is **unset**, the loop works the **whole** tracker queue — the reclaim pre-flight runs `harness reclaim --stale` with **no** `--project`, and the pick ranks across the whole queue (a `tracker: linear` team, or a `tracker: github` board). The steps below show the scoped (`repo.project` set) path; for the unscoped path, drop `--project` and read `<repo.project>` as "the whole queue".

**Step 0 — reclaim stranded runs (pre-flight).** Before picking any work, sweep the queue for tickets stranded **In Progress** by a run that died mid-flight. A session that hits a usage/session limit just *stops*, leaving its ticket In Progress; a fresh run can observe nothing about the dead predecessor, so liveness is unobservable and a **time heuristic** is the only fix that survives a hard kill (proposal `stale-run-reclamation`, D2/D3). Run the sweep first:

```bash
harness reclaim --stale --project "<repo.project>"   # repo.project SET: scope the sweep to that project ("Harness" here); default staleness threshold 90m
harness reclaim --stale                              # repo.project UNSET: no --project → sweep the whole tracker queue (a linear team / a github board)
```

This **runs first, before the pick step**, so the routine **unblocks the backlog** before it chooses work: a ticket left In Progress by a dead predecessor would otherwise wedge the queue until a human intervened. The sweep reverts each idle ticket (Linear `updatedAt` older than the threshold) back to **Todo**, so this same run can then pick it up. It is **idempotent and safe to run every tick**: a ticket already reverted is Todo (not In Progress), so a later sweep does not re-enumerate it, and a sweep that finds nothing stale is a clean no-op. The sweep keys entirely on **Linear** (not the local ledger), so it works in both the local and cloud regimes; it touches only **In Progress** tickets and never **In Review**. *Fallback (`/build`, harness tool unavailable):* run the **equivalent** Linear-keyed pre-flight by hand through the `linear` skill — revert every `<repo.project>` ticket left In Progress past the staleness threshold back to Todo (never touch In Review) — before picking work.

**Then reclaim merged worktrees + branches (housekeeping).** `close` tears down its own worktree and branch when it lands, but a run whose container died before that teardown step — or a long-dead run reverted by the sweep above — can still leave a `.worktrees/harness/<id>/` directory and a branch behind, and over many ticks these accumulate (GB of worktrees, a cluttered branch list). Run the housekeeping sweep as part of the same pre-flight:

```bash
harness worktrees cleanup --merged --age 7d   # delete merged worktrees + their branch; rm orphaned dirs >7d old
```

This is **best-effort and idempotent**: `--merged` removes each worktree whose branch has already landed on `dev`/`main`/`master` and deletes that merged branch (local + on `origin`); `--age 7d` reclaims orphaned directories left by runs that died long ago (the cruft a plain `git worktree remove` can no longer touch). It never removes a recent, unmerged worktree — including a reclaimed ticket's preserved WIP branch, which lives on `origin` and is fetched by `--resume`, not from the local directory. `--merged` treats a merge-ancestry match as necessary but not sufficient (#235): a fresh run branch with zero commits is trivially "merged" (its tip equals the base) even though its WIP may be `git stash`'d rather than committed, so before deleting it also checks the run's ledger status, `git stash list`, and the worktree's own dirty state — a hit on any of the three keeps the worktree and prints why, unless `--force` is given. *Fallback (`/build`, harness tool unavailable):* run the same `harness worktrees cleanup --merged --age 7d` by hand in the repo as part of the pre-flight.

The loop:

1. **Pick the next ticket** — invoke the **`work-discovery` skill**. It owns the discovery logic: which Todo tickets to consider — scoped to `<repo.project>` when it is set, or the whole tracker queue when it is unset (resolved from `CONTEXT.md`) — how to rank them, and which already-deferred ones to skip. The pick criteria are single-homed in that skill, not restated here — this command owns only the control flow around the invocation.
2. **Check it is wholly actionable** — apply the `work-discovery` skill's actionability test.
   - If the skill judges it **not** actionable (it needs a human decision or missing detail), **defer it with the verb**: `harness defer <TICKET> --reason <text> [--needs decision|input|operator]` (use `--reason-file <path>` for a long body). The verb posts the reason as a comment, additively applies the hold label (`--needs` selects it: `decision` for a judgment call — the default —, `input` when the operator must supply something the run cannot, or `operator` for an interactive session), **assigns the ticket to the operator** (the machine-readable hold signal `work-discovery` skips on later ticks), and records a `defer` event carrying the `needs` kind in the runs/events ledger — so triage is an audited action bound to its `autoMode.allow` clause, not a hand-rolled tracker write. Then re-pick (step 1) or, if nothing remains, go to step 5.
   - If it **can** be actioned, implement it: `/harness run <TICKET>` (primary), or `/build <TICKET>` (fallback) where the harness tool is unavailable.
3. **Resume a reclaimed ticket from its preserved WIP branch.** If the picked ticket carries the `reclaimed` label, it was reverted from a run whose orchestrator died (the pre-flight, step 0) and may have a **checkpoint-pushed WIP branch**. Start it with `harness start <TICKET> --resume` so the new run continues from that branch (fetch + continue) instead of a clean branch off `dev`, recovering the dead run's work rather than redoing it. When no durable WIP exists — the reclaim preserved no branch, or the branch no longer fetches — `--resume` **falls back** to a normal clean start automatically; it is best-effort and never blocks the queue. Either path is safe from double-merge: the resumed run still merges into `dev`, and `close`'s HEAD-bound gate (a `pass` whose reviewed SHA == HEAD) holds. The resumed worktree already carries the prior WIP, so re-orient via `git log` before continuing (proposal `stale-run-reclamation` D4). A non-`reclaimed` ticket starts normally (no `--resume`).
4. **Branch off `dev`.** Take your branch off of `dev`. Linear access is via the GraphQL API; the key is in the `.env` file in the repo.
5. **Idle → quality.** If there are no wholly actionable Todo tasks in Linear, fall through to **`/harness routine quality`** (its idle arm runs `/assess code`). If that surfaces nothing to action either, don't invent work — exit cleanly.

### /harness routine quality

The assessment loop that catches what accumulates across many changes — what no per-change review sees. It **advises** (files findings as tickets); it does not block a merge.

**Primary surface:** `/assess code` (the steward, agent-orchestrated). There is no harness-tooled variant — assessment is advisory, not a gated verb run — so this routine is agent-led on every repo.

- **Idle arm** (the Build queue is empty): run `/assess code`. Action the highest-priority finding it surfaces; record any further findings as tickets back into the Build queue for other runs to handle — into `<repo.project>` when it is set, or the tracker's default backlog (no project) when it is unset.
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

- `/harness run` — orchestrates the `start → design → review → close` verb loop for a given ticket
- The four verbs `/harness run` drives — `start`, `design`, `review`, and `close` (implemented in the harness app)
- The proposal behind the verb-loop model (the harness's "harness-as-tool" design)
