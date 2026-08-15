# ADR 0015 — Harness v4: the runtime is retired; the harness becomes a thin verification layer

- **Status:** Accepted
- **Date:** 2026-08-15
- **Supersedes (in mechanism):** [ADR 0012](0012-persistent-runtime-host.md), [ADR 0013](0013-codex-engines-in-container.md) — their analyses stand as history; the subsystems they govern are retired.

## Context

The harness was built on a 2024 assumption: models need to be *driven* — an external orchestrator sequencing them through `start → review → close`, a Docker container isolating them, a ledger auditing every verb. Current frontier models falsified that assumption. They hold the whole lifecycle in context, drive sub-agents themselves, and get output faster without the machinery. The operator has stopped using the harness app; every tick since #217 has run agent-led `/build`.

The backlog measured this. On 2026-08-15 the repo had **61 open issues**. Categorised, they were: container/Codex-engine/runtime-host (15), test-and-guard debt on harness code (16), assurance-certification machinery (6), deployment/wrapper/doctor/CLI (6), spec/changelog ceremony (5), verb-loop/ledger/routine maintenance (4), promotion machinery (3), steward guidance-coherence machinery (3), the repo's own site (2), and **exactly one** user-facing capability request (#362, visual evidence for review). Not one ticket recorded the machinery catching a defect the agent-led flow would have missed. The backlog was the machinery maintaining itself, and each review of a machinery ticket filed further machinery tickets — the queue grew by construction.

What is *not* obsolete is the discipline the machinery happened to enforce. The ledger records four consecutive ticks where the reviewer's independently built mutation table caught survivors the builder's table missed; the vacuity catalogue (wiring-field survivors, prose-guard polarity, fail-open blacklists) names failure modes frontier models still exhibit. That discipline is the durable value.

## Decision

**The harness stops being a runtime and becomes a thin layer of things a model cannot fake: deterministic gates, enforcement hooks, and a small skill set carrying the review discipline. The model drives; the harness checks.**

### Retired

- The Docker container, the runtime host, and the Codex-in-container review engine.
- The harness CLI: the audited verb loop, the ledger, `serve`, `doctor`, the `~/bin/harness` wrapper, and the deployment machinery around them.
- The assurance-certification machinery (the `assurance:trivial` deterministic certifier and its policy surfaces).
- The promotion-chain machinery and the scheduled unattended-loop configurations (`/harness routine *`).
- The steward's guidance-coherence apparatus and the commit-derived changelog assembler.
- The spec-lifecycle ceremony beyond what a change actually needs.

### Kept and sharpened

- **Deterministic gates.** `scripts/verify.sh` and `scripts/mutate.py` — exit codes and mutation survivors are the artifacts a model cannot self-deceive about.
- **Enforcement moves to hooks.** Claude Code hooks replace the verb loop: a Stop hook that blocks a "done" claim unless the gate ran green this session; a PreToolUse hook guarding pushes to the default branch. Hooks fire mechanically; the audit trail is gate output plus git history, not a ledger.
- **A slim skill set.** Build (test-first, scope, the vacuity catalogue), review (fresh-context adversarial reviewer building its **own** mutation table), debug, ship — plus the backend-neutral `tracker` protocol, which earns its keep because consuming repos genuinely differ (Linear vs GitHub).
- **A versioned craft file.** The cross-session lesson ledger moves into the repo so it travels with the tool.

### Filing policy — the queue must shrink under review

- **The finding 2×2** *(amended later on 2026-08-15, twice, superseding the severity floor shipped that morning — severity was the wrong axis for the filing decision, and once that was fixed the four severity grades had no remaining job)*. Two binaries decide everything about a finding. **Blocking or not**: shipping it would ship a defect (security hole, data loss, crash, spec violation, logic bug, missing test for a criterion) — Critical/High/Medium/Low is retired vocabulary. **Small or large**: cheap-and-contained versus a fix that would blow out the diff in flight or stall the queue. The default is fix-now — do the job right the first time. The cells: small → **fixed now in-branch, whatever it is**; large + non-blocking → **written up**, through *Bundle before you file*; large + blocking → **the ticket cannot ship as scoped** — the FAIL/hold path, a human re-scopes. There is deliberately no "small but not worth doing" case: a specific improvement that is small is always worth its cost, and anything vaguer fails the finding bar before the table is consulted. (The morning's rule — "a Low is never filed" — would have dropped a rewrite-worthy Low and filed a two-line High; both wrong outcomes from one axis doing the other's job.)
- **Recursion cap** *(restated on the same axes)*. A follow-up ticket filed from a review carries the `review-finding` label — that label marks generation one, and generation one is the last. A review of a `review-finding` ticket fixes or drops everything it can and files **nothing**: its one write-up cell (large + non-blocking) closes, and large + blocking remains the FAIL/hold path it always is. One generation of follow-up, never a lineage.
- **Bundle before you file** *(added 2026-08-15, same day)*. Every filing path — review findings, captures, deferrals, features — first searches the open queue for an unstarted ticket on the same surface and extends it rather than filing a twin. One build loop over a surface beats two loops over the same file. (The operator consolidated nearly thirty tickets on a consuming repo this way.) Bound: one honest change spec — same surface, same kind of change; never into a ticket already In Progress or held.

