# Changelog

Versions are per-file (see `registry.yaml`). This log records notable changes to the guidance set as a whole.

> Released entries are archived per year under [`CHANGELOG-archive/2026.md`](CHANGELOG-archive/2026.md). This root file keeps only the current `[Unreleased]` window; at each dev→main release its entries move to the archive (see `RELEASING.md`).

## [Unreleased]

### Fixed — the empty-roots workspace refusal names `~/bin/harness` as the expected entry point (#246)
- A venv-activated shell's native `harness` console script has no `HARNESS_WORKSPACE_ROOTS` set, so it failed closed naming only the path and the empty allowlist — neither of which was wrong. `WorkspaceNotAllowed` now appends a wrapper hint when `roots == []`; the configured-but-outside-roots branch is unchanged. 8 new/changed tests. No registry bump.

### Fixed — `review` names why a design was dropped, and refuses a `--design-file` the container cannot reach (#247)
- Measured across 34 design-era reviews, 7 ran `design_context=false`; 4 of those had passed `--design-file` at a host-only path like `/tmp` the `~/bin/harness` wrapper never mounts, so the container silently dropped it per ADR 0007 and still recorded a `pass`. `resolve_design_gate` now returns `context_reason` (`not_supplied`/`unreadable`/`hash_mismatch`/`design_failed`), recorded on the `review` event as `design_context_reason`; a `--design-file` outside the `HARNESS_WORKSPACE_ROOTS` allowlist is now refused up front (`reason=design_file_outside_workspace`, exit 5) instead of silently dropping. `commands/harness.md` Step 3's own example carried the `/tmp/design.md` anti-pattern; fixed. 20 new/changed tests. `harness` command 0.2.9 → 0.2.10 (registry 0.5.98 → 0.5.99).

### Fixed — a missing ledger now reports `no_ledger`, not `no open run found` (#244)
- Found auditing 188 session transcripts: `no open run found for worktree ...` is the single most common verb failure in Sonnet-orchestrated sessions, and it recurs read as a dead run rather than as working-directory drift — because a `db_path` that does not exist on disk resolved to the same `None` as a ledger genuinely holding no open row. `resolve_open_run` (`harness/cli/_runs.py`) now raises `LedgerNotFoundError` (`reason="no_ledger"`, naming the resolved `ledger_path`) in place of the old `return None`; `checkpoint` / `review` / `close` / `design` all inherit the fix through `run_verb`'s shared `VerbError` handling, no per-verb edit. The ledger-present "genuinely no open run" case (`close`'s `no_run` included) is unchanged. 20 new/changed tests across `test_runs_resolver.py` and new `test_verb_ledger_missing.py`, parametrized over all four verbs. `harness` command 0.2.8 → 0.2.9 (registry 0.5.97 → 0.5.98).

### Added — skills/design-system: route to the scaffold contract when no system exists yet (#240)
- `SKILL.md`'s two-stage lookup pointed at `CONTEXT.md` `paths.design_system` for the system itself but gave no way forward when that key is unset or dangling — the state every repo starts in (#239 shipped the thing to point at). New fallback paragraph in the lookup: stand the system up from `templates/design-system.md` and set `paths.design_system` to where it landed; restates the no-hardcode rule inline so a future trim can't drop it. An external-but-uninstalled system, or one with declared `status: scaffold` layers, does not trigger the fallback. 8 new tests in `test_design_system_fallback.py`. `design-system` 0.3.1 → 0.4.0 (registry 0.5.96 → 0.5.97), minor — a behaviour a consuming repo has never seen.

### Added — templates/design-system.md: the eight-layer scaffold contract (#239)
- Accepted proposal `design-system-scaffold`: `skills/design-system/SKILL.md` routes to `CONTEXT.md` `paths.design_system` for the system itself but shipped nothing at that end. New distributed contract doc — the eight layers, the one-way dependency rule, the three rules, the five-field frontmatter contract, the three token tiers plus naming scheme, output discipline, and the stack seam named explicitly as the adopting repo's job (two worked shapes cited by stack, not by source repo). 12 new tests in `test_design_system_template.py`. `templates/design-system.md` 0.1.0 (registry 0.5.95 → 0.5.96), new file.

