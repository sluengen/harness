---
feature: verb-model
status: implemented
last_updated: 2026-08-15
tickets: [CAL-570, CAL-574, CAL-586, CAL-661, CAL-925, CAL-1082, CAL-1104, CAL-1197, "#244", "#295", "#296", "#297", "#298", "#299", "#329", "#300", "#301", "#315", "#318", "#321", "#339", "#338", "#359", "#363", "#352", "#370", "#353"]
---

# Verb model — start / design / review / close

> The four audited verbs an orchestrating agent calls to drive a ticket from open to merged, with the design stage recorded and review enforced as a gate before anything lands.

## Behaviour

The harness is **not** a pipeline that drives agents. One orchestrating agent session implements a ticket and shells out to four one-shot, ledger-backed verbs — `start`, `design`, `review`, `close` — over the [run ledger](run-ledger.md). The agent owns *what gets built and how*; the verbs own *the durable record and the gate* (decision D1, [`specs/architecture-principles.md`](../architecture-principles.md)). The lifecycle of one run is `start → design → implement → review → (fix → review)* → close` (ADR [`0007`](../decisions/0007-design-verb.md) inserted `design`; assurance now decides whether the stage is required, and `review` refuses a complex run without a usable design).

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

**`trivial` is honoured where the repo can certify one** (#353; *superseded 2026-08-15: until #353 this read "recognized and rewritten — no run can snapshot it"*). `resolve_assurance` now returns the level as stated. Whether the *repo* can act on it is a second, still-pure question — `apply_fast_path_availability(resolution, fast_path_available=...)`, which `start` feeds with `load_trivial_allowlist(repo_root).valid`. A repo declaring no usable `assurance.trivial_paths` allowlist can never certify anything, so opening a `trivial` run there would charge every run an extra verb call and two tracker writes forever for an outcome already known at `start`; such a run opens at `simple` with `fast_path_unavailable`, and the existing stderr warning fires and now says something actionable. The `llm_review` column above therefore has its consumer: [`certify`](#certify--the-deterministic-trivial-fast-path) guards on `required_stages(assurance).llm_review` rather than comparing the level to a string.

**It is a snapshot in one direction — monotone, not immutable** (#352, amended by #353). `start` writes the pair; `certify` is the only other writer and can only tighten `trivial` → `simple` (`assurance_reason='diff_ineligible'`), through an `UPDATE … WHERE assurance = 'trivial'` whose WHERE clause makes the direction a property of the statement rather than a convention. Nothing else mutates it, so `design` and `review` still read the run row rather than re-reading labels: a label edited mid-run cannot remove a requirement the run was opened under, and the level can only ever have grown stricter. A repeat `start` reports the *recorded* pair for the same reason `attended` does.

The Linear transition is the only non-local side effect, and it runs **last**: if the worktree creation or the ledger insert fails, nothing has touched Linear. The rollback ordering is locked by `test_cli_start.py::test_worktree_failure_leaves_no_db_row_and_no_transition` and `::test_db_failure_removes_worktree_and_no_transition`. The open run is recorded as the `runs` row, not as an event.

#### Scenario: a ticket that already has an open run

- GIVEN a ticket that already has an `open` run
- WHEN the agent runs `harness start <ticket>` again
- THEN `start` resolves the existing open run (keyed on the canonical Linear identifier) and **returns it successfully** (exit 0) — it does not create a second worktree or row, and does not error (`harness/cli/start.py`, step 4: `if existing is not None: return existing`)

The partial unique index `idx_runs_ticket_open` is the database-level backstop for the concurrent-race path: if two `start` calls both pass the existence check, the index refuses the second insert and that loser cleans up its worktree and surfaces the run that beat it (at most one `open` run per ticket).

### `design` — produce the run's technical design

`harness design --run-id <id> [--engine claude|codex] [--model <alias>]` runs a dedicated design engine over the worktree and ticket in a fresh context — uncontaminated by the orchestrator's own state — and produces the change spec's Design section (data model, interface/contract, scenarios, security, test strategy). Claude is the default and resolves an omitted model to Opus; Codex uses its configured default when `--model` is omitted. ADR [`0007`](../decisions/0007-design-verb.md) added the stage so the session executes against an explicit design instead of designing by rejection across `(fix → review)*` cycles.

The verb records the design in three places: the ticket, as a marked comment; the ledger, as a `design` event carrying the design's content hash and the `grounded_sha` it studied; and stdout, as `DesignOutput`.

**The primary output channel is a verb-owned file outside the worktree** (#294, #318). For Claude, the model receives a scoped write grant to that file and no other path. For Codex, the model remains under `--sandbox read-only`; the CLI, not the model, writes its final response to the same file through `--output-last-message`. The temporary directory is removed on every path, so the stage cannot leave an untracked file behind and trip `close`'s `dirty_worktree` gate. The `design` event records `channel` (`file`, `stdout`, or `last_message`) and `design_chars`.

This replaced the `SUBMIT: <json>` line design had inherited from `review`. That contract fits `review` — a fixed shape under 100 characters — and does not fit a 14–17 KB Markdown document, which it forced onto one physical line with every newline escaped and no structural landmark anywhere in it. Measured on this repo's ledger before the change, `design` lost **12.5% of attempts** to the wire format against `review`'s **0.24%**; one run lost 12m44s of Opus and a complete design because a single closing brace never arrived. `review`'s contract is deliberately untouched.

Claude retains a **stdout fallback** — the design between two nonce-marked lines — as both recovery and a detector for a scoped-write permission regression. With it, that degradation records `channel="stdout"` and warns on stderr. Codex deliberately has no stdout fallback: only the CLI-owned `--output-last-message` file is accepted, recorded as `channel="last_message"`, so Claude's marked-output protocol cannot be mistaken for a Codex result.

**The stage is conditional on the run's assurance** (#352). ADR 0007 D1 ran it for every ticket whatever its judged difficulty; it now runs only where the run snapshotted a level that requires a design, which today means `complex` alone. (ADR 0005's per-ticket model-tier labels are a separate, retired mechanism — #321 — and never gated this stage.) The check reads the run row, before the adopt path and before any engine:

- GIVEN an open run whose assurance does not require a design (`simple`, or a row written before the migration)
- WHEN the agent runs `harness design --run-id <id>`
- THEN the verb invokes **no engine**, reads **no ticket**, records **no `design` event** and posts **no comment**, and exits `0` with `status="not_required"` and an empty `design_markdown`

`status` is where the skip is reported, so the orchestrator branches on a value rather than on a missing field; an empty `design_markdown` says plainly there is nothing to stage for `review`'s `--design-file`. Claude output retains the historical six-key shape, with `model` an **empty string** rather than the resolved default — `--model` is accepted and ignored here, so naming one would assert an engine choice nothing acted on. Codex output omits `model` entirely, the same absent provenance it records wherever it uses its configured default; emitting the empty string on this path instead was exactly the invented provenance the run-ledger spec says the nullable field stops producing. `not_required` is deliberately **not** a third `design` *event* status: `resolve_design_gate`, the adopt path's authentication, and the ledger statistics all key on `status != "ok"`, so a new event status would silently reclassify events for three readers. Nothing is written to the ledger on this path at all — a skipped stage must not manufacture the artifact a `complex` review would later demand. Engine and model selection stay orthogonal to assurance.

- GIVEN an open run
- WHEN the agent runs `harness design --run-id <id>`
- THEN the verb records a `design` event with `status="ok"`, `design_hash`, and the `grounded_sha` it studied, posts the design as a marked ticket comment, and emits `DesignOutput` on stdout
- THEN the `design` event also carries `channel` (which engine-specific channel delivered) and `design_chars` (the design's length) — the second being the measuring instrument for the length target the prompt states
- AND GIVEN instead the engine is killed, cannot be spawned, delivers a design on **neither** channel (`reason="no_design_output"`, which replaced `no_submit` / `malformed_submit` here — a file is written or it is not, so the distinction the JSON format created no longer exists), or the ticket spec cannot be read, THEN the verb records a `design` event with `status="failed"` and a stable `reason`, posts **no** comment, and exits `3` (decision **D4**: every failure mode degrades and records)
- AND GIVEN `--engine codex` and a final message carrying none of the requested Design sections, THEN the verb refuses it as a design (`reason="design_not_recognized"`) rather than recording it as one. The floor exists because the two engines deliver over channels with different evidentiary value: Claude's file exists only because the model used the one scoped write grant it was given, whereas the Codex CLI writes `--output-last-message` on **every** completed turn — so without a floor a refusal or a clarifying question is hashed, posted to the ticket as the Design section, and recorded `status="ok"`. One recognized section heading is the bar, not all five: a real design may legitimately omit a section, so requiring the set would reject good designs to catch prose that carries none. The check does not apply to the Claude channel, where the deliberate write is its own evidence
- AND GIVEN `--engine codex` and an exhausted Codex tier, THEN the failure is recorded as `reason="codex_usage_limit"` — the same name `review` gives the same wall, single-sourced beside the detector that recognizes it. It still degrades and records at exit `3`; what changes is that an infrastructure wall no longer arrives on the ledger as `no_design_output`, which reads as "the engine ran and designed nothing" and sends the operator to the ticket instead of the billing page
- AND GIVEN a `failed` design event on a run that does **not** require a design, WHEN the agent runs `harness review`, THEN review is **not** refused — ADR 0007 D4's degradation, now scoped to those levels, so an infra flake costs such a run its design but never its ability to ship. On a `complex` run the same event **is** refused (see `review` below)

**A failed design is not a stop.** The orchestrator proceeds to implement without one rather than re-running the verb in a loop chasing a green result; a re-run is legitimate (the latest event is authoritative and nothing is mutated), but the run is not blocked either way. How `review` consumes the design — enforcement on the ledger, context via `--design-file` — is the "design stage is required" scenario under [`review`](#review--record-a-verdict-bound-to-the-reviewed-sha) below.

### `review` — record a verdict bound to the reviewed SHA

`harness review [--run-id <id>] [--engine claude|codex] [--fallback/--no-fallback]` runs the selected review engine (`--engine`, **default `claude`**; CAL-701) against the worktree's current HEAD and records a verdict **bound to the exact SHA reviewed** — the load-bearing detail behind decision D2: the `close` gate refuses a pass whose SHA ≠ HEAD, so a stale pass cannot be reused. Each engine is a **read-only CLI subprocess** (`claude -p --permission-mode plan` or `codex exec --sandbox read-only`) emitting the same `SUBMIT:` contract — never the Agent SDK (see the "Review engine" principle in `architecture-principles.md`).

**The in-container review engine is Claude; the native Codex engine is host-only until ADR 0013's targeted profile ships in #314.** Codex's sandbox cannot start in the unmodified unprivileged wrapper, so ordinary `~/bin/harness` and `/harness run` keep their Docker/Claude path. `/harness run <ticket> --codex-only` (#318) is an explicit native-only mode: required design uses `--engine codex`, every review uses `--engine codex --no-fallback`, and `doctor --engine codex` validates Codex without requiring Claude. It does not claim Docker support; [ADR 0013](../decisions/0013-codex-engines-in-container.md)'s targeted seccomp work remains #314's separate path toward `/harness run --codex` in-container, amending [ADR 0002](../decisions/0002-in-container-review-engine.md)'s original rationale without changing today's host-only status.

The review fallback remains enabled by default for compatibility: an explicit Codex review that exhausts its authenticated tier falls back once to Claude and records `fallback_from="codex"`. `--no-fallback` turns that condition into exit 3 with `reason="codex_usage_limit"`, records no verdict, and never invokes Claude. Non-usage-limit Codex failures never fall back in either mode.

**The claude engine's model is one configured value, the same for every ticket** (#321). It is `CONTEXT.md`'s `loop.review_model` (default `opus`, `harness/loop_budget.py`), read off the `LoopBudget` the verb has already loaded for its spend breakers — so resolving it costs no file read and no network call. The alias is appended to the claude command as `--model <alias>` (`_build_cmd`); the codex command is unaffected, since codex ignores `--model`. An explicit `harness review --model <alias>` overrides the configured value outright, for host/testing use.

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

#### Scenario: the review is given rendered captures of the surface

`harness review --screenshot-dir <path>` (#361) is the **third member of the evidence family** `--design-file` and `--gate-exit`/`--gate-log` already belong to: the orchestrator produces evidence the verb cannot produce itself, hands it over, and the verb records whether it reached the engine. For a change to a user-facing surface, `review` is asked whether the result looks right and structurally cannot look — the engine runs with no browser, no display and no network. The builder can look, and until now that evidence was discarded at handoff.

Captures are named to the engine by **absolute path, never inlined** — text can be inlined and an image cannot, so the engine's own file access is what opens them. The decision — which captures a directory yields, and which invocations it refuses — lives in `harness/cli/review_visual.py` on the `review_inherit` / `review_probe` / `review_pollution` precedent; the verb keeps one call site and the recording.

- GIVEN a capture directory inside the workspace and `--engine claude`
- WHEN the agent runs `harness review --screenshot-dir <path>`
- THEN the prompt names each capture by absolute path, and the `review` event records `visual_context=true`, `visual_count=<N>`, `visual_manifest=<bool>` and **no** `visual_context_reason`
- AND GIVEN `--engine codex` with any captures, THEN it refuses **before any engine is spawned and before every short-circuit**, exit `5`, `reason=screenshots_unsupported_engine`
- AND GIVEN a directory — or any capture, or the manifest — resolving outside the workspace allowlist, THEN it refuses the same way with `reason=screenshot_dir_outside_workspace`
- AND GIVEN more than 12 captures, THEN it refuses with `reason=too_many_screenshots`
- AND GIVEN a missing directory, a path that is a file, or a directory with no captures, THEN the review **proceeds**, warns on stderr, and records `visual_context=false` with `visual_context_reason` of `unreadable` / `unreadable` / `no_images`
- AND GIVEN no `--screenshot-dir` at all, THEN behaviour is unchanged, the prompt is **byte-identical** to the pre-#361 one, and the event records `visual_context=false, visual_context_reason="not_supplied"` with `visual_count` and `visual_manifest` **absent** — a value there would assert something about a channel that was not used

**The posture, in one sentence:** *a refusal is for what the caller must fix in the invocation — an unreachable path, an oversized set, an engine that cannot see; everything about the content of a reachable, in-budget directory degrades and records.* That is the design gate's "enforcement refuses; context degrades" with the refusal half widened by exactly two cases.

**Why codex refuses rather than degrades.** Codex cannot see images — in the #361 spike it reached the right answer only by shelling out to `magick`, and `harness:dev` carries no `magick`, `convert`, `identify`, `tesseract` or PIL. Accepting the combination would record a pass that reads as though the reviewer looked at the rendering, which is the one failure this channel must not manufacture. The same argument makes the cap **refuse rather than truncate**: handing the reviewer a subset while the ledger records that the captures were supplied is the identical manufactured confidence, and the remedy ("narrow the set") is actionable. Twelve is #362's reference set — roughly four widths across up to three pages.

**The manifest is optional, by decision.** Requiring it inverts the incentive: supplying nothing proceeds, but supplying captures without a manifest would refuse — the caller who did more work is refused and the one who did none is not, making the cheapest compliance to drop the flag and lose the captures too. A required manifest *reduces* the evidence reaching the reviewer. Its absence warns and records `visual_manifest=false`, so the requirement can be decided later on adoption data.

**The invocation check precedes the inherit short-circuit**, deviating from `--design-file`'s position at the design gate. The codex refusal is decided from argv alone — no ledger read, no filesystem — and a refusal an unrelated short-circuit can skip is one whose test is defeated by putting the caller into an inherit-eligible state, which a resumed WIP branch reaches in normal operation. Placing it first makes "no path reaches a spawn, or a recorded pass, with the combination accepted" structural rather than a claim about the other steps. This is safe for the reason already recorded about the design refusal: its *position* is not the property it protects — containment is, and containment holds identically here, and earlier.

**The workspace allowlist is the only boundary, applied to the directory, to every capture, and to the manifest.** `Path.resolve()` follows links before the descendant comparison, so a capture symlinked out of the mount refuses while one resolving inside is accepted — the boundary is the mount, not the link. The manifest is named separately because it is the asymmetric case: a capture is bounded but its content is **never read**, whereas the manifest is the one entry whose bytes are read and placed in the prompt, and the suffix filter passes over `.md` before the per-entry loop sees it. Left to the directory's own check it would be the single member of an untrusted directory able to carry an arbitrary host file into the review. Both boundary refusals are ordered **before** the cap, because reported as a budget refusal an escape's remedy reads "narrow the set", which a caller can satisfy by deleting innocent captures and leaving the link.

##### The limits, stated plainly

- **`visual_context=true` records that the prompt NAMED N readable, in-workspace captures. It does not attest that the engine opened them.** Nothing in the production path parses the engine's tool use, so the field records what the verb did, not what the model did — the same real semantics `design_context` has. Making it attest consumption would require `--output-format stream-json` on the production command, which changes the `SUBMIT`-line contract `scan_submit_line` depends on for both engines and both verbs; that is filed as a follow-up, not done here.
- **Nothing authenticates that a capture depicts the reviewed SHA.** The manifest may name one, but the verb parses no manifest and a builder who captures the wrong thing produces evidence that looks correct. The prompt block says so to the engine, which *can* make the comparison — judgment placed where judgment lives. This change raises the floor; it does not close that hole.
- **The channel is reliable for layout and structure, not for reading body text at full-page downscale.** Measured against a real 1440 × 5726 px capture (#361, AC-5): the `Read` came back as an **image content block** at those dimensions, so the mechanism holds. But a token rendered at 16px body size came back as 7 of 8 characters in one run (`l` read as `1`), and exactly in a second run only after the model cropped the image itself. Character-level fidelity is at the edge, and a reviewer may need to crop to read fine detail. The failure class this channel exists to catch — a page rendering as one column at every width — is well within it. The narrowing (viewport-height slices per width, plus a documented maximum capture height) belongs to **#362**, which owns the capture convention.
- **A silent CLI regression is not detectable in the gate.** That today's `claude` CLI still returns image content blocks is a property of an external binary; if it stopped, the reviewer would degrade to reading paths and the gate would stay green. `visual_context` makes that detectable after the fact, and the opt-in live test (`HARNESS_LIVE_REVIEW_ENGINE=1`) makes it detectable on demand.
- **Prompt injection is unchanged in kind and widened in medium.** Captures and the manifest are untrusted content fed to the engine, as the diff and the ticket already are, and an instruction rendered into a PNG is harder to notice than one in text. The mitigation is **not** a sandbox: `--permission-mode plan` is read-only by the engine's own policy, which includes an unrestricted Bash tool (measured in `harness:dev` — plan mode ran arbitrary `python3 -c`, installed a package, and wrote under `~/.claude/plans/`; it declined, but was not prevented from attempting, a write into the mounted workspace). The containment that does not depend on the model's cooperation is the container and the workspace allowlist.

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

### `certify` — the deterministic trivial fast path

`harness certify [--run-id <id>] [--gate-exit <code>] [--gate-log <p>]` is what makes `assurance:trivial` safe to honour (#353, item 2 of proposal [`assurance-led-lifecycle`](../proposals/assurance-led-lifecycle.md)). A `trivial` run calls it **instead of** `review`. It runs no engine, and it has exactly two answers, both exit 0:

- **`certified`** — every path changed by `base_sha...HEAD` is allowlisted and unrestricted, the repo's verify gate is green at this HEAD, and the worktree is clean. A `certify` event is appended, bound to that SHA, and `close` accepts it. No `review` event is written: a synthetic pass would enter `harness stats`' verdict-by-engine aggregate as a judgement nobody made.
- **`assurance_upgraded`** — anything else about the *diff*. The run row moves to `simple` (`assurance_reason='diff_ineligible'`), the issue's `assurance:trivial` label is replaced with `assurance:simple`, a comment records the machine-readable reason and the offending paths, and the orchestrator proceeds to `review`. Exit 0, because a correct upgrade is the safety mechanism working and an unattended loop must not read it as an error.

A red or missing gate is **neither**: it is a refusal (exit 5, `gate_failed` / `no_gate_evidence` — the same two tags `review` emits), and it mutates nothing. "Come back when the gate is green" is the answer to a red tree; upgrading there would let a red tree quietly buy a review the run had not earned the right to ask for. Three more refusals exit 2 and also mutate nothing: `no_run`, `assurance_not_trivial` (decided through `required_stages(assurance).llm_review`, not a string compare), and `dirty_worktree` (`close`'s own predicate, called rather than copied — certifying a tree whose working copy differs from HEAD would attest to content nobody classified).

**What decides eligibility.** The allowlist is repo configuration (`CONTEXT.md` → `assurance.trivial_paths`), read from the **run's own worktree**; the veto is code ([`harness/trivial_diff.py`](../../harness/trivial_diff.py) → `RESTRICTED_PATTERNS`), covering the eight surfaces the ticket names — source, security, persistence, configuration, command/guidance, feature-spec, decision, and other public contract. Narrowing is always available to a repo; widening past the veto is not, because a repo-configurable restricted list would put the safety property under the control of the input it protects against. **The restricted scan runs first**, so no allowlist pattern — however broad — can launder a restricted path, and `CONTEXT.md` is itself restricted, so a run that edits its own allowlist is ineligible on that ground alone. Patterns take exactly three forms (`<prefix>/**`, `*.<ext>`, an exact path) matched by a hand-written matcher rather than `fnmatch` or `PurePath.match`, both of which would decide a widening case nobody reasoned about; no spelling of *everything* is expressible, and **one** malformed pattern invalidates the whole list rather than being dropped, since silently discarding one changes which paths are eligible with nothing failing.

**The classification boundary is the whole run, not the newest commit.** `base_sha` is the run's merge target at `start` (see [run ledger](run-ledger.md)), and the range is `base_sha...HEAD` computed with `--no-renames` and `-z`. Three-dot is what stops a run widening its allowlist in commit 1 and certifying in commit 2 — the widening commit is still inside the range — and it is why a base branch that advances mid-run cannot change the answer. `--no-renames` is a gate mechanism, not a formatting preference: `--name-only` prints a *detected* rename as its destination alone, so moving `harness/thing.py` to an allowlisted `docs/thing.md` would otherwise be reported as one allowlisted path and a change that deletes a source file would classify as trivial.

**Everything unresolved is ineligible**, and there is exactly one direction to fail in. Absent or invalid allowlist (`no_allowlist`), a repo that configures no `verify:` at all (`gate_not_configured` — the one place `certify` is deliberately stricter than the shared `has_gate_evidence`, whose acceptance of an unconfigured gate is right for a review, where an engine still read the diff, and wrong for a certification, whose entire safety argument *is* the gate), a run with no recorded boundary (`no_base_sha`), an unreadable diff (`diff_unreadable`), an empty diff (`empty_diff`), a restricted path (`restricted_path`), an unlisted one (`unlisted_path`). So a bug here costs a fast path, never a gate.

**Ordering is the contract.** Every check that can refuse runs before any mutation, and on the upgrade path the stricter run row is committed **before** `tracker_client` is even resolved. A tracker outage therefore cannot leave a run whose row says `trivial` while its issue says `simple`: the row is authoritative, the sync is best-effort, and a partial sync is reported by naming the artifact (`tracker_error: "label" | "comment"`) rather than by rolling anything back. Only the assurance label is touched, and that holds *by construction* — both tracker calls are single-label operations, so no code path enumerates the issue's labels and writes a set back.

#### Scenario: an eligible trivial run certifies without an engine

- GIVEN an open `trivial` run whose whole `base_sha...HEAD` diff is allowlisted and unrestricted, a clean worktree, and a green verify gate the caller reports
- WHEN the agent runs `harness certify --run-id <id> --gate-exit 0`
- THEN no design or review engine is invoked, a `certify` event is appended carrying `certified_sha`, `base_sha`, `assurance`, `classifier_version`, `eligible_paths`, `allowlist` and the same `gate_*` evidence contract `review` records, no `review` event is written, and `close` accepts that exact SHA and reports `evidence_kind: "trivial_certification"`

#### Scenario: one ineligible path upgrades the run

- GIVEN the same run, but one changed path is restricted (or matches no allowlist pattern)
- WHEN the agent runs `harness certify`
- THEN **no** `certify` event is written, the run row reads `simple` / `diff_ineligible` *before* the tracker is touched, the issue's assurance label is replaced and a comment names the reason and the offending paths, the verb exits 0 with `outcome: "assurance_upgraded"`, and the orchestrator proceeds to an ordinary `review`

#### Scenario: a certification the tree has moved past

- GIVEN a run that certified at SHA `A` and then committed, so HEAD is `B`
- WHEN the agent runs `harness close`
- THEN the gate refuses `stale_review` and names `A` among the evidenced SHAs — the binding is to the exact tree, and the answer is to certify the new HEAD

### `close` — enforce the gate, then merge

`harness close <ticket> --run-id <id>` enforces the gate, integrates the current `origin/<base>`, merges the already-committed HEAD to the base branch, pushes, transitions the ticket to Done, and finalizes the run.

The gate takes **two kinds of evidence** since #353, and it is one query for both ([`harness/cli/_review_gate.py`](../../harness/cli/_review_gate.py)): a gate-evidenced `review` pass whose `reviewed_sha` equals HEAD, or a gate-evidenced `certify` event whose `certified_sha` equals HEAD. `close.py` holds no query of its own — `_certification_refusal` is a **pure** mapping from the shared verdict onto `close`'s five (unchanged, locked) `RefusalReason` members, and `reclaim --stale`'s closable classifier calls the same predicate, because a sweep reporting *closable* for a run `close` would refuse leaves the ticket neither reclaimed nor closed. A review is preferred where both cover HEAD; the verdict's `evidence_kind` is what `CloseOutput` and the sweep report, so neither re-derives it.

#### Scenario: the gate is satisfied

- GIVEN an open run with a clean worktree and a `verdict=pass` whose `reviewed_sha` equals HEAD
- OR GIVEN an open run with a clean worktree and a `certify` event whose `certified_sha` equals HEAD (#353) — `evidence_kind` then reads `trivial_certification` instead of `review`, and `reviewed_sha` keeps its name and its meaning (the SHA the evidence binds to, which is the SHA that merges)
- WHEN the agent runs `harness close <ticket> --run-id <id>`
- THEN the verb merges the run branch into `origin/<base>` **in a throwaway worktree** (`git merge --no-ff`), pushes the merge commit to `origin/<base>`, transitions the ticket to Done **and confirms it landed against the mutation's own post-write state** (#233, `harness/linear.py`, `harness/github.py`), flips the run to `status=closed`, and emits `CloseOutput` (`run_id`, `ticket`, `reviewed_sha`, `merged`, `ticket_done`, `status`, `evidence_kind`) — the main checkout is never touched (CAL-1154)

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
- THEN the verb exits 2 with exactly one structured `reason`: `no_run` (no `start` row), `dirty_worktree` (uncommitted edits — never reviewed), `no_passing_review` (no evidence of **either** kind on record), `stale_review` (evidence exists but HEAD moved after it), or `no_gate_evidence` (evidence covers HEAD but cannot show the repo's verify gate ran). The five members are unchanged by #353 — they are a locked output contract — so the last three widen in meaning to cover a `certify` row as well as a `review` pass, and the messages (which are not contract) say which. The consequence to read deliberately: a `trivial` run that never certified is refused `no_passing_review`, an odd tag for a run that never intended a review; the message explains it and the tag stays stable

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

One execution model, **two triggers** that produce the same audited lifecycle: a human (`/harness run <ticket>`) or Hermes (the autonomous trigger slot — deferred; the launcher/trigger scaffolding was removed in CAL-712, design archived at [`hermes-orchestration.md`](../retired/hermes-orchestration.md)). The ordinary path runs each verb through the one-shot Docker wrapper and uses Claude. The explicit `/harness run <ticket> --codex-only` path runs the verbs natively in a Codex-orchestrated session, with no Claude CLI invocation; the ledger and gate contract are the same.

## Interface surface

The verbs are part of the CLI surface; their flags, exit codes, and JSON shapes are documented in [cli-surface.md](cli-surface.md), and the agent-facing contract is [`commands/harness.md`](../../commands/harness.md). The verb implementations live in `harness/cli/start.py`, `harness/cli/design.py`, `harness/cli/review.py`, `harness/cli/close.py`; the emitted CLI JSON is locked by `test_verb_contract_locked.py`.

Every verb raises one control-flow exception — `VerbError` (`harness/cli/_verb.py`) — and translates it through one epilogue, `run_verb`, so the error-JSON shape is single-sourced rather than re-declared per verb (CAL-1013). The shape: `{"error": <message>}` on stdout under `--json`, plus a machine-readable `"reason"` **only when set** (absent, never `null`). `review` and `close` set a `reason` (the gate-refusal kinds above; an infra-wall tag for `review`); the other verbs leave it unset, keeping their bare `{"error"}` shape. The `--json` *default* stays a per-verb choice (orchestrator-consumed verbs default it on; the human-facing `reclaim` / `cancel` default it off) and is deliberately not unified. `reclaim` emits a typed `ReclaimOutput` / `SweepOutput` like every sibling verb.

**An *unexpected* exception under `--json` also owes a payload (#370).** `VerbError` is the expected failure; everything else used to propagate out of `run_verb` to Typer, which rendered a traceback to **stderr** and exited 1 having written **nothing** to stdout — the one stream the orchestrating loop parses for a reason. Measured on the CI runner (the [runtime-host](runtime-host.md) record carries the measurement): `start` died on a `PermissionError` from inside `store.init_db` and the capture read `exited 1: b''`, which two people spent two days reading as *the verb produced nothing*. So under `json_output` a non-`VerbError` exception now emits the same uniform shape — `{"error": "<ExcType>: <message>", "reason": "unexpected_error"}` — and exits 1, **and still prints its traceback to stderr**: the machine reader gains a payload without the human reader losing the frames. Three exceptions are re-raised untouched because Typer already reports them with their own exit codes: `typer.Exit` and `typer.Abort` (control flow — both subclass `RuntimeError`, so a bare `except Exception` would swallow them and rewrite a verb's deliberate exit code to 1) and `typer.BadParameter` (argument errors, exit 2). Without `json_output` the exception propagates exactly as before: nothing consumes stdout there, and Typer's renderer shows the frames better than a hand-printed traceback — the defect is the machine contract, so that is the only path that changed. Two residuals, stated rather than fixed: a verb body raising some *other* `click` exception directly would be reported as unexpected rather than by Typer (no verb in this package does — `typer.BadParameter` in `harness/cli/_duration.py` is the only `click` exception raised anywhere under `harness/`), and the `--json` path's stderr traceback is now the stdlib's rather than Typer's rich, source-quoting one. The `reason` value is the same literal `unexpected_error` that `harness/events/payloads.py` already uses for `review`'s and `close`'s unreasoned raise sites, so the printed tag and the ledger tag read alike — but it is spelled a third time, in `harness/cli/_verb.py`, with nothing binding the three together.

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
