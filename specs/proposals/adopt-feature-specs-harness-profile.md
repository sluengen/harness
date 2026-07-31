<!-- guidance:template-proposal@0.1.1 -->
---
proposal: adopt-feature-specs-harness-profile
status: shipped          # draft | under-decision | accepted | shipped | rejected | split
date: 2026-06-13
related: [merge-guidance-into-harness]   # esp. CAL-652 (single-surface convergence)
---

# Proposal: Adopt feature specs in the harness

> Make the harness's own as-built record **feature specs at `specs/features/`** by turning on its `feature_specs` layer and migrating the record — applying the already-decided *one-profile / per-repo-config* model to the harness itself.

## Problem / motivation

The universal guidance names the canonical as-built record a **feature spec** at `specs/features/<feature>.md` ([`skills/spec-authoring.md`](../../skills/spec-authoring.md)). The harness still uses *design-doc specs* (`specs/` + `SPEC.md`), with `feature_specs` off. That mismatch — the harness *publishes* the "feature spec" skill while itself using a different shape — is what produced the dangling [`templates/feature.md`](../../templates/feature.md) reference and forces a permanent "except in the harness" caveat.

**This is not a profile change or a decision reversal.** The governing decision — [`specs/architecture-principles.md`](../../specs/architecture-principles.md), *"Merge the guidance repo into the harness"*, resolved 2026-06-13 — has **already retired the standard-vs-harness profile split**: there is one surface, and "`feature_specs` on/off … is **per-repo configuration** (`CONTEXT.md layers:`), not a profile." The convergence that makes this real (fold the profiles' `default_layers` into per-repo config, merge the process docs, complete the single surface, retire the agents repo) is **tracked in CAL-652**.

So "adopt feature specs in the harness" precisely means: the harness **exercises its own per-repo config** (`feature_specs: true`) and **migrates its record** to `specs/features/`. This proposal records that choice and breaks out the migration; it depends on, and must not duplicate, CAL-652.

## Options

**Option A — Turn on `feature_specs` for the harness and migrate (recommended).** Set the harness's per-repo config `feature_specs: true`; migrate its as-built record `specs/` → `specs/features/`. · *Trade-offs:* one model everywhere; the dangling reference resolves once the template is home; aligns with the resolved one-profile decision. Costs a real migration and a `SPEC.md` reconciliation.

**Option B — Keep design docs (the harness's per-repo choice stays `feature_specs: false`).** · *Trade-offs:* smallest; design docs suit a verb-driven infra tool. But the two-shapes-one-library mismatch and the dangling-reference class persist, and the published spec-authoring skill keeps needing a caveat — the inconsistency this is meant to end.

**Option C — Option A scoped to the current surface.** Only the **current verb-model subsystems** become feature specs; retired deterministic-engine docs stay as historical design docs (e.g. `specs/retired/`). A scoping choice *within* Option A.

## Recommendation

**Option A scoped per Option C**, executed **under the existing one-profile / per-repo-config decision** — no new superseding decision is required. The feature-template-home and process-doc convergence ride **CAL-652**; this proposal adds only the harness's `feature_specs` flip and the migration of its own record, scoped to the current subsystems so retired material is not dressed up as live behaviour.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| 1. **Scope** — all of `specs/` → `specs/features/`, or only the current verb-model subsystems (retired-engine docs stay historical)? *Rec: current subsystems only.* | Scott / architect | this proposal → CONTEXT.md |
| 2. **Vehicle / dedup vs CAL-652** — fold the harness's `feature_specs` flip into CAL-652 (which already owns the profile→per-repo-config convergence + template-home + process-doc merge), or keep the flip + record-migration as **standalone tickets that depend on CAL-652**? *Rec: standalone, dependent on CAL-652 — keeps CAL-652 focused on the surface/agents-retirement, this owns the harness's record.* | Scott | this proposal |
| 3. **"Feature" unit in an infra repo** — features map to the agent-facing surface (the `start`, `review`, `close` verbs + subsystems like the ledger and worktree lifecycle). Right unit? *Rec: yes — the verb contract is this tool's product surface.* | Scott / architect | CONTEXT.md |

**Resolved — accepted 2026-06-13.** (1) Scope = current verb-model subsystems only; retired-engine docs stay historical. (2) Vehicle = standalone tickets dependent on CAL-652. (3) "Feature" unit = the verbs + subsystems. Spawned **CAL-660** (turn on `feature_specs`) and **CAL-661** (migrate the record) — both Backlog, blocked by **CAL-652** (and CAL-661 also by CAL-660). The feature-template-home stays with CAL-652.

## Breakdown

Deduped against CAL-652 (the single-surface convergence). The change specs this would spawn once accepted:

1. **[CAL-652 — not new] Feature template home + complete the single surface.** The feature template comes home and the published `spec-authoring` reference resolves as part of CAL-652's "complete and stabilise the single surface." *Reference and depend on CAL-652; do not file a duplicate.* **(prerequisite for 2–3)**
2. **[CAL-660] Turn on `feature_specs` for the harness** — set the harness's per-repo config `feature_specs: true` (`CONTEXT.md layers:`), reconcile with `registry.yaml`'s `default_layers` (which CAL-652 is folding into per-repo config — coordinate, don't fight it), and update [`process/harness.md`](../../process/harness.md) (or the converged process doc) to drop the design-doc divergence. Surface/config + docs only; no code.
3. **[CAL-661] Migrate the as-built record `specs/` → `specs/features/`** — move the current verb-model subsystem specs to `specs/features/`, reconcile `SPEC.md` (index + current-vs-retired banners), and re-home retired-engine docs as historical (per Open decision 1). The largest item; may split per subsystem.

*(No `architecture-principles` supersede item: the one-profile / per-repo-config decision already supports the harness choosing `feature_specs: true`. The choice is recorded where per-repo config lives — `CONTEXT.md`.)*

## Risks / unknowns

- **Overlap / sequencing with CAL-652.** This is the dominant risk: the `feature_specs` flip is inert until the template is home and the `default_layers`→per-repo-config fold lands. Items 2–3 must be sequenced behind CAL-652 and must not re-implement its surface work.
- **Don't resurrect profile language.** The framing must stay in per-repo-config terms; reintroducing a "standard profile" would contradict the resolved decision.
- **`SPEC.md` is mid-retirement** (v0.7: §1–2/§4/§11 current; §3/§5–10/§12–14 retired). Item 3 must not promote superseded sections into live "features."
- **"Feature" is a slightly forced unit** for a verb-driven tool (Open decision 3); the mapping (verbs + subsystems as features) needs to read naturally, or the migration produces awkward specs.
- **Footprint guard.** `specs/` is an app prefix in [`tests/unit/test_guidance_footprint.py`](../../tests/unit/test_guidance_footprint.py); `specs/features/` stays under it, so the harness's own feature specs remain repo/app content — no guard change expected, but item 3 should confirm.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
