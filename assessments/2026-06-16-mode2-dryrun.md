# Mode-2 migration dry-run — 2026-06-16

**What:** the first real execution of the Mode-2 path (supersede pre-merge agents-repo guidance via **re-bootstrap**). **Target:** `coffee-standards/brewspec` — a genuine pre-merge install (`profile: standard`, flat `skills/*.md`, `source: { name: agents }`), **public** → `local` visibility mode. **Source:** local harness checkout, `dev` @ `63b54da` (recorded in the consumer lock as `ref: local`). **Gate:** N/A — observational dry-run; brewspec verified by `git check-ignore` + lock/file diff. **Closes:** CAL-717 AC-1 (recorded result) + AC-3 (defects filed). Origin: [`2026-06-15-system-and-code.md`](2026-06-15-system-and-code.md) **SYSTEM-6**.

## Why this pass

SYSTEM-6 flagged that the Mode-2 path was *designed but never run*, and that the fold-knowledge lives in `INSTALLER.md` (so the correct tool is **re-bootstrap**, not `/update-guidance`). CAL-733 shipped the doc half (AC-2). This pass runs the migration on a real old-guidance repo and records what the legacy-artifact detection + no-clobber rules actually do.

## Verdict

**The re-bootstrap mechanically works and is gitignore-safe.** A pre-merge `standard`/agents-repo install migrated cleanly onto the single surface: skills moved to the `SKILL.md` shape, two stewards merged to one, `standard.*` → `harness.*`, all ~18 superseded files removed, and in `local` mode the **only committable change was `CONTEXT.md`** (every internal + `.env` gitignored). The predicted risk — orphan files left behind by the layout shift — **did not materialise**; the agent removed them by reasoning from the registry.

The defects are about **deploy readiness and documented rules**, not the mechanics:
- **the migration cannot ship externally yet** — `main` still lacks the registry-based installer (CAL-748);
- an agent omitted two profile skills on **layer gating that isn't actually built** (CAL-749);
- the INSTALLER's documented fold-list is **stale for this exact migration** — the run succeeded on agent judgment, not on the doc (CAL-750).

## Migration scorecard (verified against the BEFORE baseline + `registry.yaml`)

| Check | Expected | Actual | ✓ |
|---|---|---|---|
| Skills → `skills/<id>/SKILL.md` | 15 (one surface) | 13 installed (2 omitted — see CAL-749), corrected to 15 | ⚠️→✓ |
| Flat `skills/*.md` orphans | 0 | 0 | ✓ |
| Agents | `code-steward`+`harness-steward` → one `steward.md` | 4 agents, single `steward.md` | ✓ |
| Renames/removals | `linear-sync`→`linear`, `code-review` gone, `standard.*`→`harness.*` | all done, originals removed | ✓ |
| New surface | `build`, `review-discipline`, `guidance-coherence`, `assessment.md` | all present | ✓ |
| Lock | `profile: harness`, `source: …ref: local` | exactly that | ✓ |
| Entry files | `AGENTS`==`CLAUDE`==`GEMINI`, `process-harness@0.4.4` | byte-identical | ✓ |
| Local-mode safety | only `CONTEXT.md` tracked, `.env` ignored, `CONTEXT.md` tracked | exactly that | ✓ |

## Findings (filed)

### DRYRUN-1 — Mode-2 cannot deploy externally until the registry-based installer reaches `main` — High → **CAL-748**

**What:** `INSTALLER.md` (dev) tells external repos to install from `main` and read its `registry.yaml`, but `main` (`bce7cf7`) is still the old lock-based model — no registry, no Mode-2 handling.
**Where:** `INSTALLER.md` step 1 vs. `main`'s tree.
**Why:** a real Mode-2 deploy following the released instructions fails or silently runs the old installer.
**Observed:** the dry-run agent went to `main` first, found no registry, and had to be redirected to the local `dev` checkout — an option a real consumer lacks.
**How:** gate Mode-2 deploy on the next `dev`→`main` release; note the local-checkout source is for source iteration only.

### DRYRUN-2 — install-time layer gating is unbuilt + miscited; profile-file omission drifts the lock — Medium → **CAL-749**

**What:** `registry.yaml:59` cites *"install-time layer gating is CAL-675"*, but CAL-675 is `Done` and is about `/harness run` universality — not layer gating. The agent used that non-existent gating to omit `design-system` + `ux-design` (38/40 files), drifting the lock from the registry; `/update-guidance` would keep offering to re-add them. `ux-design` must never be gated (applies to any user-facing surface; brewspec has a CLI + docs site).
**Where:** `registry.yaml:57-62`.
**Why:** the one-surface model installs the whole profile and gates *engagement* via `layers:` at runtime; selective install-time omission isn't supported.
**How:** fix the citation; document the contract (install-all vs. build real gating); never gate `ux-design`. *(brewspec corrected to the full 40-file install during this pass.)*

### DRYRUN-3 — INSTALLER fold-list is stale for the agents-repo→harness merge; delete-confirmation ambiguous at scale — Low → **CAL-750**

**What:** INSTALLER step 2 names only pre-merge folds (`scope-discipline`/… → `code-quality`, `spec.md` → `feature.md`); it omits the folds this migration performs (flat→`SKILL.md` layout, `linear-sync`→`linear`, two stewards→`steward`, `code-review` removal, `standard.*`→`harness.*`, old lock `source` schema). Separately, a faithful re-bootstrap removed ~18 files while INSTALLER says *"do not delete automatically — remove only with my confirmation."*
**Where:** `INSTALLER.md` step 2 (legacy-artifact + no-clobber paragraphs).
**Why:** the run migrated correctly only because the agent reasoned from the registry; a literal reading of the doc would leave orphans, and the delete rule doesn't scale to a migration.
**How:** enumerate the merge fold set (or a "migrating off pre-merge guidance" checklist); distinguish supersede-cleanup (bulk, one confirmation) from foreign-file deletion (individual).

## Disposition

- **brewspec:** migration **accepted**. Corrected to the full 40-file install (added `ux-design` + `design-system` per DRYRUN-2), `CONTEXT.md` profile-note refreshed, `CONTEXT.md` committed locally (`cae7f67`, **not pushed**). Internals + `.env` remain gitignored — nothing leaks to the public repo.
- **Defects:** CAL-748 / CAL-749 / CAL-750 filed against Harness v3 (`review-finding` + `improvement`).
- **Reproduce:** copy a pre-merge repo, re-bootstrap per `INSTALLER.md` from the harness `dev` checkout in `local` mode, diff actual vs. `registry.yaml`.