### Fixed — `harness design` detects and warns on a nested-background double invocation (#236)
- Observed running `/harness run 233`: a nested-background `design` invocation (a bare `&` chained inside a command also launched via the runtime's own background flag) looked dead on an empty output read but was still finishing; a clean retry raced it, and the stray invocation's later write silently became the run's bound design — idempotent-by-append semantics doing exactly what they should, just on the wrong pair of writers — diverging from what had already been implemented against, surfaced only indirectly as a review verdict. `DesignEventData` gains `invoked_at` (captured before engine work) and `concurrent_prior_at`, set when a run's prior `design` event finished at or after `invoked_at`; `_record_design_event` compares before writing and, on overlap, stamps the flag and warns on stderr — detection fails open on a read/parse error (ADR 0007 D4). `DesignOutput` carries the same flag (`exclude_none=True`; the six-key contract is unchanged), as does a failed attempt. `commands/harness.md` Step 1.5 now warns against nested backgrounding and the empty-output-means-not-finished trap. 9 new tests across `test_cli_design.py` / `test_event_payloads.py` / `test_review_design_linkage.py`. `harness` command 0.2.6 → 0.2.7 (registry 0.5.93 → 0.5.94).

### Fixed — `commands/harness.md` documents that a breaker trip needs `cancel` before `--resume` (#237)
- After `review` refused `reason=wall_clock_budget`, `harness start <TICKET> --resume` returned the *same* `run_id`/`started_at` — `start` resolves an existing open row before resume runs, so the budget carried over and the next `review` tripped again. New "Recovering from a breaker trip" note in Step 3 (checkpoint, handoff comment, `harness cancel <run_id>`, then `--resume`), cross-referenced from the handoff section. New `test_breaker_recovery_docs.py` plus 3 `test_cli_start.py` pins. `harness` command 0.2.7 → 0.2.8 (registry 0.5.94 → 0.5.95), patch — stacks on #236's bump.

### Fixed — `worktrees cleanup --merged` no longer deletes an open run's stashed-not-committed WIP (#235)
- Observed in `nano-erp`: a run's WIP was `git stash`'d (not committed) mid-work, leaving its branch tip identical to `dev` — trivially a `merge-base --is-ancestor` match even though the run was still `open` in the ledger. `--merged` deleted the worktree *and* the branch out from under it; the work was only recoverable via dangling-object forensics. `--merged` now runs three vetoes before honouring an ancestry match, first hit wins: the run's ledger row is non-terminal (new `harness.state.schema.IN_FLIGHT_STATUSES`, matched by `worktree_path` then `run_id`); `git stash list` has an entry for the branch; the worktree has uncommitted, unstashed changes. A vetoed worktree is kept (reason printed) unless new `--force` is given. `--age` is unchanged — it exists to reclaim the directories of runs that never closed, so vetoing there would re-open the CAL-767 cruft leak; it still retains the branch and never touches `refs/stash`. `harness.cli._abandon.CANCELLABLE_STATUSES` becomes an alias of the same set rather than a second definition. 25 new/changed tests (`test_cli_query.py`, `test_run_statuses.py`) covering the ledger/stash/dirty vetoes, the unrelated-branch non-veto, `--force`, the `--age`+`--merged` interaction, worktree_path matching, and a failed-probe conservative default. `harness` command 0.2.5 → 0.2.6 (registry 0.5.92 → 0.5.93) — corrects the "never removes a recent, unmerged worktree" claim and documents `--force`/`--db`.

### Fixed — the ticket-Done transition is verified against its own mutation response, not trusted (#233)
- Reported from a downstream repo: `close` reported `ticket_done: true` while the tracker's issue actually stayed In Review — the transition mutation returned success but the state change never took, and nothing re-checked. `LinearClient._transition` / `GitHubClient._set_status` now confirm the post-write state off the same mutation response; a mismatch raises `TrackerTransitionUnconfirmed`, and `close` maps it to `reason=ticket_transition_unconfirmed` (exit 1, `merged: true` — the merge already landed; re-running `close` recovers idempotently). `CloseOutput.ticket_done: true` now means *observed*, not merely attempted. 8 new tests, ~7 updated fixtures. No registry bump.

### Added — templates/size-guard.md: a declarative-ceiling constant matching Part B/C's claim (#234)
- Filed as a carry-forward from #232's design stage (`code-quality` Part A). Part C's prose already claimed the walker's config carries "the higher declarative-file ceiling from Part B", but the shipped reference only had `EXEMPTIONS` — a wholesale skip, not a raised ceiling. New `DECLARATIVE_GLOBS` / `DECLARATIVE_CEILING` constants (default 1.5x `HARD_LIMIT`, matching #232's number), applied only to files the globs match; a declarative file above the raised ceiling is still an ordinary offender, not exempt. Default is inert (`DECLARATIVE_GLOBS = ()`), so re-copying the template changes no adopter's result. 13 new tests in `test_size_guard_reference.py`, including one pinning that Part C's claim and the shipped constant agree. `templates/size-guard.md` 0.1.0 → 0.2.0 (registry 0.5.91 → 0.5.92), minor — a rule a consuming repo has never seen.

### Added — code-quality: the declarative ceiling is mechanized where the limit is enforced, not left to prose (#232)
- Filed via a downstream repo's steward assessment, routed upstream per this repo's own guidance-fix-routing rule. Part B named a declarative-file ceiling but no number and no mechanism, while the same skill directs mechanizing the hard limit through the linter's `max-lines` — a repo following both could end up with a flat cap, a contract test pinning it, and an exemption no tool reads. The grant now requires the exemption be declared as a linter `overrides` entry in the same change, defaulting to 1.5x the hard limit unless the repo sets its own. Four new tests in `test_declarative_ceiling_mechanized.py`, scoped to the grant's own paragraph. `code-quality` 0.19.0 → 0.20.0 (registry 0.5.90 → 0.5.91); minor, matching #220/#227/#231 — a rule a consuming repo has never seen. Lands on top of #231's same-file bump (both independently targeted 0.19.0/0.5.90; re-based to the next number rather than colliding on it).

### Added — code-quality: a sync-critical pattern extracts on the second copy, not the third (#231)
- Filed via a downstream repo's steward assessment, routed upstream per this repo's own guidance-fix-routing rule. The rule-of-three held the builder to a laxer bar than the steward's cross-file-duplication lens (`agents/steward.md` lens 2), which already applies two-or-more when the duplicated thing is a security check, an auth gate, or a domain rule that must stay in sync — so a duplicated authorization predicate could accumulate a second copy with no build-time rule naming it. A new paragraph in Part B § "Extract on the third strike", between the rule-of-three sentence and the mirrors-admission paragraph, states the same two-copy bar for a permission check, an auth gate, or a domain rule that must stay in sync. Five tests scoped to the new paragraph, not the section — the existing rule-of-three sentence already contains the phrase "a permission check", so an unscoped guard would be green before this ticket's text existed. `code-quality` 0.18.0 → 0.19.0 (registry 0.5.89 → 0.5.90), minor.

### Fixed — closed without a further diff: the guard #228 asked for already shipped in #224 (#228)
- Steward-filed CODE-INSIGHT-3 (2026-07-26 eve, `assessments/2026-07-26-code-eve.md`) asked for a guard asserting `specs/features/verb-model.md` carries a section for every audited lifecycle verb. #224's own acceptance criteria named this ticket and shipped that guard the same day: `test_verb_model_spec_documents_every_audited_verb` (`tests/unit/test_feature_specs.py`), derived from `_AUDITED_VERBS` intersected against the registered CLI surface, with an anti-vacuity floor and a failure message naming the missing verb and the file — all five of this ticket's criteria. Re-verified here against `dev` at `5c04901`: the guard passes, `verify.sh` is green (2773 passed). Closed rather than re-implemented, per the operator's decision recorded on the ticket. No registry bump.

### Fixed — the registered-surface adoption lock's predicate matches its own rule (#225)
- Filed by `/assess code` (steward, 2026-07-26 eve, **CODE-2**, Low, report `assessments/2026-07-26-code-eve.md`). #222's adoption lock derives its subject set from every tracked test source, but its matching predicate — `_INLINE_SURFACE_READ = re.compile(r'\bapp\.registered_(?:commands|groups)\b')` — found no word boundary between `_` and `a` in `promote_app.`, so the lock could not see it. Three inline copies against the `promote` sub-app survived, invisible to the guard meant to catch a sixth one. The pattern broadens to `\b\w*app\.registered_(?:commands|groups)\b`, landed first and observed red naming exactly the two modules the three lines span; the sites then convert to `registered_command_surface(promote_app)`, with every assertion line byte-unchanged. Tests only, so no registry bump.

### Fixed — the SPEC enumeration lock guards the audited set, not only the surface (#226)
- Filed by `/assess code` (steward, 2026-07-26 eve, **CODE-INSIGHT-1**, `assessments/2026-07-26-code-eve.md`). `_is_subset_surface_enumeration` fired only on a slash-list naming an ops command *and* an audited verb, exempting one naming audited verbs alone — sound while that set was frozen at three, since a set that never changes cannot drift. ADR 0007 falsified the premise: #211 added `design` to `_AUDITED_VERBS` for *anchoring* without re-deriving the exemption, leaving the guard green over exactly the class it exists to catch. The predicate now covers two guarded sets under one rule, neither clause hardcoding a cardinality, so a fifth audited verb re-arms it with no edit. Widening it turned the live guard **red** against the real `SPEC.md:349` — the one prose line this change carries, and the evidence the blindness was real. A regression test injects that stale sentence into a live SPEC section and asserts *equality* with the single offender (non-vacuity); a §3 control proves the catch comes from the predicate, not from live-section scoping. Every clause mutation-checked. Tests plus one SPEC sentence — no registry bump.

### Added — code-quality: a guard's matching predicate obeys the same derive rule as its subject set (#227)
- Filed by `/assess code` (steward, 2026-07-26 eve, **CODE-INSIGHT-2**, `assessments/2026-07-26-code-eve.md`). #220's subsection governs only *which units are checked*, never *what counts as a hit*, so a guard can derive its subject set correctly and still narrow through a hand-written predicate — two did. A third paragraph extends the rule: every literal in a predicate (a variable name it anchors on, a separator it assumes, a shape it exempts) is derived from the same defining artifact or justified in the change spec against the rule's **full** surface, naming the units it excludes; the reviewer **rejects** a predicate narrower than its rule. Five tests scoped to the *paragraph*, not the subsection — `narrow`, `green`, `literal` and `reject` already live above it and would pass before it exists — with a content-based selector that dogfoods the rule. Every clause mutation-checked. `code-quality` 0.17.0 → 0.18.0 (registry 0.5.88 → 0.5.89), minor.

### Fixed — the four-verb lifecycle across the live canonical documents (#224)
- Filed by `/assess code` (steward, 2026-07-26 eve, **CODE-1**, Medium, report `assessments/2026-07-26-code-eve.md`). ADR 0007's `design` verb shipped into four live documents that still said three: every surface a guard covered stayed current, every unguarded prose surface went stale. `specs/features/verb-model.md` — the as-built record under `feature_specs: true` — did not merely miscount, it gave `design` no `### ` section at all while its three siblings each had one. Corrected there plus `SPEC.md`, `README.md`, and `specs/architecture-principles.md:17`; the historical `### 2026-06` changelog and dated decision blocks still say three, which is what a point-in-time record should say. New `test_verb_model_spec_documents_every_audited_verb` (#228) derives the verb set from `_AUDITED_VERBS` intersected against the registered surface — landed first, failed naming exactly `design`. No registry bump.

### Fixed — the between-release CHANGELOG fold covers the line ceiling, not just bytes (#223)
- `RELEASING.md`'s fold was written against the 60,000-byte gate alone, while `test_changelog_rotation.py` enforces two ceilings — and condensing bodies buys bytes and no lines, a folded entry still being heading + bullet + blank. Proven 2026-07-26: a four-entry fold cleared bytes, the next two entries tripped the 250-line ceiling at 251. The section now measures both (`wc -c` / `wc -l`), splits into a byte pass and the one-line collapse that relieves lines (`c907faf` cited beside `208118e`), and names entry length as the driver under a 1,000-byte budget — which this entry keeps. `test_root_changelog_is_line_bounded` stops advising the rotation the section forbids between releases. New `test_releasing_changelog_fold.py` imports the bounds and derives the ceiling-test set from the rotation module, so a bound bump fails the doc guard; every assertion mutation-checked. No registry bump.

### Fixed — one reader for the Typer app's registered command surface (#222)
- Filed by `/assess code` (steward, 2026-07-26 pm, **CODE-1**, Medium). Three test modules carried a byte-identical two-line union reading Typer's registered surface; new `tests/_cliutil.registered_command_surface` is the single definition, adopted by five sites (two the ticket's grep missed), locked by an adoption test enumerating `tracked_py_sources("tests")` so a sixth inline copy fails the gate. Six new unit tests. Tests only — no registry bump.

