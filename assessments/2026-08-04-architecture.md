# Architecture assessment — 2026-08-04

**Steward:** steward (`architecture` scope, `--deep`) · **Base:** `dev` @ `030386a` · **Gate:** not run — read-only assessment.

## Why this pass

This low-cadence pass asked whether the harness's accumulated features and system shape still earn their keep, with particular attention to simpler paths to the same outcome, gravity wells, logic decay, operational fit, verification architecture, and the health of the as-built record. It read the declared boundaries in `CLAUDE.md`, `SPEC.md`, the architecture principles and recorded decisions, all four feature specs, the live package and test map, the verification gate, recent assessments, file churn since 2026-07-01, and the local ledger through the read-only `harness stats` surface.

## Verdict

**The core shape is still right, but two additions have escaped the discipline that made the core good.** The orchestration inversion remains the system's best decision: an agent owns judgement while small deterministic verbs own durable state and a SHA-bound merge gate. SQLite, isolated worktrees, typed event payloads, replaceable engine subprocesses, and host-run verification evidence form coherent boundaries. The close/reclaim shared certification predicate and the tracker factory show that the design can remove disagreement by construction rather than by prose.

Risk concentrates at the edges added after that core stabilized. Promotion is a second lifecycle whose non-success path bypasses the tracker seam and is therefore incompatible with the repository's current GitHub backend. The unconditional Opus design stage adds roughly another review-sized engine call to every run, but deliberately permits the run to continue after failure; the ledger currently demonstrates cost, not benefit. Meanwhile the record describing the architecture has accumulated enough duplicated current prose that it contradicts itself and the live tree. The shortest route to broader outcomes is therefore not a new layer: finish the tracker abstraction, tier the existing design stage according to evidence, and reduce the number of places that claim to be the current as-built description.

## System map / current shape

- **Orchestration boundary:** a human or routine launches one agent session; the session implements and calls `start → design → review → close`. The harness does not own the agent loop (`specs/architecture-principles.md:15-17`).
- **CLI / application boundary:** Typer registers lifecycle, recovery, inspection, and promotion commands from `harness/cli/__init__.py:28-47`. Command modules orchestrate; reusable git, gate, promotion, state, event, and tracker mechanics live below `harness.cli`.
- **Durable state:** `.harness/harness.db` holds run rows, append-only events, and promotion records. Pydantic payloads in `harness/events/payloads.py` define event contracts; `harness/state/store.py` owns managed SQLite connections and migrations.
- **Safety boundary:** review certification is bound to a commit SHA; `close` rechecks a clean tree and fresh gate evidence through the shared `certify_head` predicate (`harness/cli/close.py:95-107`, `harness/cli/_review_gate.py`). Merge mechanics are isolated in a throwaway worktree (`harness/close_merge.py`).
- **External boundaries:** `harness/tracker.py:47-138` defines one tracker protocol and chooses Linear, GitHub, or no tracker from `CLAUDE.md`. Review/design engines are bounded CLI subprocesses. The verification command runs on the host where the target repo's toolchain exists, and verbs classify the supplied evidence.
- **Distribution boundary:** this repository contains both the AGPL application and the versioned MIT guidance surface. `registry.yaml` defines the installed surface; tests guard imports, registry membership, public CLI/JSON contracts, and generated documentation.

## What is working

### Preserve the agent/verb boundary

The system correctly avoids rebuilding an agent runtime. Judgement and adaptation remain in the session; the harness owns the parts that benefit from determinism. This is simpler than the retired workflow engine and continues to fit the product's actual use (`SPEC.md:61-68`).

### Preserve the SHA-bound gate and shared predicates

The reviewed-SHA invariant, clean-tree refusal, and verify-evidence rule are the architecture's load-bearing safety properties. Close and stale-run classification now share `harness/cli/_review_gate.py`, so “closable” cannot drift from what `close` accepts. This is a strong application of stable contracts and making the right thing easy.

### Preserve local, append-only operational evidence

The ledger is earning its keep beyond audit: recent work used it to tune the timeout, distinguish refusals from failures, and expose latency and cycle counts. The read-only `stats` command makes architectural cost questions answerable without adding an external observability system.

### Preserve the host-toolchain boundary

Review and promotion classify gate evidence instead of trying to make the harness container host Python, Node, Xcode, and every future target toolchain. `scripts/verify.sh:6-31` distinguishes an unrunnable toolchain from a red tree, while the CLI binds supplied evidence to the relevant SHA. This is the correct operational trade-off for a cross-repository tool.

### Preserve verification of structure as well as behaviour

