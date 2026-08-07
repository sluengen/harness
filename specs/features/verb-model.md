---
feature: verb-model
status: implemented
last_updated: 2026-08-08
tickets: [CAL-570, CAL-574, CAL-586, CAL-661, CAL-925, CAL-1082, CAL-1104, CAL-1197, "#244", "#295", "#296", "#297", "#298", "#299", "#329", "#300", "#301", "#315", "#321", "#339", "#338", "#359", "#363", "#352"]
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
- AND it emits a `StartOutput` JSON object (`run_id`, ticket context, `worktree_path`, `worktree_branch`, `base_branch`, `attended`, `assurance`, `assurance_reason`)

`--attended` declares that an operator is present ([ADR 0011](../decisions/0011-attended-run-spend-scope.md), #295). The mode is recorded in the run row's `inputs_json` and echoed as `attended` so the orchestrator confirms what was stored. Unattended is the default and the failure default: an undeclared run writes the byte-identical `"{}"` it always has, and only the literal JSON `true` reads back as attended — declaring it opts a run out of the wall clock, the only ceiling on autonomous spend, so every ambiguous value fails toward the bound. Attendance is **fixed at `start`**; nothing mutates it afterwards. Both readers have shipped: `review` reads it to scope the wall-clock breaker to unattended runs (#296), and `reclaim --stale` reads it to select which staleness threshold to measure the run against (#297). `/harness run` is the one caller that declares the flag, and no routine path passes it (#298) — the erosion guard ADR 0011 names as the mechanism's only enforcement.

`start` also resolves the run's **assurance** and snapshots it on the row (#352, proposal [`assurance-led-lifecycle`](../proposals/assurance-led-lifecycle.md)). The issue carries the intent as an `assurance:<level>` label over the closed vocabulary `trivial | simple | complex`; the level decides which lifecycle stages the run is required to pay for, and [`harness/assurance.py`](../../harness/assurance.py) is its single home — the vocabulary, the resolution, the ledger coercion, and the required-stages table `design` and `review` both read.

| Assurance | Design | LLM review |
|---|---|---|
| `trivial` | no | no |
| `simple` | no | yes |
| `complex` | a design that **succeeded** | yes |

No new tracker round-trip: `labels` is already in the payload `start` fetched, so a tracker-less run simply has none to read. Resolution is **total and fails safe in one direction** — no label, two conflicting levels, an uninterpretable `assurance:*` value, and a `NULL` column on a row written before the migration all read as `simple`, the level that still requires a review. The recorded `assurance_reason` says which of those it was (`label`, `no_label`, `conflicting_labels`, `unknown_label`, `fast_path_unavailable`, `unrecorded`), because a run that silently lost its operator's stated intent is what an audit needs to see; the three reasons that mean *you stated something and it was not honoured* also warn on stderr. A bad label is never a refusal.

**`trivial` is recognized and rewritten.** It is in the vocabulary because the vocabulary is the decided policy, but no run can snapshot it: `start` upgrades it to `simple` with reason `fast_path_unavailable`, since the deterministic certification path that makes skipping a review safe is item 2 of the proposal and is not built. So the `llm_review` column above has no consumer yet — every level a run can currently hold requires a review.

**It is a snapshot, not a cache.** `start` is its only writer and nothing mutates it, so `design` and `review` read the run row rather than re-reading labels: a label edited mid-run cannot remove a requirement the run was opened under. A repeat `start` reports the *recorded* pair for the same reason `attended` does.

The Linear transition is the only non-local side effect, and it runs **last**: if the worktree creation or the ledger insert fails, nothing has touched Linear. The rollback ordering is locked by `test_cli_start.py::test_worktree_failure_leaves_no_db_row_and_no_transition` and `::test_db_failure_removes_worktree_and_no_transition`. The open run is recorded as the `runs` row, not as an event.

#### Scenario: a ticket that already has an open run

- GIVEN a ticket that already has an `open` run
- WHEN the agent runs `harness start <ticket>` again
- THEN `start` resolves the existing open run (keyed on the canonical Linear identifier) and **returns it successfully** (exit 0) — it does not create a second worktree or row, and does not error (`harness/cli/start.py`, step 4: `if existing is not None: return existing`)

The partial unique index `idx_runs_ticket_open` is the database-level backstop for the concurrent-race path: if two `start` calls both pass the existence check, the index refuses the second insert and that loser cleans up its worktree and surfaces the run that beat it (at most one `open` run per ticket).

### `design` — produce the run's technical design

`harness design --run-id <id> [--model <alias>]` runs a dedicated **Opus** engine over the worktree and the ticket in a fresh, dedicated context — uncontaminated by the orchestrator's own state — and produces the change spec's Design section (data model, interface/contract, scenarios, security, test strategy). ADR [`0007`](../decisions/0007-design-verb.md) added it so top-tier thinking happens in a verb-owned subprocess and the session executes against its output, instead of designing by rejection across `(fix → review)*` cycles.

The verb records the design in three places: the ticket, as a marked comment; the ledger, as a `design` event carrying the design's content hash and the `grounded_sha` it studied; and stdout, as `DesignOutput`.

**The engine's output channel is a file** (#294). The verb allocates one file in a fresh directory **outside the worktree**, grants the engine write capability for that single path and nothing else, tells it to write the Design section there, and removes the directory on every path — so nothing the design stage does can leave an untracked file behind and trip `close`'s `dirty_worktree` gate. The `design` event records `channel` (`file`, or `stdout` when only the fallback below delivered) and `design_chars`.

This replaced the `SUBMIT: <json>` line design had inherited from `review`. That contract fits `review` — a fixed shape under 100 characters — and does not fit a 14–17 KB Markdown document, which it forced onto one physical line with every newline escaped and no structural landmark anywhere in it. Measured on this repo's ledger before the change, `design` lost **12.5% of attempts** to the wire format against `review`'s **0.24%**; one run lost 12m44s of Opus and a complete design because a single closing brace never arrived. `review`'s contract is deliberately untouched.

A **stdout fallback** — the design between two nonce-marked lines — is the second channel, and it is a detector as much as a fallback: no test can spawn a real `claude`, so a permission-config regression would otherwise take the stage from working to producing nothing, invisibly. With it, that degrades to a design on the wrong channel, recorded as `channel="stdout"` and warned about on stderr. The fallback also tolerates a **missing closing marker**, so an engine that finishes its design and drops the final line still delivers it — the salvage the JSON contract could not offer.

**The stage is conditional on the run's assurance** (#352). ADR 0007 D1 ran it for every ticket whatever its judged difficulty; it now runs only where the run snapshotted a level that requires a design, which today means `complex` alone. (ADR 0005's per-ticket model-tier labels are a separate, retired mechanism — #321 — and never gated this stage.) The check reads the run row, before the adopt path and before any engine:

- GIVEN an open run whose assurance does not require a design (`simple`, or a row written before the migration)
- WHEN the agent runs `harness design --run-id <id>`
- THEN the verb invokes **no engine**, reads **no ticket**, records **no `design` event** and posts **no comment**, and exits `0` emitting the same locked `DesignOutput` key set with `status="not_required"` and an empty `design_markdown`

`status` is where the skip is reported, so the output contract keeps its six keys and the orchestrator branches on a value rather than on a missing field; an empty `design_markdown` says plainly there is nothing to stage for `review`'s `--design-file`. `not_required` is deliberately **not** a third `design` *event* status: `resolve_design_gate`, the adopt path's authentication, and the ledger statistics all key on `status != "ok"`, so a new event status would silently reclassify events for three readers. Nothing is written to the ledger on this path at all — a skipped stage must not manufacture the artifact a `complex` review would later demand. `--model` is accepted and ignored: engine and model selection stay orthogonal to assurance.

- GIVEN an open run
- WHEN the agent runs `harness design --run-id <id>`
- THEN the verb records a `design` event with `status="ok"`, `design_hash`, and the `grounded_sha` it studied, posts the design as a marked ticket comment, and emits `DesignOutput` on stdout
- THEN the `design` event also carries `channel` (which of the two channels delivered) and `design_chars` (the design's length) — the second being the measuring instrument for the length target the prompt states
- AND GIVEN instead the engine is killed, cannot be spawned, delivers a design on **neither** channel (`reason="no_design_output"`, which replaced `no_submit` / `malformed_submit` here — a file is written or it is not, so the distinction the JSON format created no longer exists), or the ticket spec cannot be read, THEN the verb records a `design` event with `status="failed"` and a stable `reason`, posts **no** comment, and exits `3` (decision **D4**: every failure mode degrades and records)
- AND GIVEN a `failed` design event on a run that does **not** require a design, WHEN the agent runs `harness review`, THEN review is **not** refused — ADR 0007 D4's degradation, now scoped to those levels, so an infra flake costs such a run its design but never its ability to ship. On a `complex` run the same event **is** refused (see `review` below)

**A failed design is not a stop.** The orchestrator proceeds to implement without one rather than re-running the verb in a loop chasing a green result; a re-run is legitimate (the latest event is authoritative and nothing is mutated), but the run is not blocked either way. How `review` consumes the design — enforcement on the ledger, context via `--design-file` — is the "design stage is required" scenario under [`review`](#review--record-a-verdict-bound-to-the-reviewed-sha) below.

### `review` — record a verdict bound to the reviewed SHA

`harness review [--run-id <id>] [--engine claude|codex]` runs the selected review engine (`--engine`, **default `claude`**; CAL-701) against the worktree's current HEAD and records a verdict **bound to the exact SHA reviewed** — the load-bearing detail behind decision D2: the `close` gate refuses a pass whose SHA ≠ HEAD, so a stale pass cannot be reused. Each engine is a **read-only CLI subprocess** (`claude -p --permission-mode plan` or `codex exec --sandbox read-only`) emitting the same `SUBMIT:` contract — never the Agent SDK (see the "Review engine" principle in `architecture-principles.md`).

**The in-container review engine is Claude; `--engine codex` is host-only** (ADR [0002](../decisions/0002-in-container-review-engine.md), CAL-925). Codex's read-only sandbox wraps each command in `bwrap`, which cannot create a user namespace in the unprivileged `harness:dev` container (`CLONE_NEWUSER` blocked, CAL-866), so a real `--engine codex` review degrades there. Rather than loosen the container's privileges — it reviews untrusted diffs — the decision keeps the container's engine Claude and treats `--engine codex` as a host-only cross-model option, where `bwrap` and `~/.codex` auth are available. So inside `~/bin/harness` and the `/harness run` verb loop, review runs on Claude. ADR [0013](../decisions/0013-codex-engines-in-container.md) amends that reason: the gate is the seccomp profile alone — `CAP_SYS_ADMIN` is neither sufficient nor required — and it chooses a targeted profile instead. The host-only status here stands until that profile ships.

**The claude engine's model is one configured value, the same for every ticket** (#321). It is `CONTEXT.md`'s `loop.review_model` (default `sonnet`, `harness/loop_budget.py`), read off the `LoopBudget` the verb has already loaded for its spend breakers — so resolving it costs no file read and no network call. The alias is appended to the claude command as `--model <alias>` (`_build_cmd`); the codex command is unaffected, since codex ignores `--model`. An explicit `harness review --model <alias>` overrides the configured value outright, for host/testing use.

The value is a **plain string**, not a two-value enum: a third alias is a one-line `CONTEXT.md` edit rather than a code change, and an unrecognized alias reaches the claude CLI and fails there instead of being silently coerced to the default — a review that quietly ran a different model from the one configured is the failure this shape refuses to hide. The loader admits only a bare token (`[A-Za-z0-9._-]+`), so a value carrying whitespace or a shell metacharacter falls back to the default rather than reaching an argv.

This replaced ADR [0005](../decisions/0005-per-ticket-model-tiering.md)'s per-ticket `review:<tier>` / `build:<tier>` labels, which #321 retired: the review dimension was a real control signal that was never once set, and reading it cost a tracker `fetch_issue` round-trip and five degradation branches on every review. A label of that shape still sitting on an issue is inert — nothing reads it.

#### Scenario: a review pass

- GIVEN an open run whose worktree HEAD holds committed work
- WHEN the agent runs `harness review`
- THEN the verb resolves the current run (the `status='open'` run whose `worktree_path` equals `--repo`, or the run named by `--run-id`), enforces the verify-gate evidence (below), captures `git rev-parse HEAD` as `reviewed_sha`, invokes the selected engine with the review prompt on stdin, scans stdout for the first `SUBMIT: <json>` line, and appends a `review` event carrying `{ run_id, reviewed_sha, verdict, issues, engine, convergence_check_required, cycles_exhausted, created_at, gate_ran }` (and optional `gate_command` / `gate_exit_code` / `gate_reason` / `gate_output_tail` / `commit_message` / `deferred_brief`)
- AND it prints **only** the bounded verdict (`verdict`, `issues`, `reviewed_sha`, `run_id`, `engine`, `convergence_check_required`, `cycles_exhausted`, `probes_run`, `probes_survived`) — the engine's full reasoning stays inside the verb (context economy)

A recorded `fail` is still a *successful* review (exit 0): deciding what to do with a verdict is the agent's job, not the verb's. A missing, malformed, or unknown-verdict `SUBMIT` line is **not** one of those verdicts — the reviewer delivered none — so since #270 it is classified as infra rather than as a rejected diff: exit 3 (`EXIT_INFRA_FAILURE`) carrying `reason='no_submit'` (no `SUBMIT:` line anywhere) or `reason='malformed_submit'` (one was seen but none parsed), recorded in #262's refusal shape with no `verdict` key. It therefore consumes no review cycle, cannot open the close gate, and leaves the ticket **In Review** rather than bouncing it back to In Progress — the same treatment the engine timeout and the two sandbox walls already get, on the same stated principle that an engine which never reviewed the diff produced no verdict. The verb still never raises on a bad reviewer; it records the failure. (The two `reason` tags are the ones `design` already uses for the identical failure, shared from `harness/events/payloads.py` so one protocol failure has one name across both engine verbs.)

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

ADR [`0007`](../decisions/0007-design-verb.md) makes `review` the place the design stage is enforced (decision **D3**). Without enforcement the stage is advisory and compliance decays on exactly the unattended runs it exists for; without linkage the engine never sees the design, so the `(fix → review)*` loop re-derives intent each cycle instead of converging on conformance.

**What is enforced is the run's assurance, not the presence of an event** (#352). D3 asked one question of every run — is there a `design` event? — and D4 let a `failed` one answer it, so the gate proved *invocation* rather than a usable outcome: a complex change could ship after the stage produced nothing, while a small one was refused for skipping a stage it did not need. The precondition is now [`harness/assurance.py`](../../harness/assurance.py)'s, called by `resolve_design_gate` and delegated to whole, so the requirement and the refusal are one decision with one home:

| Assurance | Latest `design` event | Result |
|---|---|---|
| `simple` | absent, `failed`, or `ok` | proceed |
| `complex` | absent | refuse `no_design` |
| `complex` | present, `status != "ok"` | refuse `design_not_usable` |
| `complex` | present, `status == "ok"` | proceed |

- GIVEN an open `complex` run with **no** `design` event on record
- WHEN the agent runs `harness review`
- THEN the verb refuses **before invoking any engine**, records no verdict, and exits `5` with `reason=no_design` — the `no_gate_evidence` philosophy: silence is not a pass
- AND GIVEN instead its latest `design` event carries `status="failed"`, THEN it refuses the same way with `reason=design_not_usable` — a distinct tag because "the stage was skipped" and "the stage ran and produced nothing usable" have different remedies, and because `design_failed` already names a review that *proceeded*, so one string meaning both would be unreadable in the ledger
- AND GIVEN a `simple` run with no `design` event at all, THEN review proceeds — that is the ordinary shape after #352, since `harness design` skips the stage for such a run, and refusing it would make the two verbs contradict each other
- AND GIVEN a `simple` run carrying a `failed` event (a run opened before the migration), THEN review proceeds with no design context, recorded as `design_context_reason="design_failed"` — D4's degradation, narrowed rather than removed

Both refusals record the terminal-observation `review` event every terminal path writes since #262, carrying the `reason` and **no `verdict` key**, so the ledger keeps its denominator while `close`'s `$.verdict = 'pass'` filter still reads nothing. The latest `design` event decides, as it already does for context: a failed attempt followed by a successful one proceeds, so re-running `harness design` clears the refusal and an engine flake cannot wedge a `complex` run permanently.

The inherited-pass path (#259) gates on the same answer rather than on the event's presence — a resumed `simple` run has no design event and would otherwise decline inheritance forever, waiting for a `no_design` that can no longer fire. It consults `design_precondition` directly rather than the full design gate, because that gate also reads `--design-file`, and reading it there would open a caller-supplied path *before* the workspace-allowlist refusal (AC-2, #247) that exists to refuse it. What that refusal protects is containment, not its own position in the sequence: a path outside the mounted workspace must never be opened, so the file read stays below it.
- AND GIVEN an `ok` design event and `--design-file <path>` whose content hashes to the event's `design_hash`, THEN that design is given to the review engine as context, so the diff is reviewed against the ticket **and** the design; the `review` event records `design_context=true`
- AND GIVEN an `ok` design event but no `--design-file` (or one that cannot be read or matched), THEN the review proceeds with no design context and records `design_context=false` — a mismatch also warns on stderr

The design check runs **before** the gate-evidence check above: a run that never recorded a design is malformed regardless of its gate colour, so refusing on the gate first would report a transient tree state while masking a missing lifecycle stage. It runs **after** the spend breakers, which stop a bounded-out run before any further work, and before the tracker park, so a refused run leaves its ticket where it stopped.

**Enforcement refuses; context degrades.** The two halves have deliberately different postures. Enforcement keys on the ledger alone — `--design-file` can neither satisfy nor bypass it — so it refuses. The design *body* is not in the ledger (the event carries `design_hash`; the body lives on the ticket as a marked comment), so the orchestrator that ran `harness design` hands its `design_markdown` back and the recorded hash authenticates it. Context is enrichment: the safe outcome — never reviewing against a wrong or unverified design — is fully achieved by dropping it, so refusing there would only add a wedge. `close` is unchanged: its gate already requires a passing review, which now transitively requires a recorded design attempt.

**The evidence is self-reported, deliberately.** It moves no trust boundary: any process that can write the workspace can already forge a ledger event, so a fabricated `--gate-exit 0` is the same class of act as a fabricated event, and the ledger's filesystem trust boundary is unchanged. The authoritative control over what actually merges is server-side branch protection (CAL-1029), not this record. What the record buys is that a `pass` now *states* whether a gate ran, so a reader — and `close` — can tell a verified tree from an unverified one. Cryptographic attestation was weighed and left out of scope. This design also removes the pressure to loosen the review container toward foreign toolchains, which ADR 0002 rejected for good reason.

#### Scenario: the run worktree is too far past its own index to review

A run worktree carrying thousands of untracked files drowns the review engine's tool-using pass. #205 traced that cause and answered it with a rule an operator has to keep — *never gate in the run worktree* — and #208 kept the rule, deliberately routing `uv` at an external environment, and still arrived at review with **3,555 files on disk against 578 tracked**: the review burned the whole `engine_timeout_seconds` ceiling and returned `engine_timeout` having reviewed nothing, while the same tree cleaned to 586/578 returned a real verdict in ~9 minutes. #359 makes the rule a mechanism.

- GIVEN an open run whose worktree holds more untracked files than `loop.untracked_file_limit` (default **1000**) past its git index
- WHEN the agent runs `harness review`
- THEN the verb refuses **before invoking any engine** and exits `5` with `{ "error": ..., "reason": "polluted_worktree", "worktree_pollution": { "tracked": …, "scanned": …, "excess": …, "limit": …, "truncated": …, "largest": [ … ] } }`, leaving the ticket where it stopped
- AND the refusal **costs no review cycle and no wall-clock budget** — it records the ordinary terminal-refusal event (`outcome=failed`, no `verdict` key), which `_count_review_events` excludes, so cleaning up is never more expensive than the burn it replaces
- AND GIVEN instead an excess exactly **equal** to the limit, THEN the engine runs — the configured budget spent is not the budget exceeded
- AND GIVEN instead `loop.untracked_file_limit: 0`, THEN no probe is spawned and no walk happens: `0` is the documented off switch, and it is the reason this key is the one integer knob the loader does **not** clamp to a floor of 1

The `reason` and the exit code are both **distinct from `engine_timeout`** (exit 5, not 3). That distinctness is load-bearing rather than cosmetic: a polluted tree *presents* as an engine timeout, so a shared tag would leave a reader of the ledger unable to tell "the engine hung" from "the harness refused to let it".

It is placed after the HEAD capture and before the tracker park, which fixes all four of its edges: after the inherited-pass short-circuit (that path spawns no engine, so a polluted tree is irrelevant to it and refusing would block a review that costs nothing); after every cheaper pre-engine check, a directory walk being the most expensive of them, so a bounded-out, undesigned or red-gated run is refused on *that*; after the HEAD capture, so the refusal row carries `reviewed_sha` and an operator sees `engine_timeout` and `polluted_worktree` against the same tree — the #208 correlation made legible; and before the park, so the ticket stays In Progress like every other pre-engine refusal.

**The check fails open, without exception.** Every case it cannot answer — the bound disabled, a path that is not a git top-level, a failed or wedged `git ls-files`, an empty index — proceeds to review. A guard that *stops* a run may rest only on evidence it actually gathered, the same asymmetry `reclaim --stale` states for its three clocks; and the failure it prevents is expensive but recoverable, whereas a falsely refused review is not. Two properties follow from the worktree's contents being untrusted (the pollution of #208 was written by tooling nobody has identified, and finding it was explicitly out of scope): the scan reads **directory entries only** — never a file's content, never a `stat` — with symlinks unfollowed and `.git` pruned, so it cannot leave the worktree or fail to terminate; and only **depth-1 path segments** are ever reported, so a root-level `.env.production` is aggregated under `(root)` and never named. What escapes to the ledger and to the orchestrator's context is integers plus at most three top-level segment names.

The measurement is `scanned - tracked` — on-disk count against index size — rather than the size of the set difference, because comparing path *spellings* misses on every non-ASCII name where macOS returns NFD against git's NFC, and would refuse a clean tree: the one direction this guard must never fail in. Subtraction also errs safely, a tracked file deleted from the working tree lowering `scanned` alone. The enumeration and its top-level anchor are shared with `reclaim --stale`'s liveness probe (`harness/_git.py`), so the two cannot disagree about which paths are a worktree's own.

#### Scenario: the reviewer proposes the mutations the builder did not

A mutation table certifies only what its author thought to mutate — and the author is the
person being reviewed. #360's own record holds two instances of what that costs: an aggregate
assertion in #207 that reported a kill it never made, and four entries in #336 that evaluated
to the original value and printed SURVIVED. The one party positioned to be an independent
counterparty on that table was, until #363, the one party that could not run anything: the
review engine is `claude -p --permission-mode plan` / `codex exec --sandbox read-only`, and it
stays exactly that. What changes is that it may now *propose*, and the verb runs what it
proposed.

- GIVEN `loop.probe_max_entries` is positive, WHEN the engine reviews, THEN its prompt asks for
  up to that many mutation entries in `scripts/mutate.py`'s table format, emitted as a `probes`
  array on the same `SUBMIT:` line — an addition to that contract, never a new way to fail it,
  so a malformed `probes` value is dropped and counted while the verdict stands
- AND THEN the verb creates a **detached throwaway worktree at the reviewed SHA**
  (`.worktrees/harness/<run_id>-probe`, `harness/probe_tree.py`), screens the proposals against
  it, renders the survivors of that screen as a table, and runs the mutation harness over it
  under `loop.probe_budget_seconds`
- AND GIVEN an entry whose mutation **survives** with an observable that moved, THEN it is
  recorded in `probe_demonstrated`, a **second engine pass** is given the outcomes and the
  first pass's own findings, and its `[probe:<id>]` finding joins the recorded issues
- AND GIVEN an entry that kills nothing, or one that breaks collection, THEN it is a failure of
  **the entry** — `mispredicted`, `inert` or `errored` per #360's set-equality rule and #365's
  liveness fork — recorded on the event and shown to no one. It is never a survivor and never a
  finding
- AND GIVEN the run worktree is not byte-identical to what it was before the engine ran, THEN
  the verb exits `3` with `reason=run_worktree_mutated`, records the refusal, and records no
  verdict

**Three bounds, and each one is enforced rather than conventional.** The count cap
(`loop.probe_max_entries`, default 3) truncates the proposal and *names* what it cut. The time
ceiling (`loop.probe_budget_seconds`, default 720) kills the subprocess, and the loader clamps
it to whatever `engine_timeout_seconds` is actually configured to, so one review's added cost
can never exceed one engine's ceiling — raising `engine_timeout_seconds` to buy a probe more
time is the standing "the ceiling is not the fix" rule wearing a new hat. And the `select` the
table runs under is **verb-owned**, never proposable: a reviewer that could choose the selection
could spend the budget N+1 times over the whole suite. `probe_max_entries: 0` disables the stage
outright, and the prompt then omits the request entirely, so the review is byte-identical to
what it was before this change.

**A probe must predict its outcome.** This is #360 AC-1's rule, and here it is what stops the
vacuity this repo pays for from simply relocating into review. A reviewer that runs a suite,
reads green and concludes "verified" has produced a feeling; an entry that declares the tests it
must kill and is judged against that produces evidence. So `kills` is required, and the
distinction between a *demonstrated* survivor (an observable moved) and an *unproven* one
(nothing showed the edit was live, as four of #336's twenty entries were not) is carried all the
way onto the event — which is what makes "was this finding demonstrated or argued" a ledger
question.

**Nothing this grants can reach the reviewed SHA.** The probe tree is a different directory at
the same commit, so the run worktree is untouched by construction rather than by configuration.
Be plain about what the identity check is: it detects what **git can see** — a tracked edit, a
deletion, an untracked addition, HEAD moving — and not a write inside a gitignored path. It is a
detector at the boundary; the boundary is `close`'s two conjuncts, a pass bound to current HEAD
**and** its separate refusal of a dirty worktree, which is why the failure mode of a misbehaving
prober is a **wedged run rather than a laundered merge**. Execution itself is bounded not by a
sandbox but by shape: a mutation is applied by one tool with a fixed argv the reviewer cannot
influence — no shell, no free-form command, no flags from the proposal — running at the reviewed
SHA in a tree that is thrown away. That is an agent-layer control, the same honesty
`design`'s single-file write grant states about itself.

**Every path degrades.** `probe_status` records which: `disabled`, `none_proposed`,
`no_instrument`, `tree_failed`, `ran`, `refused:<rule>`, `unavailable`, `timeout`, `error`.
A refusal carries the mutation harness's own stable tag for *which* rule refused, because
the distinction is the diagnostic value: `refused:prediction` says the reviewer named a node
id outside the selection — a defect in its proposal, and the measurement that decides whether
a probing reviewer earns its cost — while `refused:baseline` says the tree was already red and
says nothing about the reviewer at all. None of
them changes a verdict, which is exactly why the reason has to be on the ledger rather than on
stderr — the same argument `design_context_reason` makes. `unavailable` is worth naming
separately because it is the expected **in-container** outcome: `harness:dev` is built
`--no-dev` and carries no pytest, the same catch-22 `harness/gate.py` records for the verify
gate, so the stage runs on a host-side install and degrades honestly in the container rather
than reporting something that reads like a defect in the diff.

**The measured cost, stated rather than assumed** (AC-5). Sampled on this repo, host-side and
warm, at the verb-owned `-m "unit or guard"` selection: the mutation harness's own baseline run
is **81.5s over 3,049 tests**, and three entries cost **31.4s / 44.6s / 70.0s** — **230s total**,
32% of the 720s ceiling. Two conclusions the follow-up's defaults should be set from rather than
guessed at. The **count cap is the binding constraint, not the clock**: at this repo's size a cap
of 3 fits comfortably inside the budget where 8 would not. And the **fixed cost dominates** — the
baseline is 35% of the total, and every run recompiles into a fresh `PYTHONPYCACHEPREFIX` (the
stale-`.pyc` defence the mutation harness needs, whose price is paid here), so the marginal entry
is much cheaper than the first. A repo whose suite is slower than this one should lower the cap
before it touches the ceiling.

The stage is change 1 of the accepted `specs/proposals/review-probing.md` sequence, and it is
deliberately the narrow one: it grants no general execute, because the thing invoked is a single
tool with a fixed contract. Whether the general probe callback (#364) is worth its larger cost
is decided on what this one measures — `probe_proposed` against `probe_dropped` answers the
question the proposal names as able to invalidate it, namely whether the reviewer's proposals
are mostly real or mostly no-ops and duplicates of the builder's own table.

#### Scenario: the spend breakers bound the fix loop

The `review` verb is the loop boundary, so it enforces two **ledger-backed spend breakers** there (`harness/loop_budget.py`; thresholds read from `CONTEXT.md` → `loop:`, defaults `max_review_cycles: 5` / `unconditional_review_cycles: 3` / `wall_clock_budget_minutes: 110`). The harness cannot see the orchestrating session's token meter, but it can observe the ledger — so it bounds the *behaviours* that burn tokens:

- GIVEN a run that has already spent its `max_review_cycles` (**5**) `review` events
- WHEN the agent runs `harness review` again
- THEN the verb refuses **before invoking any engine**, records **no** `review` event, and exits `4` with `{ "error": ..., "reason": "review_cycle_ceiling" }` — the run stops and the ticket goes on operator hold. `max_review_cycles` counts the cycles a run may **spend**, not the ordinal of the call that trips (#329): a budget of 5 runs cycles 1–5 and refuses the 6th call.
- AND GIVEN a run whose **last allowed** cycle returns `fail`, THEN that review's event and printed verdict both carry `cycles_exhausted: true` — the stop lands at the *completion* of the last cycle rather than one wasted implement pass later, when the refused call would finally report it. Its sibling `convergence_check_required` covers the cycles before that: a `fail` from the last unconditional cycle onward flags that the agent owes a recorded convergence judgment before spending the next one. The two partition the fails and are never both set. **Neither gates** — the exit-4 refusal is the enforcement, these are what let a well-behaved orchestrator stop before reaching it.
- AND likewise, GIVEN an **unattended** run whose `started_at` is older than the configured wall-clock budget (110 minutes), WHEN the agent runs `harness review`, THEN the verb refuses the same way with `reason=wall_clock_budget`. That budget is not merely *aligned* with the stale-run reclamation staleness threshold — since #260 it **is** that threshold: `loop.wall_clock_budget_minutes` is the single value both consumers read, so the breaker (prospective) and `reclaim --stale` (retrospective) cannot drift apart. They are one quantity seen from two directions, and a divergence would strand a run in the gap — spared reclamation, yet refused at review. That invariant now holds *per mode* (#296/#297) and is unweakened by the split: the unattended mode still reads one value twice, and the attended mode has no review-side clock at all, so the gap has no way to open there.
- AND GIVEN an **attended** run (one `start --attended` declared, [ADR 0011](../decisions/0011-attended-run-spend-scope.md), #296) at that same elapsed value, WHEN the agent runs `harness review`, THEN the wall clock does **not** trip and the engine runs. The clock stands in for autonomous spend, and an attended run's elapsed time also counts however long the operator took to answer, during which the run spent nothing — measuring it would refuse finished work for time that cost nothing. Only that one check is scoped: the **cycle ceiling stays unconditional in both modes**, because it bounds the fix loop itself, which an operator's presence does not make cheaper. The exemption must be declared at `start` and is never acquired by omission — `evaluate_breakers` defaults to unattended, and only the literal JSON `true` on the run row reads back as attended, so a corrupt or hand-edited ledger can only ever make a run *more* bounded. `reclaim --stale` selects its own threshold by the same declared mode (#297): an attended run is measured against `loop.attended_idle_minutes` (480) instead, so the run that finishes at `review` is not reverted out from under the operator by the sweep an hour later. A longer threshold, not an exemption — an attended session abandoned overnight is still reclaimed.

This is the enforcement of the one canonical stop policy, which `skills/review-discipline/SKILL.md` owns and `agents/reviewer.md` / `commands/harness.md` / `commands/build.md` / `commands/review.md` point at rather than restate (#329). The breakers are checked at the verb boundary, not mid-session: a run that runs away *between* verbs is bounded by the wall-clock check at the next boundary, not interrupted mid-thought — the honest limit of ledger-backed breakers, and the reason true token/$ metering is deferred.

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
- AND GIVEN instead the run branch conflicts with what landed on `origin/<base>`, the verb tears the throwaway worktree down wholesale and exits 1 with a clear message (not a raw git conflict dump) **carrying `reason: merge_conflict`**, leaving the run open and resumable — merge `origin/<base>` into the run branch, commit the resolution, re-review, and close again

#### Scenario: the merge or push fails

- GIVEN an open run whose gate is satisfied
- WHEN `close`'s step-6 merge/push fails in a way `harness.close_merge` classifies
- THEN the verb exits **1** carrying that module's own `reason` — `merge_conflict` (needs work on the run branch), `push_rejected` (a concurrent close won the race; a plain retry), `git_status_failed`, `fetch_failed`, `network_timeout`, `merge_failed`, or `worktree_create_failed` — and **no** `merged` key, because the merge did not land; the run row stays `open`, the ticket is not transitioned, and the ledger's `close` event records the same reason instead of collapsing into the unexpected-error tag (#300)
- AND the reason is **propagated, not translated**: `close_merge` owns the strings and `close` passes them through, so a reason added there arrives tagged rather than as an untagged error — pinned by a totality test that derives the expected set from the module source by AST rather than hand-listing it
- AND GIVEN instead the failure is one `close_merge` did **not** classify (an OS or thread error), the verb keeps the historical untagged `{"error": ...}` shape — there is no reason to invent
- AND the merge vocabulary is **disjoint** from the ticket-transition vocabulary below, which is what lets a caller read "did the merge land?" off the tag alone rather than by parsing the human message

#### Scenario: a transient failure is absorbed before the caller ever sees it

- GIVEN an open run whose gate is satisfied, and a step-6 or step-7 failure whose classification is transient — `network_timeout`, `fetch_failed` or `push_rejected` from the merge; a transition that raised a request error (401, 5xx) or reported success without a confirming post-write state
- WHEN the agent runs `harness close`
- THEN the verb re-attempts that step itself, up to **3 attempts total** (initial + 2 retries) with 2s then 8s of backoff, and reports success if any attempt lands — so the orchestrating agent's decision tree is `exit 0 → done; non-zero → escalate`, with no refusal-table lookup and no compensating action (#301)
- AND the retry is **step-local**: a step-7 retry re-issues only the transition, never re-entering the merge, and the terminal `close` event is still recorded exactly once (#263)
- AND a deterministic failure is attempted **exactly once** — `merge_conflict`, `merge_failed`, `git_status_failed`, `worktree_create_failed`, a ticket the tracker reports as not found, and every exit-2 gate refusal (which is upstream of the retry and so cannot reach it)
- AND on exhausting the attempts the verb exits with the **same** code and `reason` it would have without the retry: the last exception is re-raised untouched into the existing handlers, so retry changes latency and the ledger, never the contract
- AND what was absorbed is recorded on the `close` event as `retries` (a count, always present) and `retried_reasons` (the ordered labels, omitted when empty), so a degrading tracker is observable rather than silently ridden out — the labels distinguish `ticket_transition_request_error` from `ticket_transition_unconfirmed`, a discrimination the exit-1 wire vocabulary deliberately does not make
- AND the caps are module constants in `harness/cli/close_retry.py`, not `CONTEXT.md` config: the `loop:` knobs bound *spend policy*, which is a per-repo choice, whereas a transient-blip retry is mechanics
- AND the retry sits **above the tracker seam** — it keys on `TicketNotDone.kind`, the backend-neutral three-way discrimination (`unconfirmed` / `not_found` / `request_error`) every backend's failures map onto, so neither tracker can acquire retry behaviour the other lacks

#### Scenario: a gate refusal

- GIVEN an open run that does not satisfy the gate
- WHEN the agent runs `harness close`
- THEN the verb exits 2 with exactly one structured `reason`: `no_run` (no `start` row), `dirty_worktree` (uncommitted edits — never reviewed), `no_passing_review` (no `verdict=pass` on record), `stale_review` (a pass exists but HEAD moved after it), or `no_gate_evidence` (a pass covers HEAD but cannot show the repo's verify gate ran)

#### Scenario: the ticket-Done transition cannot be confirmed

- GIVEN the merge has already landed, and the tracker's transition mutation either raises or reports success without a post-write state matching the one requested (#233)
- WHEN the agent runs `harness close`
- THEN the verb exits **1** — not a gate refusal, because the merge already landed — with `merged: true` and one of two `reason`s: `ticket_transition_failed` (the tracker raised) or `ticket_transition_unconfirmed` (the mutation reported success, but its own response shows the state never took); the run row stays `open` and no *landed* `close` event is written. Both reasons are reported only **after** the verb re-issued the transition up to its retry bound (#301) — a not-found ticket excepted, being deterministic — so a transition failure that reaches the caller has already outlasted the retry and is an escalation, not a re-run

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

Both backends' boundary exceptions subclass the tracker-agnostic bases in `harness/tracker_errors.py` (`TrackerConfigError` / `TrackerNotFound` / `TrackerRequestError`), so the verbs catch failures **without naming a backend** — `except TrackerNotFound` catches a Linear-or-GitHub not-found alike. Because backend selection lives in that one factory, a second backend slots in **without touching a verb**: `start`, `close`, `reclaim`, `review`'s post-verdict transition, and the held-ticket seam `harness/cli/held_ticket.py` that `defer`/`release` share (#338) all depend only on the `Tracker` protocol and the agnostic errors. `test_tracker_seam.py` pins the contract — both clients satisfy the protocol structurally (`@runtime_checkable`), the factory returns a Linear client for `linear`, a GitHub client for a configured `github`, `None` for `none`, and `GitHubConfigError` for a github repo with no config block.

Since #339 the seam is also a **source-tree invariant**, not only a convention a review has to remember: no module under `harness/cli/` may name `harness.linear` or `harness.github` at all — no import of the module, no import of a name from it, no attribute chain into it — while `harness.tracker`, `harness.tracker_errors` and `harness.tracker_queue` are unrestricted. `test_cli_module_boundaries.py` enforces it over the **tracked** `harness/cli/*.py` set (`tracked_py_sources`, so an abandoned worktree cannot read as living source, #215), reading the AST rather than the text because four CLI modules name a backend client in prose legitimately. The denylist is itself pinned to the factory: `test_backend_modules_match_the_seam_factory` derives the backend vocabulary from the `*Client` imports in `harness/tracker.py`, so a third backend wired into `tracker_client` fails the guard rather than slipping past a stale literal. What this defends is credential and write authority — a verb that constructs its own client acquires a second, ungated path to `LINEAR_API_KEY` / `GITHUB_TOKEN`, which is precisely what made `promote escalate` demand the Linear key in a repo configured `tracker: github` before #328; that specific regression keeps its named pin (`test_promote_reaches_the_tracker_through_the_seam`). The rule reads static source only: dynamic access (`importlib.import_module`, `getattr`) is a stated non-goal — the guard is against drift and accident, not an adversarial sandbox. An escape exists but leaves a record: `_BACKEND_EXEMPT` maps a path to a documented, issue-citing rationale for a module whose *purpose* is one backend, and it is empty today.

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

**A missing ledger is a distinct refusal from "no open run" (#244).** `checkpoint`, `review`, `close`, `design` all resolve their open run through the one shared `resolve_open_run` (`harness/cli/_runs.py`). Before, a `db_path` that did not exist on disk resolved to the same `None` as a ledger that was read but held no matching `status='open'` row, so every caller rendered both as `no open run found for worktree ...` — hiding the common real cause (the verb was invoked from outside the repo that owns the run) behind a message that reads like a dead or absent run. `resolve_open_run` now raises `LedgerNotFoundError` (a `VerbError` subclass, `reason="no_ledger"`, naming the resolved `ledger_path` in `extra`) in place of the old `return None`; the historical `no open run found` message and its per-verb `reason` (`close`'s `no_run`) are unchanged for the case where the ledger genuinely holds no open row. Because every caller goes through `run_verb`'s shared `VerbError` handling, the fix reaches all four verbs from the one resolver — no per-caller edit.

## Known limitations

- The orchestration *between* verbs is deliberately not reproducible: it varies with the agent, which buys full context retention and graceful degradation to manual driving on a verb failure (decision D1). Reproducibility applies to the verbs, not the end-to-end run.
- A run can be abandoned without merging via `harness cancel` (close-without-merge); see [cli-surface.md](cli-surface.md).
- A run whose orchestrator died mid-flight is recovered via `harness reclaim` — it reverts the stranded Linear ticket to Todo (so dependents unblock) and reuses `cancel`'s ledger transaction to clear the `open` row, while preserving the worktree/branch. See [run-ledger.md](run-ledger.md) and the accepted proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md). Tracker-less (`tracker: none`) only the local half runs, and the time-keyed `--stale` sweep has no tracker state to read — so recovering a dead run there is a manual `reclaim <run-id>`, not an automatic sweep.

### What #321 deliberately did not do

Three departures from that change's own design, recorded here rather than argued in a commit body:

- **`skills/spec-authoring/SKILL.md`'s tiering paragraph was not deleted whole**, as the design specified. That paragraph was also the only place in the skill naming `harness design` as the owner of the design stage, which `test_spec_authoring_notes_the_design_stage` requires (#213 AC-3) — deleting it whole made that guard fail. What replaced it carries the design-stage half and drops the tier instruction, which is what the design was actually after.
- **Two guards belonging to other tickets were edited**, which the design did not anticipate. `test_spec_authoring_notes_the_design_stage` asserted the skill still carried the `build` / `review` tier semantics "which this change does not touch" — #321 does touch them, so an assertion pinning them now pins a false claim and was removed with its reasoning left in place. `test_spec_authoring_as_built_sets.py` pinned the skill's version to the literal `0.10.1`; that literal fails on any correct later bump and its only fix is to retype the new number, so it was reduced to the durable half (the stamp agrees with the registry entry).
- **The `build:opus` / `review:opus` GitHub labels are deleted as an ops step after the merge, not by this change.** Nothing reads them once the code lands, so they are inert either way; deleting them *before* the merge would silently move #314 and #318 off the tier they still resolve. No test can assert a label's absence from a remote tracker, so the code path is what is guarded (AC-1).

## Decisions

The cross-cutting decisions that shaped the verb model — D1 (orchestration inversion), D2 (the reviewed-SHA gate), D5 (routing discipline) — are recorded once in [`specs/architecture-principles.md`](../architecture-principles.md) and referenced from here, not duplicated.

## Cross-references

- [run-ledger.md](run-ledger.md) — the SQLite ledger the verbs read and write
- [worktree-lifecycle.md](worktree-lifecycle.md) — the isolated worktree `start` creates and `close` merges
- [cli-surface.md](cli-surface.md) — the full command surface, flags, exit codes, JSON
- [`specs/architecture-principles.md`](../architecture-principles.md) — the orchestration-inversion decision record
- [`specs/proposals/harness-as-tool.md`](../proposals/harness-as-tool.md) — the accepted model