### Added — test-driven-development: cover a new lifecycle stage under every supported configuration (#221)
- RED gains a rule that a new lifecycle stage must extend every suite walking the lifecycle, not just its own unit suite. `test-driven-development` 0.5.0 → 0.6.0 (registry 0.5.87 → 0.5.88).

### Added — code-quality: a guard derives its subjects, it does not list them (#220)
- A guard enforcing a rule across a set of files/modules/keys must derive that set from its defining artifact, never a hardcoded literal. `code-quality` 0.16.1 → 0.17.0 (registry 0.5.86 → 0.5.87).

### Fixed — the CLI boundary guard derives its subject set from the registrations (#219)
- `_registered_command_modules` now `ast`-derives the boundary guard's subject set from `harness/cli/__init__.py`'s live registrations instead of a stale hand-written list. Test-module only — no registry bump.

### Added — the design stage is proven under `tracker: none` and at its tracker boundary (#218)
- `test_tracker_less_layer.py` gains a `design` case; `design_tracker.py` coverage 79% → 98%. App-only — no registry bump.

### Fixed — the design gate reads its payload keys from single-sourced constants (#217)
- `resolve_design_gate` reads via new `DESIGN_STATUS_KEY`/`DESIGN_HASH_KEY` constants instead of hardcoded literals. App-only — no registry bump.