The suite does more than chase line coverage. It enforces a 90% package floor (`scripts/verify.sh:28-31`), checks every module can import first-cleanly, prohibits imports from lower layers into the CLI (`tests/unit/test_import_layering.py:172-184`), locks public CLI/JSON contracts, and exercises the real Docker image when Docker is available (`tests/integration/test_docker.py:58-74`). The suite is large, but the important boundaries are explicitly named and mechanized.

## Architectural risks

### ARCH-1 — Promotion escalation bypasses the tracker boundary — High

**Filed as:** [#328](https://github.com/sluengen/harness/issues/328), shared with CODE-2 because both findings identify the same production boundary violation.

**What:** The repository declares `tracker: github`, and ordinary verbs obtain their backend through `tracker_client`, but `promote escalate` directly constructs `LinearClient`, reads `LINEAR_API_KEY`, requires a Linear team, and catches Linear-specific errors. Promotion is therefore not a complete lifecycle on the backend this repository currently dogfoods: a promotion reaching `needs_ticket` or `blocked` cannot take its prescribed terminal escalation path through GitHub.

**Where:** `CLAUDE.md:13-20` selects GitHub; `harness/tracker.py:47-138` defines the replaceable tracker boundary; `harness/cli/promote.py:703-788` bypasses it. The public contract and as-built record expose the same Linear-only path at `specs/features/cli-surface.md:48` and `specs/features/cli-surface.md:55-72`.

**Why:** This violates **stable contracts, replaceable implementations** and **separation of concerns**. Backend selection is supposed to live once in the tracker factory (`harness/tracker.py:103-138`); a lifecycle command that selects its own backend creates a second architecture and makes the system's current operational configuration internally inconsistent.

**How:** Move escalation issue creation and re-escalation comments behind the existing tracker factory. Replace the Linear-shaped `Tracker.create_issue(team_key=...)` contract with a backend-neutral issue-creation request whose native repository/team is held by the configured client; retain `--team` only as a deprecated Linear compatibility override if the public CLI contract requires it. Add GitHub and tracker-less promotion-escalation scenarios alongside the existing Linear tests, then update the CLI feature spec to describe one tracker-neutral path.

### ARCH-2 — The unconditional Opus design stage has a measured cost but no measured outcome advantage — Medium

**Filed as:** [#332](https://github.com/sluengen/harness/issues/332), shared with CODE-1 and SYSTEM-5 because the correction requires one coherent design-stage decision.

**What:** Every run pays for a dedicated Opus design call, even trivial tickets. Failure is explicitly non-blocking: merely recording an attempt satisfies review's lifecycle requirement. The live ledger shows 90 attempts (74 successful, 16 failed), with duration evidence on 29 calls at a median of about 331 seconds; those measured calls consumed about 169 minutes, including 35 minutes on five failed calls. First-review results and review-cycle counts do not presently establish an advantage for successful designs: the available, non-random samples average 1.48 review cycles after an `ok` design versus 1.25 after a failed one. That is not evidence that design harms outcomes, but it is evidence that the architecture currently proves the spend and not the return.

**Where:** `specs/features/verb-model.md:41-58` makes the Opus stage unconditional and failures non-blocking; `specs/proposals/design-verb.md:59-75` accepts the cost and records `design:<tier>` as the relief valve. Operational evidence came from read-only `.venv/bin/harness stats --db .harness/harness.db --json` and grouped `events` queries during this pass; `CLAUDE.md:42` independently records recent 366-second design and 321-second review medians.

**Why:** This is now in tension with **minimal dependencies/cost**, **simplicity**, and **design for extension, not speculation**. A separate design context may be valuable, but requiring the most expensive tier on every run is a stronger architectural claim than “design before code,” and the system does not yet measure the outcome that would justify it.

**How:** Use the existing ledger to add a 30-day decision report segmented by design status/model and ticket complexity, measuring first-review pass, review cycles, wall clock, and terminal completion. Then activate the already-recorded `design:<tier>` seam: default routine work to a cheaper design model and reserve Opus for an explicit complexity label. Keep the separate design artifact and SHA linkage; remove only the unconditional top-tier spend. Revisit skipping the stage entirely only if the larger sample shows no outcome gain.

### ARCH-3 — Duplicated “current” architecture records now contradict the live system — Medium

**Filed as:** [#334](https://github.com/sluengen/harness/issues/334).

**What:** The feature specs are declared canonical, but `SPEC.md`, `CLAUDE.md`, and `specs/architecture-principles.md` continue to restate current architecture in detail. Those copies have decayed in different directions: the architecture principles omit `design` from the deterministic verb list and omit the `architecture` assessment scope; one paragraph says `commands/harness.md` is distributed while another calls it registry-excluded; `SPEC.md`'s live system diagram omits `design` and its current module map says `start`/`close` use `harness.linear`; `CLAUDE.md` still defines the product and audit discipline in Linear-only terms despite selecting GitHub; and the CLI feature spec says both that the caller runs the promotion gate and that gate execution runs inside `start`/`continue`.

**Where:** `specs/architecture-principles.md:4`, `:19-21`, `:52-66`; `SPEC.md:4-7`, `:72-99`, `:213-217`; `CLAUDE.md:13-20`, `:64-80`; `specs/features/cli-surface.md:63-74`.

**Why:** This violates **one source per piece of knowledge**, **stable contracts**, and the repository's own “feature specs are the as-built record” decision. Agents are instructed to read these files before changes; mutually incompatible current descriptions make the spec record a source of guesswork precisely where it is meant to remove it. The recently corrected `last_updated` fields do not catch semantic duplication.

**How:** Make `SPEC.md` an index and historical decision narrative rather than a second as-built description: replace its current verb/module/CLI restatements with links to the four feature specs. Keep `specs/architecture-principles.md` to cross-cutting principles and decisions, reconcile it to the tracker-neutral and four-stage model, and make `CLAUDE.md` name only repo configuration plus a short map. Update the feature specs to use tracker-neutral domain language except where backend behaviour is intentionally contrasted. Add a guard that rejects backend-specific claims in shared lifecycle paragraphs and a test that the architecture-principles scope/verb sets match the derived live sets.

## Watchlist / triggers

### Keep the existing entries

- `harness/cli/review.py` remains the highest-complexity orchestration boundary (1,242 lines; 22 changes since 2026-07-01). The protocol, inheritance, and telemetry extractions are good seams, but breakers, gate evidence, tracker parking, engine invocation, and event recording still converge here.
- `harness/cli/close.py` remains a load-bearing gate/finalization junction. Its split into merge, tracker, certification, and telemetry modules is working; removing it from the watchlist would invite those concerns back.
- `harness/cli/reclaim.py` still combines single-target recovery and stale-sweep classification after several seam extractions. The existing trigger remains justified.

### Add `harness/cli/promote.py`

At 810 lines and ten changes since 2026-07-01, it owns five subcommands plus ledger coordination, gate classification, publication dispatch, and tracker escalation. ARCH-1 is already a boundary leak inside it. On the next touch, the watchlist trigger should extract a tracker-neutral escalation orchestrator rather than add another backend branch to this file.

### Add `harness/cli/design.py`

At 747 lines and fourteen changes since 2026-07-01, it is now a recurring change surface for adoption, engine execution, output-channel recovery, tracker publication, and event telemetry. `design_protocol.py`, `design_tracker.py`, and `design_adopt.py` prove that stable seams exist; the next change should either extract engine-result orchestration or explicitly defer with a reason.

`harness/events/payloads.py` should **not** be added. It is the highest-churn file, but its growth is typed declarations in the intentionally single home for event contracts, not branching or cross-layer orchestration.

## Recommended actions

1. **Restore one tracker architecture across every lifecycle.** Route promotion escalation through `Tracker`; prove Linear, GitHub, and tracker-less outcomes. This closes a current operational dead end.
2. **Tier design spend using the evidence already collected.** Add the segmented outcome view, then default routine tickets below Opus while keeping the separate design context and explicit high-tier override.
3. **Collapse the current record onto the feature specs.** Turn duplicated live sections in `SPEC.md` into pointers, reconcile architecture principles, and remove Linear-only language from shared contracts.
4. **Extend `architecture_watchlist.files` with `harness/cli/promote.py` and `harness/cli/design.py`.** Use the next-touch trigger for one bounded seam extraction or a recorded deferral.

## Findings / tickets to file

- **ARCH-1 (High):** Make promotion escalation tracker-neutral and cover all configured tracker modes.
- **ARCH-2 (Medium):** Measure design-stage outcome value and activate per-ticket design tiering.
- **ARCH-3 (Medium):** Consolidate the canonical architecture/as-built record and remove contradictory current prose.

The watchlist additions belong with ARCH-1/ARCH-2 or one small architecture-maintenance ticket; the positive observations above are narrative and should not be filed.

## Not assessed

- No production code was changed and the verification gate was not run; this is an architecture assessment, not a fresh merge certification.
- External tracker APIs, hosted GitHub branch protection, live engine CLIs, Docker daemon behaviour, and scheduled-task health were not invoked. Their boundaries and tests were read, but their services were not probed.
- Accepted proposals whose implementation has not landed were read only where they explained a current decision; they were not judged as shipped architecture.
- This pass did not repeat the code steward's dead-code, dependency-version, security-sink, or line-by-line test-quality sweeps, nor the system steward's guidance-coherence audit.