### Integration: base drift is not a stop *(added 2026-08-15, same day)*

The integration branch moving underneath in-flight work is normal concurrency, never a reason to halt or ask the operator: pull the latest, reconcile, re-run the gate, re-bind the review, ship. The **only** escalation is a genuine functional conflict — both changes individually correct but wanting incompatible behaviour, a design call — which goes to the operator as an `input` hold. `/ship` owns the rule; `/build` and `/routine` point at it.

### Hold labels — consolidated

`decision` merges into `input`. Two hold labels remain: **`input`** — the operator must supply something the run cannot (an answer, a judgment call, a credential, a fact); **`operator`** — the operator must be present at the keyboard (setup, hands-on, a visual check). Assignment to a human remains the load-bearing hold signal. Existing `decision` labels in consuming repos migrate on their next guidance update.

### Standing prompts become pointer commands

The unattended build-cycle prompt and the morning digest were running as large pasted prompts. Each becomes a small versioned command — `/routine` (discover the next ticket, build it, ship to the integration branch, hold on a red gate or conflict) and `/digest` (read-only morning report: holds needing input, overnight outcomes, work parked for a verdict, operator errands). `/routine` is deliberately **not** a mode of `/build`: `/build` builds one named ticket; `/routine` owns discovery, the standing branch authorisation, and the hold-don't-force rule.

### Delivery

The existing installer/`/update-guidance` mechanism is retained for now — it is proven cross-repo and works for Codex consumers. Packaging as a Claude Code plugin is the intended future shape once the v4 surface has settled; nothing in this ADR blocks or depends on it.

## Consequences

- **All 61 open issues close citing this ADR.** #362 alone is re-filed in the new shape (visual evidence as a capability of the review skill, carrying #361's measured narrowing: viewport-height slices per width, a documented max capture height). The four held `decision` tickets (#351, #364, #411, #416) become moot — each awaited a judgment about a subsystem this ADR retires.
- Lesson-bearing closures (#432 plan-mode-is-not-a-sandbox, #421 negation polarity, #420 fail-open blacklists, and the wider vacuity catalogue) are preserved in the craft file, not as tickets.
- The teardown itself is tracked as new, bounded work; success criterion for v4: a new repo adopts it in minutes, and the harness itself does not need a ticket for a month.

## The final shape *(recorded by the reviewer at the close of #435)*

The teardown ran in five stages. Measured over the git index — regular-file blobs and symlinks counted separately, since twenty-odd `.codex/` and `.claude/` entries are symlinks — the tree went from **657 tracked paths / 159,547 lines** at `32b1bc9` to **345 tracked paths / 51,342 lines** at `f5f9d98`: 312 paths and 108,205 lines removed.

The branch then reconciled with `dev`, which had shipped #434 (visual evidence for the agent-led review). Base drift is not a stop, so the numbers this ADR ships as are the merged ones: **346 tracked paths / 52,983 lines**, 33% of the repository. The single added path is #434's `tests/unit/test_visual_evidence_contract.py`; the rest of the difference is that module and the three prose-predicate primitives (`_units`, `_NEGATION_GAP`, `_EMPHASIS`) it depends on, re-homed from the deleted `test_build_assurance_workflow` into `tests/unit/test_assurance_filing_rubric.py` beside `_sentences` and `_section` — byte-identical, because a fork of that unit boundary is what every polarity predicate in the tree rests on.

The `harness/` package is gone whole — no seam left the rest importable — and with it `docker/`, `bin/harness`, the GHCR release workflow, `SPEC.md`, the changelog and its archive, the `/harness` command namespace, the `guidance-coherence` skill, and 191 test modules. `tests/integration/` went entirely; the one guard there whose subject survives moved to `tests/unit/`.

What remains is three things. **The guidance surface** — `skills/`, `agents/`, `commands/`, `templates/`, `hooks/`, `process/harness.md` and its three byte-identical mirrors, with `registry.yaml` as the manifest. **The gate** — `scripts/verify.sh`, now ruff, `mypy scripts templates`, one pytest stage with a coverage floor over `scripts/`, and the two `docs/index.html` drift guards; `scripts/mutate.py` is the instrument that proves a guard can fail. **The guards** — `tests/unit/`, almost entirely tree-readers, running 1,564 tests after the #434 merge, none skipped, at 79.12% coverage of the surviving executable code.

Two things survived that the shape of the change made it tempting to remove, both by operator decision: the `dev → staging → main` topology with its nightly automation, which now runs on plain git rather than an audited verb, and `/build --engine codex` with the generated `.codex/` surface.

The retired subsystems' as-built records were **archived, not deleted** — six feature specs moved to `specs/retired/` under dated banners citing this ADR. A retired subsystem's record is what explains the shape of the tree that replaced it, and this teardown is the case in point.