### Fixed — tree-walking test guards enumerate from the tracked set, not the working tree (#215)
- Filed by `/assess code` (steward, 2026-07-25, **CODE-2**), sibling of #214: two abandoned worktrees nested inside `harness/` broke seven tests across three modules by making guards read stale copies as living. One shared helper, `tests._gitutil.tracked_py_sources`, projects the git-tracked set onto `*.py` — chosen over the ticket's `startswith(".")` filter, which misses a stray tree at a non-dot path. Four sites adopt it (one the ticket did not name); nine new tests in `test_gitutil.py`, including a four-way adoption lock. On a clean tree the scanned set is byte-identical (246 = 246).

### Fixed — `reclaim --stale` reads ledger liveness, not just the tracker's `updatedAt` (#216)
- Filed from an unattended Build tick's own pre-flight (2026-07-25): the sweep reclaimed a 60-minute-old run against the 90-minute threshold. On `tracker: github` the tracker timestamp is not a heartbeat — `start` writes the Projects-v2 Status field, an item-level mutation that never bumps the issue's `updatedAt` — so a live build past 90 minutes was reverted to Todo, re-picked and duplicated. Staleness now reads the newest of two clocks: `updatedAt` and, via new `_ledger_last_activity`, `max(runs.started_at, MAX(events.timestamp))` for the open run. Ordering is load-bearing: the ledger is consulted only for tickets the tracker already calls stale, so it can spare a live run but never condemn one (proposal D3 preserved, D2 amended). Eight new tests in `test_cli_reclaim.py`.

