# ADR 0016 — Tests own structure and negative space; the reviewer owns meaning

- **Status:** Accepted
- **Date:** 2026-08-16
- **Source:** #459, ratified by the operator in-session (2026-08-16)
- **Relates to:** [ADR 0015](0015-harness-v4-thin-verification-layer.md) — the runtime it retired is what made this guard suite the repo's whole recurring cost.

## Context

ADR 0015 deleted the runtime. What remains is a guidance surface, a gate, and `tests/unit/` — and the guards are now, by a wide margin, the largest thing in the repo that a change has to satisfy. Measured on `5194fb3` (2026-08-16):

- **137 guard modules, 1,162 test functions, 1,863 collected tests, 35,537 lines.**
- **26 modules (675 tests) exercise executable behaviour** — node-spawned hooks, `scripts/` exercisers, the mutation instrument. That part is strong, and this decision does not touch it.
- The remaining **111 modules are prose-readers**: they read the published guidance and assert something about its text.

The prose-readers are two generations coexisting. The newer house style — derived corpora, positional predicates, synthetic controls, did-not-delete floors, negative-token sweeps (`test_v4_teardown`, `test_final_evidence_ordering`, the distributed-prose family) — works and ages well. The older generation pins sentences, and it is the recurring tax:

- **170 containment assertions pin a string literal of 20 characters or more** into prose, across 72 modules (AST count of `"literal" in text`; pins held in a tuple that a loop iterates are counted by neither this rule nor the ticket's, so both are lower bounds). Each breaks on a benign rewording, while verifying bytes rather than meaning.
- **Meaning-vacuous co-occurrence guards.** `test_review_discipline_current_criteria` passes if the rule it guards is *inverted* — term co-occurrence has no polarity. `test_simplicity_ladder` asserts `f"{n}." in section` for 1..6 plus a handful of common words, which a gutted ladder satisfies. `test_guidance_efficiency_tracker` asserts `len(corpus) >= 5` over a hardcoded five-element tuple — a constant asserting on itself.
- **Museum guards** pinned to frozen historical records nobody edits, where regression probability is approximately zero and the maintenance surface is permanent.
- **Fan-in.** `registry.yaml` is parsed by 48 modules, `CONTEXT.md` by 35, `review-discipline` by roughly 12. A substantive rewrite of a core skill must appease a dozen independent modules.

The operator's judgement, from the full-system review that produced #459: the literal-pin class is the most egregious finding of that review. The repo removed its runtime overhead and the guard suite became the new recurring tax on exactly the editing the guidance needs.

## Decision

**Tests assert what prose must NOT contain and what must structurally correspond. Whether prose affirmatively SAYS the right thing is the review gate's job.**

The reasoning is one observation: **no regex reads meaning.** A positive-meaning pin is therefore brittle and vacuous *at the same time* — it fails on a rewording that preserves the rule exactly, and it passes on an edit that satisfies the pinned bytes while inverting the rule in the next paragraph. That combination is the worst available, because it charges a recurring cost for assurance it does not provide.

Two classes of guard are exempt from the observation, and both stay:

- **Negative space** — what the prose must not contain: retired vocabulary, forbidden identifiers, cites into app-only paths, a deleted subsystem's names. A sweep with zero legitimate membership never has to judge meaning; it only has to find the token.
- **Structural correspondence** — what must match what: byte-identical mirrors, a version and its registry entry, a generated artifact and its source, the guidance topology, the licence boundary, the landing page and its tokens. These compare two things in the tree to each other, and neither operand is an opinion.

Where a rule is load-bearing enough to deserve a tripwire, the minimal form is: **the section exists in its canonical home, plus at most a small term set the rule cannot be stated without, plus the negation token inside the match window where the rule has a polarity.** One tripwire per rule-home, not per sentence. The polarity clause is the specific fix for the inversion-passes class.

**The marginal assurance of a sentence pin over "reviewer plus a membership tripwire on the section" is near zero, while its cost recurs on every edit.** The reviewer is the only instrument in the loop that reads semantics, and it already sees every change.

### The rule applies to itself

The first guard written under this ticket was a sweep asserting that no guard's prose cites a `test_*.py` module absent from the git index. It found eight live citations where the ticket's author had found three by hand, which is the usual argument for mechanizing a check.

It was deleted before it shipped. The sweep cannot distinguish a **stale pointer** ("the generic guard already exists in *X*", where *X* is gone) from **accurate history** ("this assertion lived in *X* until #435 deleted that module"). The difference is tense and framing — pure meaning. Separating them needs an exemption list, and an exemption list inside a zero-membership sweep is opt-out prose rather than a guard. So the eight citations were triaged by reading them: five stale pointers repaired, three historical narratives left alone, and no guard added.

That is the decision working as intended rather than an exception to it, and it is recorded here because the temptation it resisted is the one that built the corpus this ADR is pruning.

## Consequences

- **Accepted:** a rule can be silently reworded into a weaker rule without a test failing. That was already true — a co-occurrence guard passes on inversion — and it is now honest about who catches it.
- **Accepted:** the review gate carries more. It already read every diff; what changes is that its reading is the *primary* check on guidance meaning rather than a second opinion behind a regex.
- **Gained:** the guidance becomes editable again. The prose this repo publishes is its product, and a corpus that charges a dozen module edits for one paragraph rewrite selects against improving it.
- **Gained:** guards that stay are ones that age indefinitely. Nothing in the keep set has to be revisited when a sentence changes.
- **Reversal:** cheap for any individual rule — a tripwire can be tightened back into a pin at any time. What would be expensive to reverse is the deletion set, which is why the triage below is a record rather than a commit message.

The rule's home in the installed surface is `skills/code-quality/SKILL.md` Part C, *A guard over prose owns structure and negative space, never meaning*, pointed at from `CONTRIBUTING.md`'s mutation section so it is read before the guard is written rather than after.

## The triage

Every one of the 137 guard modules tracked at `5194fb3`, bucketed with its reason. The table is the record that the deletions and collapses below it were decided module by module rather than swept.

**Keep 66 · Convert 66 · Delete 5.** "Convert" means the module survives with its identity, negative-space and behaviour tests intact and its sentence-pins collapsed to one tripwire per rule-home — most of the reduction in collected tests comes from this bucket, not from deletion.

The invariant the triage is measured against: **the 26 behaviour modules and their 675 test node ids are untouched.** They are the only tests in `tests/unit/` that execute code rather than read text, and no bucket above may move one.

| Module | Bucket | Reason |
|---|---|---|
| `test_adjustment_template.py` | **CONVERT** | Header/registry parity and section structure stay; the As-built framing and on-ramp sentence-pins collapse to one tripwire. |
| `test_adr_0004_amendment.py` | **DELETE** | Museum guard over a dated, closed amendment block (two commits ever) by polarity-free co-occurrence. |
| `test_architecture_watchlist.py` | **CONVERT** | Canonical-home and repo-path sweeps stay; eight section term pins and three self-asserting smoke tests go. |
| `test_assess_architecture_scope.py` | **CONVERT** | Parity, rubric exclusivity and the scope-absence check stay; seven prose pins and two self-asserting smoke tests go. |
| `test_assess_filing_placement.py` | **CONVERT** | Three co-occurrence checks over one step body; the step's `not Backlog` polarity is never read, so an inversion passes. |
| `test_assessments_retention.py` | **KEEP** | Structural correspondence over LOG.md, derived via tracked_files_under. |
| `test_assurance_filing_rubric.py` | **CONVERT** | Near-minimal already; only the test asserting on the module's own hardcoded level tuple goes. |
| `test_assurance_filing_surfaces.py` | **KEEP** | Derived corpus, parity sweep and discrimination controls; sole home of shared filing helpers. |
| `test_bootstrap_onboarding_naming.py` | **KEEP** | Negative space plus header/id/registry/hook-META correspondence. |
| `test_bootstrap_windows_links.py` | **KEEP** | Derivation guard — the link set is derived from step 3's own declarations. |
| `test_bug_command.py` | **KEEP** | Version parity, structural cross-reference and two negative sweeps. |
| `test_build_command_bodies.py` | **KEEP** | Negative space over executable content plus literal shell-invocation identity. |
| `test_build_command_consolidated.py` | **CONVERT** | Retirement sweeps and sandbox-flag checks stay; the fallback co-occurrence and a frozen version floor go. |
| `test_build_design_tokens.py` | **KEEP** | Behavior — imports and drives scripts/build_design_tokens.py. |
| `test_build_thin_driver.py` | **CONVERT** | One test is a strict subset of a tree-wide sweep; the command-table rows are live correspondence. |
| `test_capture_on_ramp_wired.py` | **CONVERT** | Five of ten are re-checks stronger guards already own; the command-table rows are the surviving claim. |
| `test_ci_workflow_full_history.py` | **KEEP** | Derived identity over YAML with a non-vacuity floor. |
| `test_ci_workflow_permissions.py` | **KEEP** | Negative space over workflow permissions with a non-vacuity floor. |
| `test_ci_workflow_triggers.py` | **KEEP** | Parses ci.yml's `on:` block and pins the branch list — config identity. |
| `test_code_quality_duplication_threshold.py` | **CONVERT** | Four sentence-pins over one rule-home, one a verbatim re-assertion of another. |
| `test_code_quality_generated_artifact_verbatim.py` | **CONVERT** | Eight phrase anchors across three sentences of one subsection; collapses onto its existing `never re-derive` polarity. |
| `test_code_quality_guard_derives_subjects.py` | **CONVERT** | Eight prose predicates over one subsection — one rule-home, nine tests. |
| `test_code_quality_linter_first_size_enforcement.py` | **CONVERT** | Three functions co-occurrence-test one section with no polarity. |
| `test_code_quality_marker_presence_mechanized.py` | **DELETE** | Unanchored co-occurrence to EOF with no polarity; its live half is superseded in the same section. |
| `test_code_quality_narrowing_worklist.py` | **CONVERT** | Two of three tests pin a term set into one heading with no polarity read; the universality sweep survives. |
| `test_code_quality_owning_layer_aggregate.py` | **CONVERT** | The stack-leak ban stays; a term-set pin and a placement pin over one section collapse. |
| `test_code_quality_security_contract_predicate.py` | **CONVERT** | Two of four assert the identical literal heading; the rest pin terms whose polarity is in that heading. |
| `test_code_quality_size_justification.py` | **CONVERT** | AC-2 is a strict subset of AC-1; the marker name survives as one section-anchored tripwire. |
| `test_code_quality_size_limit_response.py` | **CONVERT** | Three sentence-pins over one answer paragraph; `never answered` is the only load-bearing anchor. |
| `test_code_quality_sync_critical_second_copy.py` | **CONVERT** | Paragraph-index ordering pin plus a verbatim re-check, all over one paragraph. |
| `test_codex_native_guidance.py` | **KEEP** | Generated-artifact identity — runs the generator's --check and derives the expected set. |
| `test_community_docs.py` | **CONVERT** | Tracked-file existence and link correspondence stay; three prose pins collapse to two tripwires. |
| `test_context_template_tracker_fields.py` | **KEEP** | Config-template structure and intra-file coupling; one weak word pin is not worth trading four structural checks for. |
| `test_decision_storage_strategy.py` | **CONVERT** | Ten functions are exemplary negative space and stay; one exact-phrase regex collapses. |
| `test_declarative_ceiling_mechanized.py` | **CONVERT** | Four term pins over one paragraph plus an ordinal — one rule-home. |
| `test_design_system_composition.py` | **CONVERT** | Two sentence-pins over one section — one tripwire per rule-home, not two. |
| `test_design_system_fallback.py` | **CONVERT** | Five sentence-pins over the two-stage-lookup section; the scaffold-vocabulary sweep and its teeth test stay. |
| `test_design_system_layer.py` | **KEEP** | Topology and exact set equality between tokens.json and the rendered :root block. |
| `test_design_system_template.py` | **CONVERT** | Parity, layer-order derivation and the token sweep stay; five content pins and a re-implemented control go. |
| `test_distributed_prose_app_cites.py` | **KEEP** | Negative-space app-path sweep with the boundary parsed from the recorded source. |
| `test_distributed_prose_no_repo_ids.py` | **KEEP** | Negative-space sweep whose detector is parsed from the live hook, plus a real node run of it. |
| `test_distributed_skill_cites.py` | **KEEP** | Reference-resolution sweep against the git-tracked set with boundary cases. |
| `test_docs_consistency.py` | **KEEP** | Pure negative space plus a CONTEXT.md/verify.sh correspondence. |
| `test_extraction_sweep_spec.py` | **CONVERT** | Exact-sentence pins plus a placement re-check over one rule with a built-in negation. |
| `test_feature_specs.py` | **KEEP** | Tracked-file presence, frontmatter keys, `last_updated` read against git log, link resolution. |
| `test_feature_template_call_site.py` | **CONVERT** | Five literal phrase pins over one `## Interface surface` section. |
| `test_fetch_untrusted_urls_checklist.py` | **CONVERT** | Seven functions co-occurrence-test one section; an inverted checklist passes. |
| `test_filing_prevention_rules.py` | **KEEP** | The reference implementation of the target form — anchored term sets, negation windows, exclusivity. |
| `test_final_evidence_ordering.py` | **CONVERT** | Eleven of thirteen tests are sweeps, controls and positional offsets and stay; only the two home pins merge. |
| `test_fixture_git_init_declares_its_branch.py` | **KEEP** | AST guard over tracked sources with its own positive and negative controls. |
| `test_force_push_denylist.py` | **KEEP** | Replays the host's glob semantics over the settings deny list — an executable predicate. |
| `test_gate_evidence_hook.py` | **KEEP** | Behavior — runs the Stop hook as a node subprocess; sole home of REAL_STOP_PAYLOAD. |
| `test_gate_evidence_hook_scope.py` | **KEEP** | Behavior — real worktrees and the Stop hook run through node. |
| `test_gate_marker.py` | **KEEP** | Behavior — imports scripts/gate_marker.py, spawns git, builds worktrees. |
| `test_gate_marker_contract.py` | **KEEP** | Behavior — requires both node hooks and executes gate_marker.py in real repos. |
| `test_git_push_guard_hook.py` | **KEEP** | Behavior — executes the hook as a node subprocess and introspects its exported denylists. |
| `test_gitutil.py` | **KEEP** | Behavior — drives the shared git helpers against throw-away repos. |
| `test_grounding_step.py` | **CONVERT** | Frontmatter, registry and heading checks stay; four prose checks collapse to one tripwire. |
| `test_guidance_efficiency_topology.py` | **KEEP** | The named topology guard — byte budget, reference-tree parity, no-nesting. |
| `test_guidance_efficiency_tracker.py` | **CONVERT** | The Linear sweep is real negative space but is floored by `len(corpus) >= 5` over a hardcoded 5-tuple. |
| `test_guidance_feedback_upstream.py` | **CONVERT** | Mirror and parity tests stay; seven element pins collapse and a frozen version bump goes. |
| `test_guidance_footprint.py` | **KEEP** | The app/surface boundary guard, each form with a synthetic positive control. |
| `test_guidance_github_source.py` | **KEEP** | Registry source/self-version parity and lock-schema shape — config identity. |
| `test_guidance_source.py` | **KEEP** | Tracked presence, registry parity and six node-subprocess hook cases; its prose tests assert absence. |
| `test_hooks_fail_open_is_loud.py` | **KEEP** | Behavior — runs each hook and asserts on stderr, stdout and exit status. |
| `test_hooks_module_type.py` | **KEEP** | Behavior — executes every hook through node in an ESM fixture repo. |
| `test_hooks_no_empty_catch.py` | **KEEP** | Negative-space code scan whose control exercises the real predicate. |
| `test_landing_page.py` | **KEEP** | Artifact identity and drift — markers, stale-claim absence, page ids against the registry. |
| `test_landing_page_drift_guard.py` | **KEEP** | Behavior — imports and subprocesses the landing-page checker with an anti-vacuity case. |
| `test_landing_page_hosting.py` | **KEEP** | Structural and asset identity — meta extraction, PNG magic bytes, og:url/README equality. |
| `test_license_boundary.py` | **KEEP** | The licence boundary — SHA-pinned LICENSE and scope correspondence in both directions. |
| `test_lifecycle_sweep_spec.py` | **CONVERT** | Four pins over one rule in one section, the fourth a placement re-check the slicer performs. |
| `test_linear_skill.py` | **CONVERT** | Rename identity and the GraphQL embed sweep stay; six term co-occurrences over two skills collapse to two tripwires. |
| `test_mirroring_trigger_broadened.py` | **CONVERT** | Regex-pins a literal sentence for a two-word breadth claim; merges into the third-strike tripwire. |
| `test_mirrors_admission_third_strike.py` | **CONVERT** | Two rule-homes, five functions of unanchored term co-occurrence between them. |
| `test_mode2_migration_documented.py` | **CONVERT** | Five exact-phrase pins across two live migrator docs; the subject survives, so it converts. |
| `test_mutate.py` | **KEEP** | Behavior — drives mutate.py's decision layer through the injected Runner seam. |
| `test_mutate_docs_currency.py` | **KEEP** | Derives every doc obligation from the imported mutate.py, each with a floor. |
| `test_mutate_end_to_end.py` | **KEEP** | Behavior — runs the real mutate.py against synthetic projects. |
| `test_mutate_json_report.py` | **KEEP** | Behavior — drives mutate.json_report over real values, including a planted-secret measurement. |
| `test_mutate_liveness.py` | **KEEP** | Behavior — drives survivor classification through the stubbed Observer seam. |
| `test_nightly_promotion_workflow.py` | **KEEP** | Structural pin of the step's run value against the script, plus workflow-scoped bans. |
| `test_no_private_surfaces.py` | **KEEP** | Negative-space sweep over the committed tree for workspace URLs and personal paths. |
| `test_no_tasks_layer.py` | **CONVERT** | Absence and registry identity stay; one file-wide four-common-word co-occurrence goes. |
| `test_no_tracked_environment_symlinks.py` | **KEEP** | Tracked-tree identity plus a real `git add -A` in a throwaway repo. |
| `test_optional_project_scope_guidance.py` | **CONVERT** | Tracker-neutrality ban and parity stay; a whole-file co-occurrence and a duplicate go. |
| `test_over_engineering_lens.py` | **CONVERT** | Exclusive-home checks stay; three lens-body pins go and the `"not" in block` polarity is decoration. |
| `test_placeholder_stub_gating.py` | **CONVERT** | Two parity tests stay; four prose pins reduce to two tripwires, one per rule-home. |
| `test_process_doc_mirrors.py` | **KEEP** | The byte-identity mirror rule, with positive and negative controls on its predicate. |
| `test_promotion_routine_docs.py` | **CONVERT** | Its derivations died with ADR 0015; eleven sentence-pins remain, including a literal date. |
| `test_promotion_step_script.py` | **KEEP** | Behavior — executes promotion-step.sh against a stubbed git and a fake gate. |
| `test_push_target_guard_hook.py` | **KEEP** | Behavior — runs the push guard as a node subprocess over real repos and markers. |
| `test_rebase_stable_certification_record.py` | **DELETE** | Museum guard: eight assertions pinning a `status: shipped` proposal with one commit in its history. |
| `test_registry_layer_gating_note.py` | **CONVERT** | The stale-cite ban stays; two phrase pins on one registry note collapse. |
| `test_registry_self_version_hook.py` | **KEEP** | Behavior — runs the freshness hook as a node subprocess against synthetic repos. |
| `test_removal_sweep_spec.py` | **CONVERT** | Exact-sentence pins plus a placement re-check over one rule with a built-in negation. |
| `test_review_discipline_asbuilt_record_currency.py` | **DELETE** | Redundant polarity-free re-check of a bullet `test_review_discipline_context_currency` already owns. |
| `test_review_discipline_asbuilt_record_gate.py` | **CONVERT** | Five term co-occurrences across three homes, three of them nearly identical. |
| `test_review_discipline_backend_module_clone.py` | **CONVERT** | Parity stays; a six-token bullet pin plus an ordinal, with no polarity, collapses. |
| `test_review_discipline_context_currency.py` | **CONVERT** | Bullet-anchored already, but one test re-derives the slice the bullet reader performs. |
| `test_review_discipline_context_currency_releasing.py` | **DELETE** | A second module re-pinning four more terms into that same bullet, with a copy-pasted slicer. |
| `test_review_discipline_craft_reference.py` | **KEEP** | Document-topology identity; its one prose test already has a term set and polarity. |
| `test_review_discipline_current_criteria.py` | **CONVERT** | Two functions pin one Stage 1 rule by co-occurrence; the guard passes if the rule is inverted. |
| `test_review_discipline_extraction_test_home.py` | **CONVERT** | Four assertions over one bullet; the weakest is `"test" in bullet` over a bullet about testing. |
| `test_review_discipline_misplaced_helper.py` | **CONVERT** | Six term co-occurrences over one Stage-2 bullet plus a duplicate placement check. |
| `test_review_discipline_partial_hook_adoption.py` | **CONVERT** | One bullet, three literal-term tests plus a bullet-ordering pin encoding no rule. |
| `test_review_discipline_port_orphan.py` | **CONVERT** | The rule is live and single-homed, but the assertion searches the whole file rather than its bullet. |
| `test_review_discipline_type_predicate_coverage.py` | **CONVERT** | Six-term bullet pin plus a placement test that is a strict subset of the bullet slicer. |
| `test_review_discipline_watchlist_entry_currency.py` | **CONVERT** | Slicer-boundary tests stay; the four-term bullet pin collapses. Must keep exporting `_sentences`. |
| `test_review_stop_policy_single_home.py` | **KEEP** | Exclusivity guard — derived corpus, retired-rule sweep, controls both ways. |
| `test_secret_hygiene.py` | **KEEP** | Negative space over git ls-files for dotenv and private-key basenames. |
| `test_settings_derived_parity.py` | **KEEP** | Byte-identity of the two settings files plus membership of permission rules. |
| `test_ship_base_drift_collision.py` | **CONVERT** | Eight tests over one paragraph; the artifact sweep and its splice control stay, six phrase pins collapse. |
| `test_simplicity_ladder.py` | **CONVERT** | `f"{n}." in section` is satisfied by any ordered list; eleven token pins over one section. |
| `test_size_guard_reference.py` | **KEEP** | The named size guard — execs the walker the template ships over tmp_path fixtures. |
| `test_skill_boundary_dedup.py` | **KEEP** | Dedup in negative form plus cross-reference correspondence; sole home of a shared `_section`. |
| `test_source_file_size_justification.py` | **KEEP** | The size guard — walks the tracked index with tmp_path controls on every predicate boundary. |
| `test_spec_authoring_as_built_sets.py` | **CONVERT** | Registry parity stays; the pre-change-token fossil control is now identical to the home assertion. |
| `test_spec_authoring_no_size_ac.py` | **CONVERT** | Two functions pin one rule, already carrying an exact-sentence literal. |
| `test_spec_authoring_scope_claim_invariant.py` | **CONVERT** | The universality leak sweep stays; a section pin, an exact-sentence regex and a placement re-check go. |
| `test_spec_driven_development_asbuilt_record_gate.py` | **CONVERT** | One rule pinned by phrase in four homes; three propagation tests fold into the canonical one. |
| `test_steward_consolidated.py` | **CONVERT** | Absence, registry and dangling-reference sweeps stay; four prose tests collapse. |
| `test_tdd_configuration_coverage.py` | **CONVERT** | Eight exact-phrase pins over one bullet; parity, the derived ordinal and the vocabulary sweep survive. |
| `test_tdd_guard_condition_coverage.py` | **CONVERT** | Eight-term bullet pin, a paragraph-adjacency pin with no consequence, and a frozen prior version. |
| `test_tests_own_state_principle.py` | **CONVERT** | Five term pins into one principles bullet; the `never borrows` polarity is unread. |
| `test_tracker_neutral_lifecycle.py` | **KEEP** | Derived neutral surface minus a documented allowlist, with a can-fail control. |
| `test_tweak_command.py` | **KEEP** | Parity, structural cross-reference and negative sweeps; the /bug inverse pair. |
| `test_update_guidance_lock_untracked_adoption.py` | **CONVERT** | Six prose pins on one command file, four of them exact-phrase regexes. |
| `test_update_guidance_same_version_drift.py` | **CONVERT** | Header/registry parity stays; five classification-table phrase regexes collapse to one tripwire. |
| `test_v4_records_only_what_remains.py` | **KEEP** | Two orthogonal negative-space halves with synthetic-only controls. |
| `test_v4_teardown.py` | **KEEP** | Absence asserted as git ls-files non-membership with a did-not-delete-too-much floor and controls. |
| `test_verify_coverage_gate.py` | **KEEP** | Reads verify.sh through a real argv parser with executable controls — gate wiring, not prose. |
| `test_verify_gate_unrunnable.py` | **KEEP** | Behavior — runs verify.sh against a stubbed broken toolchain and asserts exit 97. |
| `test_visual_evidence_contract.py` | **KEEP** | Already the target shape — presence plus per-occurrence negation-anchored inversion sweeps. |
| `test_work_discovery_skill.py` | **CONVERT** | Parity and the single-home drift guard stay; eleven section pins and a frozen version literal go. |
| `test_workflow_guard_hook.py` | **KEEP** | Behavior — runs the workflow guard as a node subprocess against a hermetic repo. |
| `test_worktree_ignore_hygiene.py` | **KEEP** | Behavior — hermetic repos, real git status / add / check-ignore. |
