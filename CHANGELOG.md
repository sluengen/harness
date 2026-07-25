# Changelog

Versions are per-file (see `registry.yaml`). This log records notable changes to the guidance set as a whole.

> Released entries are archived per year under [`CHANGELOG-archive/2026.md`](CHANGELOG-archive/2026.md). This root file keeps only the current `[Unreleased]` window; at each dev→main release its entries move to the archive (see `RELEASING.md`).

## [Unreleased]

### Fixed — the CLI boundary guard derives its subject set from the registrations (#219)
- Filed by `/assess code` (steward, 2026-07-26, finding **CODE-3**, Low, report `assessments/2026-07-26-code.md`). `_COMMAND_MODULES` was a hand-written set of eight stems that the package had outgrown by four command surfaces — `defer` / `release` (tracker-protocol work), `promote` (ADR 0003) and `design` (#211). Because `test_no_command_imports_a_sibling_commands_private_helper` iterates the set for **both** the importing module and the import target, each omission was a blind spot in *both* directions: a private import out of `design.py` and one into `design.py` were equally invisible. The guard was green because nothing violated it, not because it had checked — the same class #215 fixed on the other side of the suite. New `_registered_command_modules` `ast`-parses `harness/cli/__init__.py`, building an import map (absolute and level-1 relative, keyed by bound name so an alias resolves) and reading the two registration forms the CLI uses — `app.command(name=…)(callable)`, a call *of a call*, and `app.add_typer(app_obj, name=…)`. It yields a name → stem mapping, **17 names over 14 stems**, many-to-one where `status` / `logs` / `events` / `runs` all resolve to `query`; `_COMMAND_MODULES` is its value set. The derived set is a strict superset of the retired eight, admitting `query` and `version` as well as the four named: both back registered commands, so under the guard's own definition they are command modules, and the widened set yields zero offenders against the current tree. **Deriving from the live Typer app was rejected as the source**, though `test_cli_surface_locked.py:94` already does it: `add_typer` returns a `typer.Typer` carrying no defining module, so groups would need a second resolution path, and `callback.__module__` resolves through the `query` re-export shim to `query_events` / `query_runs` / `query_status`, silently changing which files get scanned. It is kept instead as the **independent oracle** in `test_derivation_covers_every_registered_command` — two derivations of one surface that must agree, so a registration style the parser cannot resolve fails there naming the command rather than shrinking the guarded set silently. That test is the anti-vacuity check the ticket is really about: an offender scan over an empty set passes trivially. A **positive control** (`test_the_guard_detects_a_cross_command_private_import`) proves the scan fires at all, paired with a public-import negative control; without it the suite only ever proved that nothing currently violates the rule. A filesystem heuristic was rejected as concretely wrong, not merely coarse — `review.py` legitimately imports `_build_cmd` from `review_protocol`, which registers no command. `test_reclaim_does_not_import_from_worktrees` is kept verbatim as the CAL-1013 regression. Nine new tests (4 → 13); offender messages are now `sorted` since a `frozenset` drives iteration. Test-module only — no production code, no distributed guidance file, so no registry bump.

### Added — the design stage is proven under `tracker: none` and at its tracker boundary (#218)
- Filed by `/assess code` (steward, 2026-07-26, finding **CODE-2**, Medium, report `assessments/2026-07-26-code.md`). `test_tracker_less_layer.py` walks `start`, `close`, `reclaim` and the stale sweep, but had no `design` case — even though #212 made `review` refuse `no_design` for **every** run, so the whole tracker-less lifecycle rested on an untested claim in `fetch_ticket_spec`'s own docstring. The claim is correct and the steward traced it; nothing proved it. Two tests close that: `design` on a `tracker: none` repo exits 3 with one `failed` / `no_ticket_spec` event and no comment, and the *following* `review` — grounded on that verb-written event, not a seeded one, which would only have re-proved `test_review_design_linkage.py` — is accepted and records `design_context=false`. Four more in `test_cli_design.py` cover the uncovered tracker-boundary branches: a NULL `runs.ticket` degrading *while a working tracker stub is supplied*, so the degrade can only have come from the missing ticket; both arms of the fetch `except` (`TrackerNotFound`, `TrackerRequestError`) parametrized, since asserting one leaves the other unproven for one line; and the comment-post failure. `design_tracker.py` goes **79% → 98%**. **Four of the five are characterization tests** of already-correct behaviour, where "watch it fail for the right reason" cannot mean "fail because production is missing" — so each was **mutation-checked**: drop the `ticket is None` guard, return a stub spec for the tracker-less branch, swallow the post failure, downgrade exit 1 to `EXIT_DESIGN_FAILED`, and refuse a `failed` design event at the gate. All five mutants killed the test that names them; a characterization test that survives its mutant proves nothing and is the failure mode this ticket exists to prevent. Two traps are recorded in the tests themselves: a runner that *raises* cannot prove the engine was skipped (`_produce_design`'s broad `except Exception` records `engine_error` and the verb still exits 3, so the assertion passes for the wrong reason — hence a recording flag), and `_seed_open_run`'s frozen `started_at` trips `wall_clock_budget` before the design gate is ever consulted, so the `review` test takes a new keyword-only override rather than re-timing four existing callers. The one production change is the genuine red that led: `design.py`'s exit-code list described exit 1 only as "unexpected error", hiding the one exit-1 case a caller can plan for — the comment-post failure deliberately records **no** event, so the run's next `review` refuses with `no_design` until `design` is re-run. Behaviour is untouched throughout; the ticket proves it. App-only — no distributed guidance file, so no registry bump.

### Fixed — the design gate reads its payload keys from single-sourced constants (#217)
- Filed by `/assess code` (steward, 2026-07-26, finding **CODE-1**, Medium, report `assessments/2026-07-26-code.md`). `resolve_design_gate` read the `design` event payload with hardcoded literals — `event.get("status")` and `event.get("design_hash")` — while the constants meant for it, `DESIGN_STATUS_PATH` / `DESIGN_HASH_PATH`, had between them **one** reader: a test asserting a constant equals its own spelling. That violates the CAL-1012 convention recorded at `test_event_payloads.py:288` and enforced for the other two reader modules; #212 added a third reader and extended neither the convention nor its guard. The dead constants were also the wrong **shape** for the consumer they named — `_field_path` yields a `json_extract` path (`$.status`) for a SQL reader, while the gate indexes an already-parsed `dict` and needs the bare field name `_field_name` produces (the `WORKFLOW_FAILED_REASON_KEY` pattern). They are therefore **replaced, not deleted**, and that distinction is the whole point: `_field_name` raises at import if the field is gone, so the constants are the only mechanism making a `DesignEventData.status` rename fail loudly. Deleting them as ordinary dead code — the obvious cleanup — would leave `event.get("status")` returning `None` on a rename, which the gate reads as "not ok", so **every review would silently proceed with no design context**, no warning and no error, while the ledger recorded `design_context=False` on each one as though that were the caller's choice. Enforcement itself is untouched by this (`no_design` keys on the event's *presence*), so the failure would not have opened the gate — it would have quietly stopped applying ADR 0007's conformance criterion to any diff, which is an audit hole rather than a breach, and the harder class to notice. New `DESIGN_STATUS_KEY` / `DESIGN_HASH_KEY` sit beside `WORKFLOW_FAILED_REASON_KEY`; `resolve_design_gate` imports them, a new edge (`review_protocol` → `events.payloads`) that keeps the protocol module pure — two `str` constants, no ledger, no I/O. The `"ok"` / `"failed"` **values** are deliberately left as literals: they are a discriminator vocabulary, not payload keys, and the convention is about keys. Two tests, both written and observed red first: `test_design_gate_source_holds_no_raw_design_key_literals` beside the two existing source-scan guards, banning those two keys specifically rather than the `.get` idiom — `scan_submit_line` legitimately reads `payload.get("verdict")` from the engine's SUBMIT JSON, a different contract with no model behind it — and `test_the_design_gate_reads_the_keys_the_model_writes`, which replaces the spelling assertion by feeding the emitter's real `model_dump` through the gate. A behavioural round-trip alone could not have been the red: the model's field name and the raw literal agree today, so it would have passed against the defect. The seven existing `resolve_design_gate` cases pass untouched as the regression net. The module docstring and `specs/features/run-ledger.md` now record the two constant shapes and which reader each serves, since the convention had only ever been written down for the SQL half. App-only — no distributed guidance file, so no registry bump.

### Fixed — tree-walking test guards enumerate from the tracked set, not the working tree (#215)
- Filed by `/assess code` (steward, 2026-07-25, **CODE-2**), sibling of #214: two abandoned worktrees nested inside `harness/` broke seven tests across three modules, none a code regression — each guard walked the working tree with `rglob("*.py")` and read a stale copy of a guarded source as living. One shared helper, `tests._gitutil.tracked_py_sources`, projects the **git-tracked** set onto `*.py`, sorted and deduplicated (two callers feed it to `parametrize`). The tracked set rather than the ticket's `startswith(".")` filter, which misses a stray tree at a non-dot path; a fourth site the ticket did not name (`test_design_marker.py`) is included, and two hand-rolled sites converted. Nine new tests in `test_gitutil.py`, including a four-way adoption lock. On a clean tree the scanned set is byte-identical (246 = 246).

### Fixed — `reclaim --stale` reads ledger liveness, not just the tracker's `updatedAt` (#216)
- Filed from an unattended Build tick's own pre-flight (2026-07-25): the sweep reclaimed a 60-minute-old run against the 90-minute threshold. On the `tracker: github` backend the tracker timestamp is not a heartbeat — `start` writes the Projects-v2 **Status** field, an *item*-level mutation that never bumps the issue's `updatedAt`, and the other verbs never touch the issue at all. A **live** build past 90 minutes was being reverted to Todo and labelled `reclaimed` underneath itself, then re-picked and duplicated. Staleness now reads the newest of two clocks: the tracker's `updatedAt` and, via new `_ledger_last_activity`, `max(runs.started_at, MAX(events.timestamp))` for the ticket's open run. Ordering is load-bearing — the ledger is consulted only for tickets the tracker already calls stale, so it can spare a live run but never condemn one, and where there is no DB liveness collapses to today's behaviour (proposal **D3** preserved, **D2** amended). Resolves the proposal's deferred heartbeat item with no new mechanism. Eight new tests in `test_cli_reclaim.py`.

### Added — the four-verb lifecycle is documented across the guidance surfaces (#213)
- Breakdown item 4 of 4 of `specs/proposals/design-verb.md`, policy record ADR [`0007`](specs/decisions/0007-design-verb.md); it had to land last, documenting a step items 1–3 had to make real first. `commands/harness.md` gains **Step 1.5 — `design`** (the invocation, `DesignOutput`, implement-against-the-design, unconditional and not tier-gated, the degrade-and-record posture, and the `no_design` exit-5 refusal listed first), plus `--design-file` on the `review` invocation; `CONTEXT.md` moves to "Four verbs, one ledger, one gate"; `spec-authoring` records that the design stage is not a third tier dimension. One canonical lifecycle string is asserted from a single constant in `test_design_verb_lifecycle_documented.py` so the two surfaces cannot drift a second wording. `SPEC.md` / `README.md` / `process/harness.md` deliberately untouched — a known coherence boundary left to a later sweep. **`harness` 0.2.4 → 0.2.5**, **`spec-authoring` 0.9.1 → 0.9.2** (registry **0.5.85 → 0.5.86**).

### Added — `review` enforces the design stage and reviews against the design (#212)
- Breakdown item 3 of 4 of `specs/proposals/design-verb.md` (ADR [`0007`](specs/decisions/0007-design-verb.md)), decisions **D3**/**D4**. `harness review` keys on the run's latest `design` event: no event refuses before any engine runs (**exit 5**, `reason=no_design`, no `review` event recorded), while a `status='failed'` event **satisfies** the check — D4's contract is that a design was attempted and recorded, never that it succeeded. A `status='ok'` design reaches the engine prompt via new `--design-file`, authenticated by the recorded `design_hash`. Enforcement keys on the ledger alone, so the file can neither satisfy nor bypass it; an absent, unreadable, or mismatched file degrades (drops context) rather than wedging the run, recorded as `design_context` on the `review` event. The check sits after the spend breakers and deliberately **before** the gate-evidence check — root cause before symptom. **Watchlist trigger** (`harness/cli/review.py`): seam, not growth — `build_review_prompt` and the pure `resolve_design_gate` moved to `review_protocol.py`. 31 tests in `test_review_design_linkage.py`; new shared `tests/_ledger.seed_design_event` satisfies the precondition in the four review modules that reach an engine.
### Fixed — `resolve_repo_root` refuses a path that is not a git top-level (#214)
- Filed by `/assess code` (steward, 2026-07-25, systemic insight CODE-INSIGHT-1), which found two abandoned worktrees nested at `harness/.worktrees/harness/<id>` — inside the `harness/` *package* directory, where `worktrees cleanup` could never see them again. `resolve_repo_root` accepted any resolvable path inside the allowlist, so a verb invoked with `--repo`/CWD pointing at any subdirectory silently wrote worktrees, branches, and ledger rows under the wrong root. It now also requires a git top-level, raising the new `NotAGitTopLevel` mapped to the existing invocation-refusal contract (**exit 2**, before any side effect). The check is `.git` **presence** (`exists()`, not `is_dir()`) — load-bearing, since a linked worktree carries `.git` as a *file* and the verbs are routinely pointed at a run's worktree (#179). Allowlist-first ordering is pinned by a test, so a path outside the roots keeps its original refusal. Five test modules' fixtures moved to the new shared `tests/_gitutil.init_repo`. (Its sibling finding CODE-2 is #215.)
### Added — the `harness design` verb: engine, ticket comment, ledger event (#211)
- Breakdown item 2 of 4 of `specs/proposals/design-verb.md` (ADR [`0007`](specs/decisions/0007-design-verb.md)). New `harness/cli/design.py` registers the fourth lifecycle verb `harness design [--run-id] [--model]` between `start` and implement: resolve the open run, fetch the ticket spec, capture `grounded_sha`, run the read-only Opus engine under `loop.engine_timeout_seconds`, and record the outcome in three places — the ticket as a marked comment (new `harness/design_marker.py`, the `reclaim_marker.py` pattern), the ledger as a new `design` event (`DesignEventData`: `status='ok'` with `design_hash` + `grounded_sha`, or `status='failed'` with a stable `reason`), and stdout as `DesignOutput`. **Degrade and record (D4):** all five failure reasons (`engine_timeout`, `engine_error`, `no_submit`, `malformed_submit`, `no_ticket_spec`) append a `failed` event, post no comment, and exit 3, funnelled through one `_DesignNotProducedError` handler. Tracker I/O split to `design_tracker.py`, keeping the verb under the 500-line limit (review FAIL cycle 1 caught this and exposed a real trap: `test_source_file_size_justification` reads **git-tracked** files, so a pre-commit gate is blind to a brand-new file). **Watchlist trigger** (`harness/cli/review.py`): the bounded engine subprocess driver moved to new `harness/cli/_engine.py` (shared with `design` rather than copied), `review_protocol.py` re-exports for compatibility. 34 tests across `test_cli_design.py` + `test_design_marker.py`.

### Added — the design engine protocol: prompt, SUBMIT contract, Opus default (#210)
- Breakdown item 1 of 4 of `specs/proposals/design-verb.md` (ADR [`0007`](specs/decisions/0007-design-verb.md)). New pure `harness/cli/design_protocol.py`: `build_design_prompt` (read-only posture, the five required Design sections from `DESIGN_SECTIONS`), `parse_design_submit` returning three distinct outcomes (design / `NO_SUBMIT_SENTINEL` / `MALFORMED_SUBMIT_SENTINEL` — distinct because ADR 0007 degrades either way and the recorded reason is the only evidence of which happened), and `build_design_cmd` for the `claude -p --permission-mode plan --model opus` invocation. `DESIGN_MODEL_DEFAULT = "opus"` is a constant per ADR 0007's unconditional-Opus decision; `resolve_model_tier` is deliberately not wired. Inert until the verb (#211) consumed it. 21 tests in `test_design_protocol.py`.

### Added — review-discipline: extend the sibling-duplication check to backend module files (#209)
- Filed by `/assess code` in nano-erp (CODE-INSIGHT-2, `ERP-179`). The only mechanized check for "a new module copies a sibling's helper" (**Misplaced pure helper**) was scoped to frontend view/screen files, so two backend clones landed in separate tickets unseen. New Stage 2 bullet **Cloned backend module helper**, its backend sibling: grep a new backend module's declared names against siblings; a matching signature is a clone, and belongs in a shared home before approval. **`review-discipline` 0.6.7 → 0.6.8** (registry **0.5.84 → 0.5.85**).

### Added — review-discipline: partial-hook-adoption check also catches skipping the hook entirely (#208)
- Filed by nano-erp's `/assess code` (CODE-INSIGHT-1, `ERP-178`). #194's "Partial hook/utility adoption" rule only fired once a call site *imported* the shared hook, so twice in one range a call site that skipped the hook entirely and hand-rolled its whole contract never tripped it. The bullet now triggers on the **shape of the diff** — a fetch or write-then-refetch flow, or a hand-rolled `useState` load/save/refusal sequence — catching both partial adoption and full non-adoption. **`review-discipline` 0.6.6 → 0.6.7** (registry **0.5.83 → 0.5.84**).

### Changed — code-quality: broaden the mirroring self-admission trigger from helper to any duplicated unit (#206)
- From the form repo, CAL-1214 (`/assess code`, CODE-INSIGHT-1). `code-quality`'s "Extract on the third strike" admission-comment rule was worded around "a helper mirrors a sibling", which reads as scoped to pure functions — so three UI components each admitting in a doc comment that they mirror the previous one never pulled the trigger across three separate ticket reviews. The trigger's subject broadens to "a helper, component, or module", explicitly covering a duplicated rendering/structural shell. This entry also folded #185–#181. **`code-quality` 0.16.0 → 0.16.1** (registry **0.5.82 → 0.5.83**).

### Added — ship the guidance-feedback-upstream rule (#205)
- Breakdown item 1 of `specs/proposals/guidance-feedback-upstream.md` (accepted 2026-07-20), whose tracking ticket was diverted into an unrelated fix and lost in the Linear→GitHub cutover, leaving the doc edit unshipped. `process/harness.md`'s "Updating the guidance" section (mirrored byte-identical into `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`) gains the rule: on a guidance defect, friction, or idea, search existing issues, then draft a GitHub issue against the `source.repo` resolved from `.guidance-lock.yaml` — never hardcoded, never sent unattended, never carrying the consumer's proprietary code. Review FAIL cycle 1 caught a missing CHANGELOG entry (#202 precedent).

### Added — code-quality / review-discipline: a placeholder/stub must be flag-gated, not reachable from a live CTA (#204)
- From the form repo, CAL-1130 (`/assess code`, CODE-INSIGHT-1), decided 2026-07-24. Two stubs one day apart in the originating repo were both wired to live, ungated surfaces and both filed after the fact; the repo owned a gating mechanism but no rule mandating it. `code-quality` Part A gains **Placeholder and stub gating** — a function returning hardcoded/faked data in place of real logic must not be reachable from a live CTA without a gate — with the matching `review-discipline` Stage 2 check.

### Added — test-driven-development: cover each of a guard's trigger conditions, not just the one that trips first (#203)
- From an `/assess code` steward pass against a consuming repo: a multi-condition guard's suite exercised only one of its independent trigger paths, so deleting the other left all 422 assertions green while the untested condition was exactly what let a real defect through. RED gains a bullet after "Cover the active loop, not just its exit": a guard with several independent trigger conditions needs one test per condition, each proved to fail for its own reason.

### Added — wire `/bug` and `/tweak` into the process docs + command table (#202)
- Breakdown item 4 of `specs/proposals/bug-and-tweak-capture-commands.md`, landing last so the docs describe what shipped: `spec-driven-development` and `spec-authoring` name the capture on-ramp, and `process/harness.md`'s Commands table (mirrored into `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`) gains `/bug` + `/tweak` rows and one sentence stating the three-way boundary — `/propose` decides the unconfirmed, `/bug`/`/tweak` capture the confirmed-small, `/start` picks up the filed. **`process-harness` 0.4.8, `spec-driven-development` 0.5.1, `spec-authoring` 0.9.1** (registry **0.5.79**).

### Added — `commands/bug.md`: files a bug straight to Todo (#200)
- Breakdown item 2: new `commands/bug.md`, a thin capture command filling the shared template with `kind: bug` and filing straight to Todo with no escape hatch (a bug's fix direction is never in doubt — contrast `/tweak`, #201). Documents both tracker backends, including the three-step `gh issue create` → `item-add` → `item-edit --single-select-option-id` that explicitly sets Status=Todo, closing the item-add-no-status trap (tick #90) where a filed item is invisible to `work-discovery`. **New `bug` 0.1.0** (registry **0.5.76 → 0.5.77**).

### Added — new `templates/adjustment.md`: the shared capture template for `/bug` and `/tweak` (#199)
- Breakdown item 1 of `specs/proposals/bug-and-tweak-capture-commands.md`: the capture front door had nowhere lightweight to land. New `templates/adjustment.md` — `kind: bug | tweak` / `area` frontmatter, *As-built (observed)* / *Desired* / *From actual use* / *Acceptance criteria* with per-kind framing, and a `tweak`-only escape hatch to `/propose`. Framed as a capture-optimized change spec extended by `/start`, not a competing artifact. **New `template-adjustment` 0.1.0** (registry **0.5.76**).

### Added — `review-discipline`: CONTEXT.md currency bullet also covers a repo's release runbook (#198)
- A tracker cutover or branch-topology amendment could update `CONTEXT.md` correctly while leaving a sibling release runbook silently describing the old world — what happened at the Linear→GitHub cutover and the dev→staging→main amendment (see #196). `review-discipline`'s CONTEXT.md currency bullet now also fires on a diff changing `tracker:` or `branches:` roles, phrased generically (no filename hardcoded, since it ships to every consuming repo and a literal cite would trip the app-only-cite guard). **`review-discipline` 0.6.4 → 0.6.5** (registry **0.5.74 → 0.5.75**).

### Added — `work-discovery` gains the return path: when a held ticket is clearable and what released means (#192)
- The skill owned only the outbound half (skip a held ticket); the inbound half — what makes a hold clearable and what "released" means — was unwritten, so `/decision` (#193) had nowhere to delegate it. New Return path section, single-homing the definition the command consumes rather than restating it there.
### Added — `harness defer --needs` gains a third hold kind, `input` (#191)
- Per ADR 0006: `decision`/`operator` did not partition the space, so a ticket waiting on the operator to *supply* something was mis-filed, and `/decision` (#193) would have had to re-triage every sweep. `DeferNeeds` gains `input` (the value stays the additively-applied label name); `work-discovery` names and skips all three, assignment stays the authoritative skip signal, and `operator` narrows to interactive-session-only.
### Added — `/promote`: agent-orchestrated fallback for repos without the harness app (#190)
- `commands/promote.md` gains a `## Fallback: no harness app` section — the `/build`-is-available-everywhere pattern applied to release movement, with `$PATH` detection specified. Deliberately reduced per ADR 0003's 2026-07-23 amendment (conflict → stop, red gate → stop, no repair attempt), keeping the verb-backed path's hop asymmetry, plus a stated "what you lose without the ledger" paragraph so a later reader does not "complete" it into a second drifting implementation.
### Added — `/promote`: a versioned command over the harness promotion verbs (#189)
- The five promotion verbs shipped (ADR 0003) but their caller existed only as `RUNBOOK.md` prose — unaddressable and uninstallable. New `commands/promote.md` transcribes the loop as a universal command: `/promote <src> to <dst>` resolves each word against `CONTEXT.md` `branches:` roles first, so one invocation drives any repo's own branch names. Documents all ten lifecycle states, the forbidden outer-agent actions, and the bounded-repair/escalation policy; `RUNBOOK.md` now keeps only this repo's cadence and points here. **New `promote` 0.1.0.**
### Earlier unreleased changes

> The entries below are folded to one-line summaries to keep this file under its 60,000-byte size gate between releases (CAL-1182). This is the *condense* fix, chosen over forcing a `dev → main` release: the release stays a deliberate, separately-gated act (`main` is PR-only per CAL-1029; the promotion lifecycle is ADR 0003), not a side effect of a headroom fix. Full detail is in git history, and each entry rotates to [`CHANGELOG-archive/2026.md`](CHANGELOG-archive/2026.md) at the next release.

### Added — code-quality: a linter enforces the file-size limit where it can (#185)
- Where the repo's linter already has a file-length rule (`max-lines`), turn it on instead of writing the size-guard walker — commit-time enforcement, and an unused rule-disable is itself reported. **`code-quality` 0.14.0 → 0.15.0** (registry **0.5.66 → 0.5.67**).

### Added — review-discipline: a CONTEXT.md currency trigger on the stage-two checklist (#184)
- Stage 2 gains a **CONTEXT.md currency** bullet: a diff that adds/removes a test runner, gate step, workspace, or top-level path must be checked against `CONTEXT.md`'s `stack`/`commands`/`layers` block — a stale entry there is a Medium finding. **`review-discipline` 0.6.2 → 0.6.3** (registry **0.5.65 → 0.5.66**).

### Added — code-quality: a security-contract test asserts the predicate, not the name (#183)
- A security-contract test proving a control exists (RLS policy, auth guard, CSP directive) must assert what it *evaluates to*, not merely that it's present, paired with a negative fixture. **`code-quality` 0.13.0 → 0.14.0** (registry **0.5.64 → 0.5.65**).

### Added — spec-driven-development requires the as-built record before a surface accumulates a second ticket (#182)
- A surface's as-built record (feature spec, or design-doc section where `feature_specs` is off) must exist before a second shipped ticket lands on it; propagated to `review-discipline`, `reviewer.md`, and `commands/review.md` so it is reachable at review time. **`spec-driven-development` 0.4.0 → 0.5.0, `review-discipline` 0.6.1 → 0.6.2, `reviewer` 0.1.6 → 0.1.7, `review` 0.1.3 → 0.1.4** (registry **0.5.63 → 0.5.64**).

### Added — review-discipline verifies a type predicate covers every required field (#181)
- Stage 2 gains a **Type predicate coverage** check: for every `value is T` predicate, enumerate `T`'s required fields and confirm the guard checks each one, not a subset. **`review-discipline` 0.6.0 → 0.6.1** (registry **0.5.62 → 0.5.63**).

### Added — a numeric duplication threshold for scope discipline (#180)
- `code-quality` Part A gains a duplication threshold: a copy in one other place must be named and justified in the change spec; a copy in two places must be extracted now — grep sibling modules before writing a helper. **`code-quality` 0.12.0 → 0.13.0**.

### Added — per-ticket model tiering: `review` honors a `review:<tier>` label (#177)
- New `resolve_model_tier` reads a `build`/`review` `<tier>` GitHub label (default `sonnet`); `harness review` resolves the `review` tier and appends `--model <alias>` for the claude engine only. ADR 0005. **`spec-authoring` 0.8.0 → 0.9.0, `commands/harness.md` 0.2.2 → 0.2.3**.

### Fixed — the run ledger mis-resolves under a worktree `--repo` (#179)
- `resolve_verb_db_path` now walks up via a new `git_common_dir` helper to the worktree's main checkout before appending `.harness/harness.db`, fixing a false `"no open run found"` when a verb runs with `--repo`/CWD pointing at a worktree.

### Added — `/update-guidance` adopts a registry-listed, on-disk, lock-untracked file (#173)
- Step 2 names the registry-listed/on-disk/lock-untracked case explicitly (silently adopt on hash match, else a CONFLICT-shaped 2-way reconcile) so a file graduating to a distributable is never left stranded. **`update-guidance` 0.5.3 → 0.6.0**.

### Added — a gate guard against repo-guide guidance drift (#169)
- `scripts/check_landing_page_guidance.py` fails the verify gate when `docs/index.html`'s `data-guidance="<id>"` references a ghost entry missing from `registry.yaml`, or names no guidance at all. ADR 0004.

### Added — bootstrap guidance for the github tracker backend (#168)
- `templates/CONTEXT.template.md` gains a commented `github:` block (`repo`/`project`/`status_field`) and `BOOTSTRAP.md` generalizes the tracker-credential bootstrap step. **`template-context` 0.1.12 → 0.1.13**.

### Changed — CONTEXT schema marks `repo.project` optional (#176)
- `repo.project` documented as optional: set → the `/harness routine` loops scope to that project; unset → the whole tracker queue (the Linear team, or the github board). **`template-context` 0.1.11 → 0.1.12**.

### Changed — nullable project scope on the tracker seam + reclaim CLI (#174)
- `Tracker.fetch_reclaimable_issues(*, project: str | None)` widens across the seam and both backends; `harness reclaim --stale` no longer requires `--project`.

### Changed — conditional, tracker-neutral build-loop scoping (#175)
- `work-discovery` and `/harness routine build` read `repo.project` as an optional scope lever instead of hardcoding one Linear project. **`work-discovery` 0.3.0 → 0.4.0, `harness` command 0.2.1 → 0.2.2**.

### Added — a GitHub Projects v2 tracker backend behind the seam (CAL-1105)
- `harness/github.py`'s `GitHubClient` implements `Tracker` over GitHub Issues + a Projects v2 `Status` single-select field (resolved by name), superseding the `UnsupportedTrackerError` placeholder; auth via `GITHUB_TOKEN`.

### Added — host the repo-guide page on GitHub Pages + link from README (CAL-1201)
- `docs/index.html` gains Open-Graph/Twitter meta tags, a favicon, and share assets; the README links the hosted guide. `specs/infrastructure.md` records the GitHub Pages hosting decision.

### Added — a self-contained repo-guide landing page at `docs/index.html` (CAL-1200)
- `four-loops.html` grew into `docs/index.html`: the Four Loops model, a harness-verbs section, and a guidance catalogue, each `data-guidance="<id>"` resolving in `registry.yaml`.

### Fixed — GitHub detects the licence as AGPL-3.0 (CAL-1198)
- `LICENSE` restored to byte-exact AGPL-3.0 text (a prepended note had diluted it below licensee's 98% threshold); the MIT carve-out renamed to `GUIDANCE-MIT.md`, off the licence glob, so only one root licence is detected. **`bootstrap` 0.5.0 → 0.5.1**.

### Changed — verbs obtain their tracker through a seam factory (CAL-1197)
- Every verb now obtains its tracker via `tracker_client(repo_root)` (a `@runtime_checkable Tracker` protocol) instead of constructing `LinearClient` directly — the seam a second backend (github, CAL-1105) plugs into without touching a verb.

### Changed — `close` merges in a throwaway worktree, not the main checkout (CAL-1154)
- `close`'s merge/push moved into a detached `.worktrees/harness/<run_id>-close` worktree off `origin/<base>`; the main checkout stays untouched, and the `dirty_base_checkout` refusal is retired from the locked verb contract. **`commands/harness.md` 0.2.0 → 0.2.1**.

### Added — `doctor` flags a drifted `~/bin/harness` wrapper (CAL-1149)
- New `check_wrapper` compares the host-side `~/bin/harness` against the versioned `docker/harness-wrapper.sh`, surfacing symlink/copy/drifted/detached via `HARNESS_WRAPPER_STATUS`.

### Changed — CI runs on `dev`, not only `main` (CAL-1030)
- `.github/workflows/ci.yml` now triggers on `[main, dev]`, so `close`'s direct pushes to `dev` are verified at merge time instead of waiting for the release PR.

### Changed — `code-quality` Part A: an extraction sweeps for its copies (CAL-1172)
- Part A gains *An extraction sweeps for its copies*: grep the whole tree post-extraction; a divergent surviving copy is the finding, not the leftover. **`code-quality` 0.11.0 → 0.12.0**.

### Changed — the feature template demands a production call site per exported entry (CAL-1171)
- `templates/feature.md` requires a named production caller per exported interface entry; an uncalled entry routes to Known limitations instead of "delivered API". **`template-feature` 0.1.1 → 0.2.0**.

### Fixed — `checkpoint` re-pushes a rebased run branch (force-with-lease) (CAL-1162)
- `harness checkpoint` pushes with `--force-with-lease` so a rebase-before-close no longer silently reverts durability to the pre-rebase commit; a genuine remote race surfaces as `reason='stale_remote'`.

### Changed — `/assess` findings file to Todo, with a widened autoMode clause (CAL-1168)
- `/assess` step 2 now files findings/insights to **Todo** (was ad hoc) with severity-mapped priority; the filing `autoMode.allow` clause carries the operator's verbatim-approved text. **`assess` 0.6.1 → 0.7.0**.

### Added — `harness defer v2`: `--needs`, assign-on-defer, approved autoMode clause (CAL-1167)
- `harness defer` gains `--needs decision|operator` and assigns the ticket to the operator (`LinearClient.assign_to_viewer`) as the machine-readable hold signal. **`harness` command 0.1.9 → 0.2.0**.

### Changed — `work-discovery` skips on assignment, defers with assignment (CAL-1166)
- The skip rule keys on assignment to a human (any state, with a transitional label OR); deferral now assigns the operator alongside the comment + label. **`work-discovery` 0.2.0 → 0.3.0**.

### Changed — ticket protocol codified in the `linear` skill (CAL-1165)
- Todo/Backlog filing rules, assignment-as-hold-signal, and the `operator` label documented; `projectId`/`assigneeId` set on create. **`linear` 0.4.2 → 0.5.0**.

### Fixed — a promotion gate whose toolchain can't run is `blocked`, not a false code ticket (CAL-1160)
- New `GATE_UNRUNNABLE_EXIT` (97) maps to `blocked` via `classify_gate_failure`, closing the unreachable `exit_code is None` path that used to file a false `needs_ticket`.

### Fixed — `promote` gates host-side, so the promotion success path is reachable (CAL-1159)
- `promote start`/`continue` gain `--gate-exit`/`--gate-log` (mirroring `review`) and classify host-supplied evidence instead of running the gate inside the toolchain-less container; new `gate_pending` state.

### Changed — the tracker switch collapses to a single `tracker:` field (CAL-1164)
- `tracker: linear | github | none` replaces the derivable `layers.linear` boolean as the single on/off-plus-backend fact; `tracker_config_error` rejects an incoherent switch/address pair at `start`.

### Added — a distributed reference for the mechanical size-marker guard (CAL-1156)
- New `templates/size-guard.md` ships a repo-editable `# size: <reason>` walker for consuming repos, execute-verified against fixtures. **`code-quality` 0.10.0 → 0.11.0**.

### Fixed — the wrapper is shellcheck-clean, and its guard no longer skips silently (CAL-1150)
- Fixed a latent SC2046 in `docker/harness-wrapper.sh` (the `-it` flags were built with an unquoted command substitution) by assembling them in a `TTY_ARGS` array; the shellcheck guard now warns audibly when shellcheck is absent instead of skipping silently, with `bash -n` as the always-on floor.

### Fixed — the image-freshness guard no longer disables itself silently on a detached copy (CAL-1153)
- The CAL-1144 image-freshness guard silently no-op'd on a wrapper copied outside any checkout (the real `~/bin/harness` install), disabling it in exactly the deployment it protects; it now warns once on stderr naming the detached-copy cause and the symlink remedy, and three new tests exercise the real wrapper from a copy and a symlink.

### Added — tests own the state they mutate (CAL-1161)
- New `engineering-principles` principle (**0.3.0 → 0.4.0**, registry **0.5.48 → 0.5.49**): a suite provisions its own instance and disposes it at teardown, never borrowing state that outlives the run — sourced from a consumer repo whose documented test command destroyed its shared dev database, and placed in principles (not TDD) because it is about isolation, not real-vs-mock.

### Changed — the staging hop direct-pushes on a green gate; the no-auto-merge rule scopes to the release hop (CAL-1158)
- The ADR-0003 no-auto-merge rule now scopes to the *release* hop only: the nightly `dev → staging` hop direct-pushes the gated SHA (`DIRECT_PUSH_TARGET` allowlist = `staging` alone, refusing `main` before any git runs) and opens no PR, recorded as a new terminal `promoted` state; `main` stays the single PR-gated human decision point.

### Fixed — drop the stale org gloss on the Linear team prefix
- Deleted the stale `Calibrate-coffee (CAL)` gloss on `CONTEXT.md`'s `linear: CAL` team key (also in `specs/infrastructure.md` and two `tests/` fixture copies) — the key is opaque and the only thing the API uses, and correcting it to the current org name would publish a private name into generic infrastructure other repos self-host.

### Fixed — the private-surface guard was blind to the workspace's former slug (CAL-1029)
- `test_no_private_surfaces` knew only the *current* workspace slug, leaving 24 former-slug `linear.app` URLs standing across four `specs/` files; redacted to the bare `CAL-xxx` ids (the forbidden tuple now grows on a rename). Also: `SECURITY.md` states the ledger is not tamper-evident, and `ci.yml` pins `contents: read`. CAL-1029 stays open for the operator-run visibility flip.

### Fixed — `close` no longer merges into a base checkout it has not checked, and never hides a failed cleanup (CAL-1151)
- `close` was mutating the base checkout without validating it; CAL-1151 made it refuse `dirty_base_checkout` before the first mutation, stopped discarding the merge-abort exit code, and split the conflicted-vs-refused-to-start error messages. (The throwaway-worktree redesign that superseded the `dirty_base_checkout` precondition landed as CAL-1154, above.)

### Fixed — the wrapper rebuilds a stale `harness:dev` instead of silently running it (CAL-1144)
- Nothing rebuilt the `harness:dev` image after a merge, so an unattended tick could silently run an old verb; the freshness guard now lives in the wrapper and rebuilds (rather than refuses) when `harness/` has moved, with a failed rebuild exiting non-zero instead of falling through to the stale image.

### Added — the advisory `/assess` report commit is sanctioned; `gh pr merge` is denied (CAL-1140)
- `settings/harness.json` **0.5.0 → 0.6.0**: a seventh `autoMode.allow` clause sanctions the unattended `/assess` report commit to `dev` (bounded to `assessments/`), and `Bash(gh pr merge *)` is now denied so all integration routes through the `close` verb's HEAD-bound gate (discharging CAL-1142's deferred fifth deny).

### Added — `harness/cli/close.py` is armed on the architecture watchlist (CAL-1139)
- Armed `harness/cli/close.py` on the `CONTEXT.md` architecture watchlist (gate + ledger + git concerns accreting in one module); splitting it is out of scope, and `linear.py`'s exclusion (its size is guard-mandated cohesion) is pinned as a tripwire.

### Added — the OpenCode + MLX local orchestrator spike (CAL-1134)
- Recorded the OpenCode + MLX local-orchestrator stack for driving nightly promotion cheaply in `specs/local-orchestrator-stack.md` (marked a hypothesis — nothing is installed here), guarded by a drift test that derives subcommands and stop-conditions from the live `promote` surface.

### Added — `harness defer` verb: the triage write as an audited verb (CAL-1143)
- New `harness defer <TICKET> --reason <text>` verb: triage was the one lifecycle write the routine hand-rolled as raw GraphQL; it now posts the reason, additively applies the `decision` label, and records a `defer` event on its own terminal `runs` row — binding triage to its `autoMode` clause and the ledger.

### Fixed — the release-facing docs describe what actually shipped (CAL-1111)
- The README changelog was an era behind and `RELEASING.md`'s checklist named a roadmap table neither file ever had; added a `2026-07` era entry, removed the phantom item, and pinned currency with `test_release_docs_currency.py`.

### Added — `harness promote start` / `continue` worktree + merge mechanics (CAL-1115)
- Filled the `promote start` / `continue` write-path openers on a new `harness/promotion.py`: worktree + `--no-ff` merge from the target, conflict classification (`agent_may_fix` vs `needs_ticket` by file kind/count), and a resumable one-repair `continue`; `merged_sha` added to the locked `Promotion` contract.

### Changed — the `~/bin/harness` wrapper is a versioned file, not a README heredoc (CAL-1123)
- Promoted the wrapper from a README heredoc to a real versioned `docker/harness-wrapper.sh` (mode 755, `bash -n`-clean), recommended to be symlinked onto `PATH` so fixes propagate on `git pull`; the container-hardening guards now assert against the file, not prose.

### Added — `code-quality` names a narrowing's worklist as the transitive consumers of the field (CAL-1100)
- `code-quality` **0.8.0 → 0.9.0**: a narrowing at a boundary is a whole-call-graph change — the worklist is every transitive consumer of the field, not the callsites a coercion-operator grep returns (from the 2026-07-16 assessment).

### Added — `spec-authoring` requires a scope-claim invariant to cite its enumeration or be recorded as a finding (CAL-1101)
- `spec-authoring` **0.6.0 → 0.7.0**: any scope claim ("the only consumer", "exactly one home") must cite the enumeration that establishes it, or a second consumer is a finding, not an invariant. (Both this and CAL-1100 filed from `assessments/2026-07-16-code.md`; registry **0.5.45 → 0.5.46**.)

### Fixed — `doctor` probes that the review engine can actually run, not just that it is on PATH (CAL-1083)
- `doctor`'s reviewer check now runs a `--version` liveness probe per engine (`absent` / `cannot_run` / `ok`) instead of a PATH-only `which`, so an on-PATH-but-unrunnable engine FAILs (Codex's in-container `bwrap` per ADR 0002); it also WARNs when a repo defines no `verify:` gate.

### Fixed — the wrapper joins group 0 so the non-root container can reach the forwarded ssh-agent socket (CAL-1122)
- `close`/`checkpoint` SSH pushes failed because the non-root (`USER harness`) container couldn't reach Docker Desktop's root-owned forwarded ssh-agent socket; fixed with `--group-add 0` in the wrapper (the socket is group-rw), without weakening CAL-1008's credential hardening.

### Added — the verbs run tracker-less under `layers.linear: false` (CAL-1104)
- The verbs now run tracker-less under `layers.linear: false` (previously hard-required Linear despite the advertised switch): new `harness/layers.py` reads the block-scoped key, `start` treats its arg as an opaque run id, `close`/`reclaim` degrade honestly, the review gate is untouched, and the layer defaults on conservatively. `templates/CONTEXT.template.md` **0.1.9 → 0.1.10**.

### Fixed — redact workspace URLs leaked into a public proposal
- Redacted nine full `linear.app/<workspace>` URLs leaked into `specs/proposals/local-promotion-steward.md` to the bare `CAL-xxxx` ids — `test_no_private_surfaces` had been red on `dev` (CI ran only on `main` pushes then), blocking the gate for every ticket.

### Added — `review` requires recorded verify-gate evidence (CAL-1082)
- `review --gate-exit <code> [--gate-log <path>]` now records verify-gate evidence bound to `reviewed_sha` (green → the engine runs and the event carries `gate_ran`/`gate_command`/`gate_exit_code`/tail; red → refuses `gate_failed` before the engine; configured-but-absent → `no_gate_evidence`), and `close` gains a `no_gate_evidence` backstop for pre-change passes. New `harness/gate.py`; `commands/harness.md` **0.1.7 → 0.1.8**.