### Added — the four-verb lifecycle is documented across the guidance surfaces (#213)
- Breakdown item 4 of 4 of `specs/proposals/design-verb.md`, policy record ADR [`0007`](specs/decisions/0007-design-verb.md); it landed last, documenting a step items 1-3 had to make real first. `commands/harness.md` gains **Step 1.5 — `design`** and `--design-file` on `review`; `CONTEXT.md` moves to "Four verbs, one ledger, one gate"; `spec-authoring` records that the design stage is not a third tier dimension. One canonical lifecycle string is asserted from a single constant so the two surfaces cannot drift a second wording. **`harness` 0.2.4 → 0.2.5**, **`spec-authoring` 0.9.1 → 0.9.2** (registry **0.5.85 → 0.5.86**).

### Added — `review` enforces the design stage and reviews against the design (#212)
- `harness review` refuses a run with no recorded `design` event (exit 5, `reason=no_design`); a `status='failed'` attempt still satisfies it (D4). A `status='ok'` design reaches the engine via `--design-file`, authenticated by `design_hash`. 31 tests.
### Fixed — `resolve_repo_root` refuses a path that is not a git top-level (#214)
- Steward finding CODE-INSIGHT-1: any resolvable path inside the allowlist was accepted, so a verb one directory too deep silently planted its worktree there. Now also requires a git top-level (`NotAGitTopLevel`, exit 2). Five test modules' fixtures moved to shared `tests/_gitutil.init_repo`.
### Added — the `harness design` verb: engine, ticket comment, ledger event (#211)
- Breakdown item 2 of 4 of `specs/proposals/design-verb.md` (ADR [`0007`](specs/decisions/0007-design-verb.md)). New `harness/cli/design.py` registers the fourth lifecycle verb `harness design [--run-id] [--model]` between `start` and implement, recording the outcome in three places — a marked ticket comment (`harness/design_marker.py`), a new `design` ledger event (`DesignEventData`), and stdout as `DesignOutput`. Degrade and record (**D4**): all five failure reasons append a `failed` event, post no comment, and exit 3. Tracker I/O split to `design_tracker.py`; the bounded engine subprocess driver extracted to `harness/cli/_engine.py`, shared with `review` rather than copied. 34 tests.

### Added — the design engine protocol: prompt, SUBMIT contract, Opus default (#210)
- Breakdown item 1 of 4 of `specs/proposals/design-verb.md` (ADR [`0007`](specs/decisions/0007-design-verb.md)). New `harness/cli/design_protocol.py`: the read-only design prompt, the `SUBMIT` contract, and `DESIGN_MODEL_DEFAULT = "opus"`. `parse_design_submit` distinguishes three outcomes — the design, never-reached-the-contract, and malformed — kept separate from `review_protocol.py` because the payload fields and failure semantics differ. Pure protocol module, inert until the verb consumes it.

### Added — review-discipline: extend the sibling-duplication check to backend module files (#209)
- Filed by nano-erp's `/assess code` (CODE-INSIGHT-2). New Stage 2 bullet **Cloned backend module helper**, extending the frontend-only sibling-duplication check to backend modules. `review-discipline` 0.6.7 → 0.6.8 (registry 0.5.84 → 0.5.85).

### Added — review-discipline: partial-hook-adoption check also catches skipping the hook entirely (#208)
- Filed by nano-erp's `/assess code` (CODE-INSIGHT-1). #194's rule only fired on partial adoption; now also triggers on the diff *shape* (fetch/write-refetch, hand-rolled `useState` flow) to catch full non-adoption too. `review-discipline` 0.6.6 → 0.6.7 (registry 0.5.83 → 0.5.84).

### Changed — code-quality: broaden the mirroring self-admission trigger from helper to any duplicated unit (#206)
- From the form repo, CAL-1214 (`/assess code`, CODE-INSIGHT-1). `code-quality`'s "Extract on the third strike" admission-comment rule was worded around "a helper mirrors a sibling", which reads as scoped to pure functions — so three UI components each admitting in a doc comment that they mirror the previous one never pulled the trigger across three separate ticket reviews. The trigger's subject broadens to "a helper, component, or module", explicitly covering a duplicated rendering/structural shell. This entry also folded #185–#181. **`code-quality` 0.16.0 → 0.16.1** (registry **0.5.82 → 0.5.83**).

