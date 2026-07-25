# Changelog

Versions are per-file (see `registry.yaml`). This log records notable changes to the guidance set as a whole.

> Released entries are archived per year under [`CHANGELOG-archive/2026.md`](CHANGELOG-archive/2026.md). This root file keeps only the current `[Unreleased]` window; at each dev→main release its entries move to the archive (see `RELEASING.md`).

## [Unreleased]

### Added — `review` enforces the design stage and reviews against the design (#212)
- Breakdown item 3 of 4 of `specs/proposals/design-verb.md` (accepted 2026-07-25), policy record ADR [`0007`](specs/decisions/0007-design-verb.md) decisions **D3** (enforcement) and **D4** (degrade and record); item 2 (#211) shipped the `harness design` verb this enforces on, and had to land first or every in-flight run would hit `no_design` with no verb to satisfy it. `harness review` gains two behaviours keyed on the run's latest `design` event. **Enforcement:** a run with no `design` event is refused before any engine is invoked, records no `review` event, and exits **5** with `reason=no_design` — the `no_gate_evidence` philosophy, silence is not a pass; an event whose `status` is `failed` **satisfies** the check, since D4's contract is that a design was *attempted and recorded*, never that it succeeded, so an engine flake costs a run its design but never its ability to ship. **Context:** a `status='ok'` event's design is embedded verbatim in the review-engine prompt between the framing and the `SUBMIT` contract, so the `(fix → review)*` loop converges on conformance instead of re-deriving intent every cycle. The check sits **after** the spend breakers (a bounded-out run stops on that) and deliberately **before** the gate-evidence check: a run that never recorded a design is malformed regardless of its gate colour, so refusing on the gate first would report a transient tree state while masking a missing lifecycle stage — root cause first, and it is one ledger read rather than a file read. **Where the design text comes from** was the open question the ticket left to this build. The body is not in the ledger (#211 records `design_hash` only; the body lives on the ticket as a marked comment), and of the ticket's two options — re-fetch the comment, or have the `DesignOutput` consumer pass it — this takes the second: new `--design-file <path>` carries the `design_markdown` `harness design` already printed, and the recorded hash authenticates it. That keeps a comment-read method off the tracker seam and its two backends, keeps the ledger event the single key for both behaviours, and matches #211's own as-built note that nothing reads the design back out of the comment. **Enforcement refuses; context degrades:** enforcement keys on the ledger alone, so `--design-file` can neither satisfy nor bypass it, while an absent, unreadable, or hash-mismatched file drops the context rather than failing the run — never reviewing against an unverified design is already achieved by dropping it, so refusing would add a wedge and buy nothing. A file that was *passed* but could not be read or matched warns on stderr; simply not passing one is quiet (warning there would put a line on every review until every caller adopts the flag, training readers to ignore the warning that matters) and is instead recorded as `design_context` on the `review` event — a non-optional bool beside `gate_ran`, making "did the linkage stop working?" a ledger question rather than a console one. **Watchlist trigger** (`harness/cli/review.py`): outcome **seam, not growth** as the ticket called — the prompt builder (`build_review_prompt`) and the whole gate decision (`resolve_design_gate`, five outcomes, pure) land in `harness/cli/review_protocol.py`; the verb gains only glue (one ledger read, one refusal branch, one file read) plus a `prompt` parameter on `_invoke_engine`, so a usage-limit fallback re-runs the identical prompt rather than rebuilding one that could differ. `design_content_hash` moves into `design_protocol.py` and `harness/cli/design.py` now calls it instead of inlining `hashlib`, so the hash's writer and its verifier cannot drift into permanently mismatching digests. New `test_review_design_linkage.py` (31 tests) covers the refusal and its actionable message, the failed-attempt exemption, the design reaching the prompt, context economy (the design goes in, only the bounded verdict comes out), hash mismatch and unreadable-file degradation, latest-event-authoritative in both directions, all three refusal orderings, and the pure layer directly. New `tests/_ledger.seed_design_event` satisfies the new precondition in the four review test modules that reach an engine — the `tests/_gitutil.init_repo` pattern from #214, one home rather than four pasted seeders. `close` is untouched: its gate already requires a passing review, which now transitively requires a recorded design attempt. `specs/features/verb-model.md` and `cli-surface.md` record the refusal, the ordering, and the new flag; the guidance and `/harness run` loop wording are item 4 (#213). App-only — no distributed guidance file, so no registry bump.

### Fixed — `resolve_repo_root` refuses a path that is not a git top-level (#214)
- Filed by `/assess code` (steward, 2026-07-25, systemic insight CODE-INSIGHT-1, report `assessments/2026-07-25-code.md`), which found two abandoned promotion worktrees nested at `harness/.worktrees/harness/<id>` — one level too deep, inside the `harness/` *package* directory — where the harness's own `worktrees cleanup` (which scans only the canonical `<repo-root>/.worktrees/harness/`) could never see them again. Root cause: `resolve_repo_root` (`harness/workspace.py`) resolved `--repo` with `Path(...).resolve()` plus the `HARNESS_WORKSPACE_ROOTS` allowlist check and nothing else, so any verb invoked with `--repo`/CWD pointing at *any* subdirectory of the real root silently wrote worktrees, branches, and ledger rows under the wrong root — a one-`cd`-away mistake here, where the source package shares the repo's name. The verbs' single path-acceptance point now also requires the survivor to be an actual git top-level, raising the new `NotAGitTopLevel`; `harness/cli/_repo.py` maps it to the same invocation-refusal contract already in force for `WorkspaceNotAllowed` (**exit 2**, path named on stderr, before any tracker/git/DB side effect). Kept a **distinct** exception type rather than reusing `WorkspaceNotAllowed`, whose message ("outside the allowed workspace roots") would be actively wrong for a path squarely inside them; no shared base class for a single catch site. The check is `.git` **presence** (`exists()`, not `is_dir()`) rather than a `git rev-parse --show-toplevel` subprocess: it keeps `harness/workspace.py` framework-agnostic and costs a stat per invocation, and `exists()` is load-bearing because a linked worktree carries `.git` as a *file* — the verbs are routinely invoked with `--repo` pointing at a run's worktree (#179), so an `is_dir()` check would refuse every in-flight run. **Order is load-bearing and pinned by a test**: the allowlist (the security boundary) is checked first, so a path outside the roots keeps reporting the refusal it always did. New tests in `test_workspace.py` and `test_cli_workspace_gate.py` cover the reported subdirectory case, a plain non-repo directory, the linked-worktree acceptance, allowlist precedence, refusal-type distinctness, and that the pure `resolve_within_allowlist` boundary check is left untouched. Five test modules whose fixtures handed a bare `tmp_path` to a verb now initialize a real repo through a new shared `tests/_gitutil.init_repo` helper rather than five pasted `git init` calls. App-only — no distributed guidance file, so no registry bump.

### Added — the `harness design` verb: engine, ticket comment, ledger event (#211)
- Breakdown item 2 of 4 of `specs/proposals/design-verb.md` (accepted 2026-07-25), policy record ADR [`0007`](specs/decisions/0007-design-verb.md); item 1 (#210) shipped the protocol layer, which was inert without a verb to consume it. New `harness/cli/design.py` registers a fourth lifecycle verb, `harness design [--run-id <id>] [--model <alias>]`, between `start` and implement: it resolves the open run through the same shared resolver `review`/`close` use, fetches the ticket's title + description (the spec the design answers to — `start` persists neither on the run row), captures the worktree HEAD as `grounded_sha`, runs the read-only `claude -p --permission-mode plan --model opus` engine under `CONTEXT.md` `loop.engine_timeout_seconds`, and records the outcome in three places: the ticket as a marked comment, the ledger as a new `design` event, and stdout as `DesignOutput`. New `harness/design_marker.py` single-sources the comment contract (`DESIGN_MARKER` + `format_design_comment`) the way `reclaim_marker.py` does for the reclaim/handoff protocols, with tests pinning that a design comment is never read as a resumable branch by either resume reader — three marked-comment protocols now share one ticket's comment stream. New `design` event type and `DesignEventData` payload: `status='ok'` carries the design's sha256 `design_hash` and the `grounded_sha`, `status='failed'` carries a stable `reason` tag plus a human `detail` (the `VerbError` `reason`-vs-`message` split), with `exclude_none=True` keeping each shape's unused fields out of the JSON. **Degrade and record (ADR 0007 D4):** all five ways the stage can fail to produce a design — `engine_timeout`, `engine_error`, `no_submit`, `malformed_submit`, and `no_ticket_spec` (a tracker-less repo, an unresolvable tracker, or a fetch failure, where designing anyway would post a confidently ungrounded design) — append a `failed` event, post no comment, and exit 3, so the stage records the attempt item 3 will enforce on and never wedges a run. One internal `_DesignNotProducedError` carries every failure to a single recording handler rather than re-implementing the contract at five sites. The stage's tracker I/O — read the spec in, post the artifact out — is split into `harness/cli/design_tracker.py`, which raises tracker-shaped failures (`TicketSpecUnavailableError` / `TicketCommentFailedError`) and knows nothing of exit codes, so the verb keeps the whole `reason`-tag vocabulary and there is no import cycle; the split also keeps the new verb module under the 500-line hard limit rather than being born over it behind a `# size:` justification (review FAIL cycle 1 caught this, and it exposed a real trap: `test_source_file_size_justification` reads **git-tracked** files, so a pre-commit gate run is blind to a brand-new file). **Watchlist trigger** (`harness/cli/review.py`): outcome 1, a small behaviour-preserving seam extraction — the bounded engine subprocess driver (spawn, feed stdin, kill *and reap* on expiry) moved to new `harness/cli/_engine.py` along with `RunResult`/`Runner` and a neutral `EngineTimeoutError`, since `design` needed the identical mechanics and a second copy differing only in which exception it raises is exactly the duplication `code-quality` Part A forbids; each verb keeps a thin translator to its own `VerbError`, `review_protocol.py` re-exports the two types so every existing import resolves, and `review.py` got smaller. `review`'s pre-existing timeout tests — which spawn a genuinely hanging child — are the behaviour-preservation proof and are unmodified. New `test_cli_design.py` (27 tests) and `test_design_marker.py` (7) cover the success path, the sha256 hash, the single marked comment, the `DesignOutput` key set, context economy (the engine's pre-SUBMIT chatter never escapes), the engine command and cwd, prompt grounding in the fetched ticket, `--model` override, idempotent re-run, every failure reason, the three refusal shapes (unknown run-id, no open run, a closed run), and two guards that the driver is not duplicated. SPEC §11 and `specs/features/cli-surface.md` gain the command line their drift guards require; the prose as-built record stays reviewer-owned. `review` reading the design event and refusing `no_design` (#212) and the guidance/lifecycle docs (#213) remain out of scope.

### Added — the design engine protocol: prompt, SUBMIT contract, Opus default (#210)
- Breakdown item 1 of 4 of `specs/proposals/design-verb.md` (accepted 2026-07-25), policy record ADR [`0007`](specs/decisions/0007-design-verb.md). ADR 0007 adds a `design` stage to the run lifecycle (`start → design → implement → review → (fix → review)* → close`), but no protocol layer existed for a design engine — `review` has one in `harness/cli/review_protocol.py` and `design` needed its sibling before any verb could be built. New pure module `harness/cli/design_protocol.py`: `build_design_prompt(ticket_title, ticket_description)` renders the read-only design-not-implement posture, the five required Design sections, and the `SUBMIT: {"design_markdown": ...}` contract; `parse_design_submit(stdout)` returns a `DesignResult` with three **distinct** outcomes — the design, `NO_SUBMIT_SENTINEL` (the engine never reached its contract), or `MALFORMED_SUBMIT_SENTINEL` (it emitted a SUBMIT line that does not parse, is not an object, lacks or mistypes `design_markdown`, or carries only whitespace) — because ADR 0007 degrades and records either way, making the recorded reason the only evidence of which happened. `build_design_cmd()` builds the `claude -p --permission-mode plan --model opus` invocation; there is no codex variant (ADR 0002 keeps the in-container engine unprivileged, where `bwrap` cannot start). `DESIGN_SECTIONS` single-sources the section list — three from `templates/change.md`'s Design block (the artifact is that block, not a new artifact class), Security and Test strategy from the `architecture` skill — and the prompt renders from it, so the two cannot drift. `DESIGN_MODEL_DEFAULT = "opus"` is a constant per ADR 0007's unconditional-Opus decision: `resolve_model_tier` stays the dimension-generic seam a future `design:<tier>` label would hang off and is deliberately **not** wired, pinned by a test asserting the module resolves no tier. The two protocols are kept separate rather than sharing a scanner — their payloads and failure handling differ, and entangling them would couple two contracts free to move apart. New `test_design_protocol.py` (21 tests) pins the prompt's sections/posture/contract, all three parser outcomes plus the malformed sub-cases, and the model default; the prompt's own example SUBMIT line is asserted to parse back through the parser. The module is inert until the `design` verb consumes it — the verb, ledger event, and ticket comment (item 2), `review` linkage and the `no_design` refusal (item 3), and the guidance/doc updates (item 4) are out of scope here.

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
- Breakdown item 4 of `specs/proposals/bug-and-tweak-capture-commands.md` (accepted 2026-07-24), landing last so the docs describe what shipped. Items 1–3 (`templates/adjustment.md` #199, `commands/bug.md` #200, `commands/tweak.md` #201) were already registered, so this ticket is documentation only: `spec-driven-development` step 1 now names the capture on-ramp (`/bug`/`/tweak` file a pre-framed change spec straight to Todo; `/start` extends it with Grounding/Design at build time), and `spec-authoring`'s Change spec section notes the same on-ramp relative to the full change-spec form. `process/harness.md`'s Commands table (mirrored byte-identical into `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`) gains `/bug` and `/tweak` rows plus one explicit sentence stating the three-way boundary the proposal's Risks section called for, defending against a later steward lean/MECE finding: `/propose` decides the unconfirmed, `/bug`/`/tweak` capture the confirmed-small, `/start` picks up the filed. New `test_capture_on_ramp_wired.py` pins the command-table rows, the explicit boundary sentence, both skills naming the on-ramp, mirror parity, and header/registry version sync. **`process-harness` 0.4.7 → 0.4.8, `spec-driven-development` 0.5.0 → 0.5.1, `spec-authoring` 0.9.0 → 0.9.1** (registry **0.5.78 → 0.5.79**).

### Added — `commands/bug.md`: files a bug straight to Todo (#200)
- Breakdown item 2: new `commands/bug.md`, a thin capture command filling the shared template with `kind: bug` and filing straight to Todo with no escape hatch (a bug's fix direction is never in doubt — contrast `/tweak`, #201). Documents both tracker backends, including the three-step `gh issue create` → `item-add` → `item-edit --single-select-option-id` that explicitly sets Status=Todo, closing the item-add-no-status trap (tick #90) where a filed item is invisible to `work-discovery`. **New `bug` 0.1.0** (registry **0.5.76 → 0.5.77**).

### Added — new `templates/adjustment.md`: the shared capture template for `/bug` and `/tweak` (#199)
- Breakdown item 1 of `specs/proposals/bug-and-tweak-capture-commands.md` (accepted 2026-07-24): the capture front door for a use-surfaced bug or tweak had nowhere lightweight to land — `/propose` is mis-shaped for already-confirmed work, and hand-filing is fiddly (`gh project item-add` does not set Status, tick #90). This ticket is the template only, blocking `commands/bug.md` (#200) and `commands/tweak.md` (#201), which fill it. New `templates/adjustment.md`: `kind: bug | tweak` / `area` frontmatter, and body sections *As-built (observed)* / *Desired* / *From actual use* / *Acceptance criteria*, with the As-built section giving per-kind framing (a bug's observed is the wrong behaviour plus a repro; a tweak's is the current, correct behaviour plus the friction) and a `kind: tweak`-only escape-hatch note pointing at `/propose` when the tweak turns out to carry a real decision or spans more than one change. Explicitly framed as a **capture-optimized change spec** — same destination as `templates/change.md` (the tracker issue body), extended by `/start` with Grounding and Design at build time — an on-ramp, not a competing artifact. New `test_adjustment_template.py` pins the version header/registry parity, the frontmatter fields, the four sections, the per-kind framing, and the on-ramp statement. **New `template-adjustment` 0.1.0** (registry **0.5.75 → 0.5.76**).

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
