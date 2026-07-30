---
feature: verb-model
status: implemented
last_updated: 2026-07-29
linear: [CAL-570, CAL-574, CAL-586, CAL-661, CAL-925, CAL-1082, CAL-1104, CAL-1197, "#244"]
---

# Verb model — start / design / review / close

> The four audited verbs an orchestrating agent calls to drive a ticket from open to merged, with the design stage recorded and review enforced as a gate before anything lands.

## Behaviour

The harness is **not** a pipeline that drives agents. A single Claude session orchestrates *and* implements a ticket, shelling out to four one-shot, ledger-backed verbs — `start`, `design`, `review`, `close` — over the [run ledger](run-ledger.md). The agent owns *what gets built and how*; the verbs own *the durable record and the gate* (decision D1, [`specs/architecture-principles.md`](../architecture-principles.md)). The lifecycle of one run is `start → design → implement → review → (fix → review)* → close` (ADR [`0007`](../decisions/0007-design-verb.md) inserted `design` as a mandatory stage; `review` refuses a run that never recorded one).

### `start` — open a run

`harness start <ticket>` validates the ticket, opens the run, and hands back the worktree the agent will build in.

#### Scenario: a clean open

- GIVEN a Linear ticket that has no other `open` run
- WHEN the agent runs `harness start <ticket>`
- THEN the verb fetches and canonicalises the ticket, generates a ULID `run_id`, creates an isolated git worktree off the base branch (default `dev`, see [worktree lifecycle](worktree-lifecycle.md)), inserts the `open` `runs` ledger row, and **transitions the ticket to In Progress last**
- AND it emits a `StartOutput` JSON object (`run_id`, ticket context, `worktree_path`, `worktree_branch`, `base_branch`)

The Linear transition is the only non-local side effect, and it runs **last**: if the worktree creation or the ledger insert fails, nothing has touched Linear. The rollback ordering is locked by `test_cli_start.py::test_worktree_failure_leaves_no_db_row_and_no_transition` and `::test_db_failure_removes_worktree_and_no_transition`. The open run is recorded as the `runs` row, not as an event.

#### Scenario: a ticket that already has an open run

- GIVEN a ticket that already has an `open` run
- WHEN the agent runs `harness start <ticket>` again
- THEN `start` resolves the existing open run (keyed on the canonical Linear identifier) and **returns it successfully** (exit 0) — it does not create a second worktree or row, and does not error (`harness/cli/start.py`, step 4: `if existing is not None: return existing`)

The partial unique index `idx_runs_ticket_open` is the database-level backstop for the concurrent-race path: if two `start` calls both pass the existence check, the index refuses the second insert and that loser cleans up its worktree and surfaces the run that beat it (at most one `open` run per ticket).

### `design` — produce the run's technical design

`harness design --run-id <id> [--model <alias>]` runs a read-only **Opus** engine over the worktree and the ticket in a fresh, dedicated context — uncontaminated by the orchestrator's own state — and produces the change spec's Design section (data model, interface/contract, scenarios, security, test strategy). ADR [`0007`](../decisions/0007-design-verb.md) added it so top-tier thinking happens in a verb-owned subprocess and the session executes against its output, instead of designing by rejection across `(fix → review)*` cycles.

The verb records the design in three places: the ticket, as a marked comment; the ledger, as a `design` event carrying the design's content hash and the `grounded_sha` it studied; and stdout, as `DesignOutput`. The stage is **unconditional** — it runs for every ticket whatever its judged difficulty, and the `build:<tier>` / `review:<tier>` labels do not gate it (ADR 0005's semantics are untouched).

- GIVEN an open run
- WHEN the agent runs `harness design --run-id <id>`
- THEN the verb records a `design` event with `status="ok"`, `design_hash`, and the `grounded_sha` it studied, posts the design as a marked ticket comment, and emits `DesignOutput` on stdout
- AND GIVEN instead the engine is killed, cannot be spawned, emits no `SUBMIT` line or a malformed one, or the ticket spec cannot be read, THEN the verb records a `design` event with `status="failed"` and a stable `reason`, posts **no** comment, and exits `3` (decision **D4**: every failure mode degrades and records)
- AND GIVEN a `failed` design event, WHEN the agent runs `harness review`, THEN review is **not** refused — the check is that a design was *attempted and recorded*, never that it succeeded, so an infra flake costs a run its design but never its ability to ship