### Added — ship the guidance-feedback-upstream rule (#205)
- Breakdown item 1 of `specs/proposals/guidance-feedback-upstream.md` (accepted 2026-07-20), whose tracking ticket was diverted into an unrelated fix and lost in the Linear→GitHub cutover, leaving the doc edit unshipped. `process/harness.md`'s "Updating the guidance" section (mirrored byte-identical into `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`) gains the rule: on a guidance defect, friction, or idea, search existing issues, then draft a GitHub issue against the `source.repo` resolved from `.guidance-lock.yaml` — never hardcoded, never sent unattended, never carrying the consumer's proprietary code. Review FAIL cycle 1 caught a missing CHANGELOG entry (#202 precedent).

### Added — code-quality / review-discipline: a placeholder/stub must be flag-gated, not reachable from a live CTA (#204)
- From the form repo, CAL-1130 (`/assess code`, CODE-INSIGHT-1). `code-quality` Part A gains **Placeholder and stub gating**, mirrored in `review-discipline` Stage 2.

### Added — test-driven-development: cover each of a guard's trigger conditions, not just the one that trips first (#203)
- From a steward pass: RED gains a bullet requiring one test per independent trigger condition, not just the one that trips first.

### Added — wire `/bug` and `/tweak` into the process docs + command table (#202)
- Breakdown item 4 of `specs/proposals/bug-and-tweak-capture-commands.md`, landing last so the docs describe what shipped: `spec-driven-development` and `spec-authoring` name the capture on-ramp, and `process/harness.md`'s Commands table (mirrored into `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`) gains `/bug` + `/tweak` rows and one sentence stating the three-way boundary — `/propose` decides the unconfirmed, `/bug`/`/tweak` capture the confirmed-small, `/start` picks up the filed. **`process-harness` 0.4.8, `spec-driven-development` 0.5.1, `spec-authoring` 0.9.1** (registry **0.5.79**).

### Added — `commands/bug.md`: files a bug straight to Todo (#200)
- Breakdown item 2: new `commands/bug.md`, a thin capture command filling the shared template with `kind: bug` and filing straight to Todo with no escape hatch (a bug's fix direction is never in doubt — contrast `/tweak`, #201). Documents both tracker backends, including the three-step `gh issue create` → `item-add` → `item-edit --single-select-option-id` that explicitly sets Status=Todo, closing the item-add-no-status trap (tick #90) where a filed item is invisible to `work-discovery`. **New `bug` 0.1.0** (registry **0.5.76 → 0.5.77**).

### Added — new `templates/adjustment.md`: the shared capture template for `/bug` and `/tweak` (#199)
- Breakdown item 1 of `specs/proposals/bug-and-tweak-capture-commands.md`: the capture front door had nowhere lightweight to land. New `templates/adjustment.md` — `kind: bug | tweak` / `area` frontmatter, *As-built (observed)* / *Desired* / *From actual use* / *Acceptance criteria* with per-kind framing, and a `tweak`-only escape hatch to `/propose`. Framed as a capture-optimized change spec extended by `/start`, not a competing artifact. **New `template-adjustment` 0.1.0** (registry **0.5.76**).

### Added — `review-discipline`: CONTEXT.md currency bullet also covers a repo's release runbook (#198)
- A tracker cutover or branch-topology amendment could update `CONTEXT.md` correctly while leaving a sibling release runbook silently describing the old world — what happened at the Linear→GitHub cutover and the dev→staging→main amendment (see #196). `review-discipline`'s CONTEXT.md currency bullet now also fires on a diff changing `tracker:` or `branches:` roles, phrased generically (no filename hardcoded, since it ships to every consuming repo and a literal cite would trip the app-only-cite guard). **`review-discipline` 0.6.4 → 0.6.5** (registry **0.5.74 → 0.5.75**).

### Earlier unreleased changes

> The entries below are folded to one-line summaries to keep this file under its 60,000-byte size gate between releases (CAL-1182). This is the *condense* fix, chosen over forcing a `dev → main` release: the release stays a deliberate, separately-gated act (`main` is PR-only per CAL-1029; the promotion lifecycle is ADR 0003), not a side effect of a headroom fix. Full detail is in git history, and each entry rotates to [`CHANGELOG-archive/2026.md`](CHANGELOG-archive/2026.md) at the next release.

### Added — `/promote`: a versioned command over the harness promotion verbs (#189)
- `commands/promote.md` transcribes ADR 0003's five promotion verbs as a universal command resolving `<src>`/`<dst>` against `CONTEXT.md` `branches:` roles.

### Added — `/promote`: agent-orchestrated fallback for repos without the harness app (#190)
- A `## Fallback: no harness app` section, deliberately reduced per ADR 0003's 2026-07-23 amendment (conflict/red-gate → stop, no repair attempt).

### Added — `harness defer --needs` gains a third hold kind, `input` (#191)
- Per ADR 0006: `decision`/`operator` did not partition the hold space, so `input` covers a ticket waiting on the operator to supply something.

### Added — `work-discovery` gains the return path: when a held ticket is clearable and what released means (#192)
- The inbound half of the hold contract, so `/decision` (#193) has a single-homed definition to delegate to.

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

### Earlier still — one line each

> A further condensation of the oldest `[Unreleased]` entries, applying the `RELEASING.md` fold a second time: heading and summary collapse onto one line so the file clears its **line** ceiling as well as its byte ceiling. Full detail is in git history; each entry rotates to [`CHANGELOG-archive/2026.md`](CHANGELOG-archive/2026.md) at the next release.

- **Added — a GitHub Projects v2 tracker backend behind the seam (CAL-1105)** — `harness/github.py`'s `GitHubClient` implements `Tracker` over GitHub Issues + a Projects v2 `Status` single-select field (resolved by name), superseding the `UnsupportedTrackerError` …
- **Added — host the repo-guide page on GitHub Pages + link from README (CAL-1201)** — `docs/index.html` gains Open-Graph/Twitter meta tags, a favicon, and share assets …
- **Added — a self-contained repo-guide landing page at `docs/index.html` (CAL-1200)** — `four-loops.html` grew into `docs/index.html`: the Four Loops model, a harness-verbs section, and a guidance catalogue, each `data-guidance="<id>"` resolving in `registry.yaml`.
- **Fixed — GitHub detects the licence as AGPL-3.0 (CAL-1198)** — `LICENSE` restored to byte-exact AGPL-3.0 text (a prepended note had diluted it below licensee's 98% threshold) …
- **Changed — verbs obtain their tracker through a seam factory (CAL-1197)** — Every verb now obtains its tracker via `tracker_client(repo_root)` (a `@runtime_checkable Tracker` protocol) instead of constructing `LinearClient` directly — the seam a second backend …
- **Changed — `close` merges in a throwaway worktree, not the main checkout (CAL-1154)** — `close`'s merge/push moved into a detached `.worktrees/harness/<run_id>-close` worktree off `origin/<base>` …
- **Added — `doctor` flags a drifted `~/bin/harness` wrapper (CAL-1149)** — New `check_wrapper` compares the host-side `~/bin/harness` against the versioned `docker/harness-wrapper.sh`, surfacing symlink/copy/drifted/detached via `HARNESS_WRAPPER_STATUS`.
- **Changed — CI runs on `dev`, not only `main` (CAL-1030)** — `.github/workflows/ci.yml` now triggers on `[main, dev]`, so `close`'s direct pushes to `dev` are verified at merge time instead of waiting for the release PR.
- **Changed — `code-quality` Part A: an extraction sweeps for its copies (CAL-1172)** — Part A gains *An extraction sweeps for its copies*: grep the whole tree post-extraction …
- **Changed — the feature template demands a production call site per exported entry (CAL-1171)** — `templates/feature.md` requires a named production caller per exported interface entry …
- **Fixed — `checkpoint` re-pushes a rebased run branch (force-with-lease) (CAL-1162)** — `harness checkpoint` pushes with `--force-with-lease` so a rebase-before-close no longer silently reverts durability to the pre-rebase commit …
- **Changed — `/assess` findings file to Todo, with a widened autoMode clause (CAL-1168)** — `/assess` step 2 now files findings/insights to **Todo** (was ad hoc) with severity-mapped priority …
- **Added — `harness defer v2`: `--needs`, assign-on-defer, approved autoMode clause (CAL-1167)** — `harness defer` gains `--needs decision|operator` and assigns the ticket to the operator (`LinearClient.assign_to_viewer`) as the machine-readable hold signal.
- **Changed — `work-discovery` skips on assignment, defers with assignment (CAL-1166)** — The skip rule keys on assignment to a human (any state, with a transitional label OR) …
- **Changed — ticket protocol codified in the `linear` skill (CAL-1165)** — Todo/Backlog filing rules, assignment-as-hold-signal, and the `operator` label documented …
- **Fixed — a promotion gate whose toolchain can't run is `blocked`, not a false code ticket (CAL-1160)** — New `GATE_UNRUNNABLE_EXIT` (97) maps to `blocked` via `classify_gate_failure`, closing the unreachable `exit_code is None` path that used to file a false `needs_ticket`.
- **Fixed — `promote` gates host-side, so the promotion success path is reachable (CAL-1159)** — `promote start`/`continue` gain `--gate-exit`/`--gate-log` (mirroring `review`) and classify host-supplied evidence instead of running the gate inside the toolchain-less container …
- **Changed — the tracker switch collapses to a single `tracker:` field (CAL-1164)** — `tracker: linear | github | none` replaces the derivable `layers.linear` boolean as the single on/off-plus-backend fact …
- **Added — a distributed reference for the mechanical size-marker guard (CAL-1156)** — New `templates/size-guard.md` ships a repo-editable `# size: <reason>` walker for consuming repos, execute-verified against fixtures.
- **Fixed — the wrapper is shellcheck-clean, and its guard no longer skips silently (CAL-1150)** — Fixed a latent SC2046 in `docker/harness-wrapper.sh` (the `-it` flags were built with an unquoted command substitution) by assembling them in a `TTY_ARGS` array …
- **Fixed — the image-freshness guard no longer disables itself silently on a detached copy (CAL-1153)** — The CAL-1144 image-freshness guard silently no-op'd on a wrapper copied outside any checkout (the real `~/bin/harness` install), disabling it in exactly the deployment it protects …
- **Added — tests own the state they mutate (CAL-1161)** — New `engineering-principles` principle (**0.3.0 → 0.4.0**, registry **0.5.48 → 0.5.49**): a suite provisions its own instance and disposes it at teardown, never borrowing state that …
- **Changed — the staging hop direct-pushes on a green gate; the no-auto-merge rule scopes to the release hop (CAL-1158)** — The ADR-0003 no-auto-merge rule now scopes to the *release* hop only: the nightly `dev → staging` hop direct-pushes the gated SHA (`DIRECT_PUSH_TARGET` allowlist = `staging` alone, refusing …
- **Fixed — drop the stale org gloss on the Linear team prefix** — Deleted the stale `Calibrate-coffee (CAL)` gloss on `CONTEXT.md`'s `linear: CAL` team key (also in `specs/infrastructure.md` and two `tests/` fixture copies) — the key is opaque and the …
- **Fixed — the private-surface guard was blind to the workspace's former slug (CAL-1029)** — `test_no_private_surfaces` knew only the *current* workspace slug, leaving 24 former-slug `linear.app` URLs standing across four `specs/` files …
- **Fixed — `close` no longer merges into a base checkout it has not checked, and never hides a failed cleanup (CAL-1151)** — `close` was mutating the base checkout without validating it …
- **Fixed — the wrapper rebuilds a stale `harness:dev` instead of silently running it (CAL-1144)** — Nothing rebuilt the `harness:dev` image after a merge, so an unattended tick could silently run an old verb …
- **Added — the advisory `/assess` report commit is sanctioned; `gh pr merge` is denied (CAL-1140)** — `settings/harness.json` **0.5.0 → 0.6.0**: a seventh `autoMode.allow` clause sanctions the unattended `/assess` report commit to `dev` (bounded to `assessments/`), and `Bash(gh pr merge *)` …
- **Added — `harness/cli/close.py` is armed on the architecture watchlist (CAL-1139)** — Armed `harness/cli/close.py` on the `CONTEXT.md` architecture watchlist (gate + ledger + git concerns accreting in one module) …
- **Added — the OpenCode + MLX local orchestrator spike (CAL-1134)** — Recorded the OpenCode + MLX local-orchestrator stack for driving nightly promotion cheaply in `specs/local-orchestrator-stack.md` (marked a hypothesis — nothing is installed here), guarded …
- **Added — `harness defer` verb: the triage write as an audited verb (CAL-1143)** — New `harness defer <TICKET> --reason <text>` verb: triage was the one lifecycle write the routine hand-rolled as raw GraphQL …
- **Fixed — the release-facing docs describe what actually shipped (CAL-1111)** — The README changelog was an era behind and `RELEASING.md`'s checklist named a roadmap table neither file ever had …
- **Added — `harness promote start` / `continue` worktree + merge mechanics (CAL-1115)** — Filled the `promote start` / `continue` write-path openers on a new `harness/promotion.py`: worktree + `--no-ff` merge from the target, conflict classification (`agent_may_fix` vs …
- **Changed — the `~/bin/harness` wrapper is a versioned file, not a README heredoc (CAL-1123)** — Promoted the wrapper from a README heredoc to a real versioned `docker/harness-wrapper.sh` (mode 755, `bash -n`-clean), recommended to be symlinked onto `PATH` so fixes propagate on `git …
- **Added — `code-quality` names a narrowing's worklist as the transitive consumers of the field (CAL-1100)** — `code-quality` **0.8.0 → 0.9.0**: a narrowing at a boundary is a whole-call-graph change — the worklist is every transitive consumer of the field, not the callsites a coercion-operator grep …
- **Added — `spec-authoring` requires a scope-claim invariant to cite its enumeration or be recorded as a finding (CAL-1101)** — `spec-authoring` **0.6.0 → 0.7.0**: any scope claim ("the only consumer", "exactly one home") must cite the enumeration that establishes it, or a second consumer is a finding, not an …
- **Fixed — `doctor` probes that the review engine can actually run, not just that it is on PATH (CAL-1083)** — `doctor`'s reviewer check now runs a `--version` liveness probe per engine (`absent` / `cannot_run` / `ok`) instead of a PATH-only `which`, so an on-PATH-but-unrunnable engine FAILs …
- **Fixed — the wrapper joins group 0 so the non-root container can reach the forwarded ssh-agent socket (CAL-1122)** — `close`/`checkpoint` SSH pushes failed because the non-root (`USER harness`) container couldn't reach Docker Desktop's root-owned forwarded ssh-agent socket …
- **Added — the verbs run tracker-less under `layers.linear: false` (CAL-1104)** — The verbs now run tracker-less under `layers.linear: false` (previously hard-required Linear despite the advertised switch): new `harness/layers.py` reads the block-scoped key, `start` …
- **Fixed — redact workspace URLs leaked into a public proposal** — Redacted nine full `linear.app/<workspace>` URLs leaked into `specs/proposals/local-promotion-steward.md` to the bare `CAL-xxxx` ids — `test_no_private_surfaces` had been red on `dev` (CI …
- **Added — `review` requires recorded verify-gate evidence (CAL-1082)** — `review --gate-exit <code> [--gate-log <path>]` now records verify-gate evidence bound to `reviewed_sha` (green → the engine runs and the event carries …