**A failed design is not a stop.** The orchestrator proceeds to implement without one rather than re-running the verb in a loop chasing a green result; a re-run is legitimate (the latest event is authoritative and nothing is mutated), but the run is not blocked either way. How `review` consumes the design — enforcement on the ledger, context via `--design-file` — is the "design stage is required" scenario under [`review`](#review--record-a-verdict-bound-to-the-reviewed-sha) below.

### `review` — record a verdict bound to the reviewed SHA

`harness review [--run-id <id>] [--engine claude|codex]` runs the selected review engine (`--engine`, **default `claude`**; CAL-701) against the worktree's current HEAD and records a verdict **bound to the exact SHA reviewed** — the load-bearing detail behind decision D2: the `close` gate refuses a pass whose SHA ≠ HEAD, so a stale pass cannot be reused. Each engine is a **read-only CLI subprocess** (`claude -p --permission-mode plan` or `codex exec --sandbox read-only`) emitting the same `SUBMIT:` contract — never the Agent SDK (see the "Review engine" principle in `architecture-principles.md`).

**The in-container review engine is Claude; `--engine codex` is host-only** (ADR [0002](../decisions/0002-in-container-review-engine.md), CAL-925). Codex's read-only sandbox wraps each command in `bwrap`, which cannot create a user namespace in the unprivileged `harness:dev` container (`CLONE_NEWUSER` blocked, CAL-866), so a real `--engine codex` review degrades there. Rather than loosen the container's privileges — it reviews untrusted diffs — the decision keeps the container's engine Claude and treats `--engine codex` as a host-only cross-model option, where `bwrap` and `~/.codex` auth are available. So inside `~/bin/harness` and the `/harness run` verb loop, review runs on Claude.

**The claude engine's model is resolved per-ticket from a `review:<tier>` label** (ADR [0005](../decisions/0005-per-ticket-model-tiering.md), #177). Before invoking the engine, the verb calls `tracker_client().fetch_issue(ticket)` and resolves the ticket's `review` dimension via the pure `resolve_model_tier(labels, dimension)` (`harness/cli/review_protocol.py`): a `review:opus` label resolves `opus`, an absent or unrecognized label defaults `sonnet`. The resolved alias is appended to the claude command as `--model <alias>` (`_build_cmd`); the codex command is unaffected regardless of the ticket's labels — the tier is a claude-only control signal. An explicit `harness review --model <alias>` overrides the resolved tier outright, for host/testing use. A sibling `build:<tier>` label carries the same shape but drives no verb — it is a recorded judgement only, since the orchestrating session is the builder and has no deterministic per-ticket model seam.

#### Scenario: a review pass

- GIVEN an open run whose worktree HEAD holds committed work
- WHEN the agent runs `harness review`
- THEN the verb resolves the current run (the `status='open'` run whose `worktree_path` equals `--repo`, or the run named by `--run-id`), enforces the verify-gate evidence (below), captures `git rev-parse HEAD` as `reviewed_sha`, invokes the selected engine with the review prompt on stdin, scans stdout for the first `SUBMIT: <json>` line, and appends a `review` event carrying `{ run_id, reviewed_sha, verdict, issues, engine, convergence_check_required, created_at, gate_ran }` (and optional `gate_command` / `gate_exit_code` / `gate_reason` / `gate_output_tail` / `commit_message` / `deferred_brief`)
- AND it prints **only** the bounded verdict (`verdict`, `issues`, `reviewed_sha`, `run_id`, `engine`, `convergence_check_required`) — the engine's full reasoning stays inside the verb (context economy)

A recorded `fail` is still a *successful* review (exit 0): deciding what to do with a verdict is the agent's job, not the verb's. A missing, malformed, or unknown-verdict `SUBMIT` line is recorded as `verdict='fail'` with the sentinel issue `"reviewer emitted no valid SUBMIT line"` — the verb never raises on a bad reviewer, it records the failure.

The agent acts on the verdict:

- `fail` → fix the root cause in the worktree, commit, and **re-run `review`** (the `(fix → review)*` loop). Each review binds to the new HEAD. The loop is **bounded** by the spend breakers below.
- `defer` → the implementation is shippable, but the review surfaced a genuinely out-of-scope finding; file a follow-up for it. Note the close gate opens **only** on a `verdict=pass` (`harness/cli/close.py` queries `verdict='pass'`; a run with only a `defer` is refused `no_passing_review`), so to close you still need a passing review bound to HEAD — obtain one before closing.
- `pass` → proceed to close.

#### Scenario: the verify gate's evidence is required before any engine

`review` requires **evidence** that the repo's verify gate (`CONTEXT.md` → `verify:`) ran green before it invokes an engine, and records that evidence on the `review` event. This is what makes a recorded `pass` mean *the gate ran and was green* rather than *a reviewer read the diff* — until CAL-1082 the two were byte-identical in the ledger, and the only instruction to run the gate was prose addressed to a model. The verbs own "the durable record **and the gate**"; this is the second half.

**The orchestrator runs the gate; the verb enforces and records it.** The harness is a scaffold, not a toolchain host. Its image cannot carry every target repo's toolchain: `harness:dev` is built `--no-dev`, so not even this repo's own `ruff` is present, a Node target needs Node, and an Xcode target can never run in a Linux container. A verb that *executed* the gate would therefore either grow toward every ecosystem or hand a diff-only `pass` to the repos it could not run — and could never close its own tickets. So the gate runs where the toolchain already lives (the orchestrating session, host-side) and its result is handed to the verb (`--gate-exit <code>`, `--gate-log <path>`). `harness/gate.py` reads `verify:` for the record and bounds the log tail; it holds no execution path.

- GIVEN an open run whose repo configures `verify: "bash scripts/verify.sh"`, and an agent that ran it green
- WHEN the agent runs `harness review --gate-exit 0 --gate-log <path>`
- THEN the engine is invoked, and the `review` event carries `gate_ran=true`, `gate_exit_code=0`, the resolved `gate_command`, and the bounded `gate_output_tail` — all bound to `reviewed_sha`
- AND GIVEN instead **no** `--gate-exit` is supplied, THEN the verb refuses **before invoking any engine**, records **no** event, and exits `5` with `reason=no_gate_evidence` — silence is not a pass
- AND GIVEN instead `--gate-exit` is non-zero, THEN the verb refuses the same way and exits `5` with `{ "error": ..., "reason": "gate_failed", "gate_output_tail": ... }` — the harness does not review a red tree, and spends no tokens doing it. The bounded (≤ 2 KB) tail is a deliberate exception to context economy: it is the *reason for the refusal*, so the agent can fix what broke without re-reading the whole log.
- AND GIVEN instead the repo configures no `verify:` at all, THEN the engine runs and the event records `gate_ran=false, gate_reason="not_configured"` — the harness cannot gate what a repo does not define, so the ledger states the absence plainly instead of implying a gate ran, and `close` allows that pass.

The evidence is checked **after** the spend breakers below (a run already bounded out is refused on that, not on its gate) and **after** the design check that follows.

#### Scenario: the design stage is required before any engine

ADR [`0007`](../decisions/0007-design-verb.md) makes `design` a stage of every run, and `review` is where that is enforced (decision **D3**). Without enforcement the stage is advisory and compliance decays on exactly the unattended runs it exists for; without linkage the engine never sees the design, so the `(fix → review)*` loop re-derives intent each cycle instead of converging on conformance.

- GIVEN an open run with **no** `design` event on record
- WHEN the agent runs `harness review`
- THEN the verb refuses **before invoking any engine**, records **no** `review` event, and exits `5` with `reason=no_design` — the `no_gate_evidence` philosophy: silence is not a pass
- AND GIVEN instead the run's latest `design` event carries `status="failed"`, THEN it is **not** refused: D4 degrades and records, so the check is that a design was *attempted and recorded*, never that it succeeded, and an engine flake costs a run its design but never its ability to ship
- AND GIVEN an `ok` design event and `--design-file <path>` whose content hashes to the event's `design_hash`, THEN that design is given to the review engine as context, so the diff is reviewed against the ticket **and** the design; the `review` event records `design_context=true`
- AND GIVEN an `ok` design event but no `--design-file` (or one that cannot be read or matched), THEN the review proceeds with no design context and records `design_context=false` — a mismatch also warns on stderr

The design check runs **before** the gate-evidence check above: a run that never recorded a design is malformed regardless of its gate colour, so refusing on the gate first would report a transient tree state while masking a missing lifecycle stage. It runs **after** the spend breakers, which stop a bounded-out run before any further work, and before the tracker park, so a refused run leaves its ticket where it stopped.

**Enforcement refuses; context degrades.** The two halves have deliberately different postures. Enforcement keys on the ledger alone — `--design-file` can neither satisfy nor bypass it — so it refuses. The design *body* is not in the ledger (the event carries `design_hash`; the body lives on the ticket as a marked comment), so the orchestrator that ran `harness design` hands its `design_markdown` back and the recorded hash authenticates it. Context is enrichment: the safe outcome — never reviewing against a wrong or unverified design — is fully achieved by dropping it, so refusing there would only add a wedge. `close` is unchanged: its gate already requires a passing review, which now transitively requires a recorded design attempt.

**The evidence is self-reported, deliberately.** It moves no trust boundary: any process that can write the workspace can already forge a ledger event, so a fabricated `--gate-exit 0` is the same class of act as a fabricated event, and the ledger's filesystem trust boundary is unchanged. The authoritative control over what actually merges is server-side branch protection (CAL-1029), not this record. What the record buys is that a `pass` now *states* whether a gate ran, so a reader — and `close` — can tell a verified tree from an unverified one. Cryptographic attestation was weighed and left out of scope. This design also removes the pressure to loosen the review container toward foreign toolchains, which ADR 0002 rejected for good reason.

#### Scenario: the spend breakers bound the fix loop

The `review` verb is the loop boundary, so it enforces two **ledger-backed spend breakers** there (`harness/loop_budget.py`; thresholds read from `CONTEXT.md` → `loop:`, defaults `max_review_cycles: 6` / `wall_clock_budget_minutes: 90`). The harness cannot see the orchestrating session's token meter, but it can observe the ledger — so it bounds the *behaviours* that burn tokens:

- GIVEN a run that has already recorded **5** `review` events
- WHEN the agent runs `harness review` a 6th time
- THEN the verb refuses **before invoking any engine**, records **no** `review` event, and exits `4` with `{ "error": ..., "reason": "review_cycle_ceiling" }` — the run stops and escalates to the user (cycles 1–3 run unconditionally; cycles 4–5 carry a `convergence_check_required` advisory on a fail so the agent assesses convergence; the 6th is the hard ceiling, double the unconditional three).
- AND likewise, GIVEN a run whose `started_at` is older than the 90-minute wall-clock budget, WHEN the agent runs `harness review`, THEN the verb refuses the same way with `reason=wall_clock_budget` (deliberately mirroring the stale-run reclamation staleness threshold — if one moves, move both).

This is the one coherent stop rule `agents/reviewer.md` and `commands/harness.md` also state. The breakers are checked at the verb boundary, not mid-session: a run that runs away *between* verbs is bounded by the wall-clock check at the next boundary, not interrupted mid-thought — the honest limit of ledger-backed breakers, and the reason true token/$ metering is deferred.

### `close` — enforce the gate, then merge

`harness close <ticket> --run-id <id>` enforces the gate, integrates the current `origin/<base>`, merges the already-committed HEAD to the base branch, pushes, transitions the ticket to Done, and finalizes the run.

#### Scenario: the gate is satisfied

- GIVEN an open run with a clean worktree and a `verdict=pass` whose `reviewed_sha` equals HEAD
- WHEN the agent runs `harness close <ticket> --run-id <id>`
- THEN the verb merges the run branch into `origin/<base>` **in a throwaway worktree** (`git merge --no-ff`), pushes the merge commit to `origin/<base>`, transitions the ticket to Done **and confirms it landed against the mutation's own post-write state** (#233, `harness/linear.py`, `harness/github.py`), flips the run to `status=closed`, and emits `CloseOutput` (`run_id`, `ticket`, `reviewed_sha`, `merged`, `ticket_done`, `status`) — the main checkout is never touched (CAL-1154)

#### Scenario: the base advanced during the run

- GIVEN an open run that passed review, and `origin/<base>` has advanced since `start` with non-conflicting work (a concurrent run landed a ticket)
- WHEN the agent runs `harness close <ticket> --run-id <id>`
- THEN the verb fetches `origin/<base>` and bases the throwaway merge worktree on that current tip **before** merging, so the push lands rather than being rejected non-fast-forward (CAL-777); the HEAD-bound gate is preserved — the reviewed SHA is the merge's second parent, so only the reviewed commit's content rides in
- AND GIVEN instead the run branch conflicts with what landed on `origin/<base>`, the verb tears the throwaway worktree down wholesale and exits 1 with a clear message (not a raw git conflict dump), leaving the run open and resumable — rebase the run branch on the updated base, re-review, and close again

#### Scenario: a gate refusal

- GIVEN an open run that does not satisfy the gate
- WHEN the agent runs `harness close`
- THEN the verb exits 2 with exactly one structured `reason`: `no_run` (no `start` row), `dirty_worktree` (uncommitted edits — never reviewed), `no_passing_review` (no `verdict=pass` on record), `stale_review` (a pass exists but HEAD moved after it), or `no_gate_evidence` (a pass covers HEAD but cannot show the repo's verify gate ran)

#### Scenario: the ticket-Done transition cannot be confirmed

- GIVEN the merge has already landed, and the tracker's transition mutation either raises or reports success without a post-write state matching the one requested (#233)
- WHEN the agent runs `harness close`
- THEN the verb exits **1** — not a gate refusal, because the merge already landed — with `merged: true` and one of two `reason`s: `ticket_transition_failed` (the tracker raised) or `ticket_transition_unconfirmed` (the mutation reported success, but its own response shows the state never took); the run row stays `open` and no `close` event is written, so re-running `harness close` is the recovery once the tracker is healthy (the merge/push step is idempotent for an already-landed run branch)

#### Scenario: the merge never touches the main checkout

- GIVEN an open run whose gate is satisfied, and a main checkout in **any** state — clean, carrying uncommitted edits, or even mid-merge
- WHEN the agent runs `harness close`
- THEN the merge runs in a detached throwaway worktree at `.worktrees/harness/<run_id>-close` based on `origin/<base>`; the main checkout is byte-identical before and after, on both the success and the conflict path (CAL-1154)

`close` merges off the main checkout entirely (`harness.close_merge`, mirroring `harness.promotion`): it fetches `origin/<base>`, merges the run branch in a throwaway worktree, pushes the merge commit to `origin/<base>`, and removes the worktree. The guarantee is **structural, not defended** — there is no shared tree to strand, so no base-checkout precondition to check and no restore that can fail. This retired the CAL-1151 `dirty_base_checkout` refusal (its precondition is now unreachable) and, with it, that reason from the locked refusal-reason contract. A conflict tears the whole worktree down (no `git merge --abort` on any shared tree) and exits 1 with the same clear message as before; a push rejected non-fast-forward — two concurrent closes racing the same base — also exits 1, and the loser retries (its next fetch sees the winner's tip). Because the local `<base>` branch is no longer advanced by a close, the `start` and `worktrees cleanup` readers base off `origin/<base>` (see [`worktree-lifecycle.md`](worktree-lifecycle.md)).

`no_gate_evidence` is the backstop under the gate step above (CAL-1082): a pass recorded by a harness that predates the verify gate carries no `gate_ran` key, `json_extract` yields `NULL`, and close reads that as *no evidence a test ever ran* and refuses. Fail-safe by construction — an old pass cannot be spent on a merge, and no ledger migration is needed. A pass whose `gate_reason` is `not_configured` is allowed: the repo defines no gate, and the ledger says so honestly. (Whether `close` should tighten *that* is a separate decision — it would strand every repo without a `verify:`.)

`close` does **not** auto-commit. A dirty worktree is refused outright, because uncommitted edits are not in HEAD and so were never reviewed (`stale_review` catches a commit *after* review; only the clean-tree check catches an edit *without* committing — CAL-586, locked by `test_cli_close.py::test_dirty_worktree_refused_when_uncommitted_edits`). A gate refusal is the gate doing its job and is never worked around — the verb never bypasses its own gate.

**The ticket-Done transition is verified, not trusted (#233).** A mutation that reports success is not proof the tracker's state actually changed — its acknowledgement can arrive detached from the write it names, or a tracker-side rule can silently keep the old value. `LinearClient._transition` and `GitHubClient._set_status` — the one shared implementation behind every transition (`start`'s In Progress, `review`'s In Review, `close`'s Done, `reclaim`'s revert to Todo) — now ride the confirmation on the **same mutation** that already fires: the Linear `issueUpdate` selects `issue { state { id name } }` back, and the GitHub `updateProjectV2ItemFieldValue` selects `fieldValueByName` back, so confirming costs no extra round trip and opens no write-then-read replica-lag window. When the returned post-write state doesn't match the one requested — or is missing entirely — the client raises `TrackerTransitionUnconfirmed` (`harness/tracker_errors.py`), a `TrackerRequestError` subclass, so every verb that already catches that base handles it as the tracker failure it already models; only `close` branches on the subclass itself, to attach its own `ticket_transition_unconfirmed` reason (distinct from a raised `ticket_transition_failed`, above) — both are exit-1, not gate refusals, because the merge already landed.

### The tracker switch — `tracker:`

Every tracker touchpoint above is conditional on the target repo's `CONTEXT.md` → `tracker:` (CAL-1104, CAL-1164). `tracker: linear | github | none` is the **single source of truth** for whether a tracker is wired and which backend — one top-level field, so no second boolean can contradict it. It replaces the CAL-1104 `layers.linear` switch, whose name collided with the `repo.linear` address and whose on/off state was derivable from — yet unenforced against — that address. The switch is read by `harness/layers.py` (`tracker()` / `linear_enabled()`), the same read-config-from-CONTEXT-by-regex shape as `harness/loop_budget.py` (breaker thresholds) and `harness/gate.py`. It defaults **on** (`linear`), so everything above describes the ordinary case. `github` selects the GitHub Issues backend (Projects v2 status, CAL-1105 — its own subsection below).

#### Scenario: a repo with no tracker

- GIVEN a repo whose `CONTEXT.md` sets `tracker: none`, and **no** `LINEAR_API_KEY`
- WHEN the agent drives `start → design → review → close`
- THEN no verb validates a key, fetches an issue, or transitions anything, and the run completes green (the `design` case was added to this path by #218)
- AND `start`'s `<ticket>` argument is an **opaque run identifier** — carried verbatim (so `idx_runs_ticket_open` still refuses a duplicate open run) and emitted with `title` / `description` / `url` / `id` left `null` rather than invented
- AND `close` reports `ticket_done: false` — the honest record of a transition that did not happen, not a failure
- AND `reclaim` keeps its local half (reconcile the ledger, preserve the branch) and skips the revert; `reclaim --stale` is a clean no-op, because staleness keys entirely on the tracker's `updatedAt` and there is nothing to enumerate

The gate is **unchanged** by the switch: `close` evaluates the reviewed-SHA gate *before* the tracker step, so a tracker-less close with no passing review still refuses `no_passing_review`. Tracker-less does not mean gate-less — pinned by `test_tracker_less_layer.py`.

The default is deliberately conservative: a missing `CONTEXT.md`, a missing `tracker:` key (with no `layers.linear`), or an unrecognised value all read as **on** (`linear`). A repo that has not opted out keeps today's behaviour — including failing fast on a missing `LINEAR_API_KEY` — rather than degrading into a tracker-less run because a file could not be parsed. **Back-compat:** a repo not yet migrated has no `tracker:` key, so the reader falls back to `layers.linear` (`false` → `none`, otherwise → `linear`); that fallback still resolves the `layers:` block before matching, because `linear:` appears twice in an un-migrated `CONTEXT.md` (`repo.linear`, the team prefix; `layers.linear`, the old switch) and an unscoped match reads the prefix first. An **incoherent** switch/address pair — `tracker: linear` with no `repo.linear`, `tracker: none` with a dangling address, or a lingering `layers.linear` that disagrees with an explicit `tracker:` — is rejected up front by `start` (`tracker_config_error`, pinned by `test_tracker.py` and `test_cli_start.py`), before any key check or side effect.

`review` has no tracker touchpoint to gate: it records a verdict to the ledger and never calls the tracker. Should it gain one (CAL-1103 would move the ticket to In Review), that transition takes the same layer check.

#### The tracker seam — one factory, backend-agnostic verbs

The switch above resolves *which* backend; the **seam** is *how* the verbs consume it. No verb constructs a tracker client directly — each obtains one from a single factory, `harness.tracker.tracker_client(repo_root)`, and calls the `Tracker` protocol (`harness/tracker.py`, CAL-1197). `LinearClient` and `GitHubClient` are two structural implementations of that protocol; the factory reads the switch (`harness.layers.tracker`) and returns the matching one:

- `tracker: linear` → a `LinearClient` (a missing `LINEAR_API_KEY` raises `LinearConfigError`, which each verb maps to its own exit code, exactly as before the seam);
- `tracker: none` → `None`, and the verb runs tracker-less (the scenario above) — the factory returns *without* reaching for a credential;
- `tracker: github` → a `GitHubClient` built from the `github:` config block and `GITHUB_TOKEN` (CAL-1105); an absent/incomplete config block or a missing token raises `GitHubConfigError`, so a *misconfigured* github repo fails loudly (never a silent no-op tracker), while a *correctly configured* one gets a working backend.

Both backends' boundary exceptions subclass the tracker-agnostic bases in `harness/tracker_errors.py` (`TrackerConfigError` / `TrackerNotFound` / `TrackerRequestError`), so the verbs catch failures **without naming a backend** — `except TrackerNotFound` catches a Linear-or-GitHub not-found alike. Because backend selection lives in that one factory, a second backend slots in **without touching a verb**: `start`, `close`, `defer`, `reclaim`, and `review`'s post-verdict transition all depend only on the `Tracker` protocol and the agnostic errors. `test_tracker_seam.py` pins the contract — both clients satisfy the protocol structurally (`@runtime_checkable`), the factory returns a Linear client for `linear`, a GitHub client for a configured `github`, `None` for `none`, and `GitHubConfigError` for a github repo with no config block.

#### The GitHub backend — Projects v2 status (CAL-1105)

GitHub Issues have **no native workflow states**, so the design decision this backend records (AC-4): the harness maps its states onto a **Projects v2 single-select field** (default name `Status`), *not* labels. The issue is an item on a configured board, and a transition sets that item's field to the option whose **name** matches the target state — `todo`→*Todo*, `in_progress`→*In Progress*, `in_review`→*In Review*, `done`→*Done*, matched case-insensitively. This mirrors `LinearClient`'s name-then-resolve discipline (never a hard-coded option UUID): the board owns the option ids, the client resolves them at runtime via `updateProjectV2ItemFieldValue`, and an issue not yet on the board is added on its first transition. Projects v2 fields were chosen over labels for first-class, mutually-exclusive status (a label set can hold two states at once; a single-select cannot) at the cost of a pre-configured board and the token's `project` scope. Rejected alternative — labels: simplest/greppable, but state is not first-class and nothing enforces one-state-at-a-time.

Config lives in a `github:` block, read by `harness/layers.py` (`github_settings`, the same regex-over-CONTEXT shape as the switch): `repo: <owner>/<name>` (the issues repo), `project: <owner>/<number>` (the board, user- or org-owned — resolved via `repositoryOwner.__typename`), and an optional `status_field:` (default `Status`). `tracker_config_error` rejects `tracker: github` with no `github:` block up front at `start`. The `<ticket>` identifier is the **issue number** (`42`, or `#42`); the repo is pinned by config, so one tracker serves one repo. Auth is `GITHUB_TOKEN` (env-only, the same rule as `LINEAR_API_KEY`), needing the `repo` and `project` scopes. Resume/handoff markers (the reclamation and context-rollover readers) work identically as **issue comments** — the same two distinct marker strings and the `reclaimed`-label gate on resume — over `harness.reclaim_marker`. `test_github.py` pins the method contracts against a stubbed transport; the live `start → review → close` proof against a real board is recorded in this ticket's build log.

**The harness repo dogfoods this backend (CAL-1204).** `sluengen/harness`'s own `CONTEXT.md` sets `tracker: github` against the **"Harness"** Projects v2 board and drives the **built-in `Status` field** (the default — no `status_field` configured), so its transitions show on the board's default view (issue #172). The four states are carried by that built-in field; "In Review" is added to it via `updateProjectV2Field` (it is *not* a fixed built-in set — the earlier assumption that the built-in field could not hold "In Review" was wrong). So the harness runs its own verb loop on GitHub Issues. `repo.project` is the board title (`Harness`), though since #248 that match is no longer load-bearing — on GitHub the board *is* the queue, so `fetch_queue_membership` answers from board membership and ignores `repo.project` entirely; `repo.linear`/`env.linear_token` are retained but read only when `tracker: linear` (kept for reference/rollback). `test_layers.py` and `test_tracker.py` pin the own-context tracker as `github`.

### Routing discipline

The ledger is a complete audit trail only if nothing hand-rolls a `git merge` / `push` or a Linear mutation for the run lifecycle. Every git/ticket state transition routes through a verb; `close` validates against the ledger as a backstop (decision D5). The `/harness run` skill ([`commands/harness.md`](../../commands/harness.md)) forbids out-of-band mutation.

### Triggers

One execution model, **two triggers** that produce an identical execution path: a human (`/harness run <ticket>`) or Hermes (the autonomous trigger slot — deferred; the launcher/trigger scaffolding was removed in CAL-712, design archived at [`hermes-orchestration.md`](../retired/hermes-orchestration.md)). A trigger launches a per-session Claude runtime; each verb runs as a one-shot container *outside* that runtime, exactly as `~/bin/harness` is a `docker run`.

## Interface surface

The verbs are part of the CLI surface; their flags, exit codes, and JSON shapes are documented in [cli-surface.md](cli-surface.md), and the agent-facing contract is [`commands/harness.md`](../../commands/harness.md). The verb implementations live in `harness/cli/start.py`, `harness/cli/design.py`, `harness/cli/review.py`, `harness/cli/close.py`; the emitted CLI JSON is locked by `test_verb_contract_locked.py`.

Every verb raises one control-flow exception — `VerbError` (`harness/cli/_verb.py`) — and translates it through one epilogue, `run_verb`, so the error-JSON shape is single-sourced rather than re-declared per verb (CAL-1013). The shape: `{"error": <message>}` on stdout under `--json`, plus a machine-readable `"reason"` **only when set** (absent, never `null`). `review` and `close` set a `reason` (the gate-refusal kinds above; an infra-wall tag for `review`); the other verbs leave it unset, keeping their bare `{"error"}` shape. The `--json` *default* stays a per-verb choice (orchestrator-consumed verbs default it on; the human-facing `reclaim` / `cancel` default it off) and is deliberately not unified. `reclaim` emits a typed `ReclaimOutput` / `SweepOutput` like every sibling verb.

**A missing ledger is a distinct refusal from "no open run" (#244).** `checkpoint` / `review` / `close` / `design` all resolve their open run through the one shared `resolve_open_run` (`harness/cli/_runs.py`). Before, a `db_path` that did not exist on disk resolved to the same `None` as a ledger that was read but held no matching `status='open'` row, so every caller rendered both as `no open run found for worktree ...` — hiding the common real cause (the verb was invoked from outside the repo that owns the run) behind a message that reads like a dead or absent run. `resolve_open_run` now raises `LedgerNotFoundError` (a `VerbError` subclass, `reason="no_ledger"`, naming the resolved `ledger_path` in `extra`) in place of the old `return None`; the historical `no open run found` message and its per-verb `reason` (`close`'s `no_run`) are unchanged for the case where the ledger genuinely holds no open row. Because every caller goes through `run_verb`'s shared `VerbError` handling, the fix reaches all four verbs from the one resolver — no per-caller edit.

## Known limitations

- The orchestration *between* verbs is deliberately not reproducible: it varies with the agent, which buys full context retention and graceful degradation to manual driving on a verb failure (decision D1). Reproducibility applies to the verbs, not the end-to-end run.
- A run can be abandoned without merging via `harness cancel` (close-without-merge); see [cli-surface.md](cli-surface.md).
- A run whose orchestrator died mid-flight is recovered via `harness reclaim` — it reverts the stranded Linear ticket to Todo (so dependents unblock) and reuses `cancel`'s ledger transaction to clear the `open` row, while preserving the worktree/branch. See [run-ledger.md](run-ledger.md) and the accepted proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md). Tracker-less (`tracker: none`) only the local half runs, and the time-keyed `--stale` sweep has no tracker state to read — so recovering a dead run there is a manual `reclaim <run-id>`, not an automatic sweep.

## Decisions

The cross-cutting decisions that shaped the verb model — D1 (orchestration inversion), D2 (the reviewed-SHA gate), D5 (routing discipline) — are recorded once in [`specs/architecture-principles.md`](../architecture-principles.md) and referenced from here, not duplicated.

## Cross-references

- [run-ledger.md](run-ledger.md) — the SQLite ledger the verbs read and write
- [worktree-lifecycle.md](worktree-lifecycle.md) — the isolated worktree `start` creates and `close` merges
- [cli-surface.md](cli-surface.md) — the full command surface, flags, exit codes, JSON
- [`specs/architecture-principles.md`](../architecture-principles.md) — the orchestration-inversion decision record
- [`specs/proposals/harness-as-tool.md`](../proposals/harness-as-tool.md) — the accepted model
