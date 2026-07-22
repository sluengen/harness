<!-- guidance:template-proposal@0.1.2 -->
---
proposal: optional-project-scope
status: accepted   # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-22
related: [stale-run-reclamation]
---

# Proposal: Make project scoping optional in the build routine

> Let a consuming repo run the build loop across a whole tracker queue, not just one named project — by making `repo.project` optional rather than required.

## Problem / motivation

The `/harness routine build` loop scopes all work selection to a **single** project — `CONTEXT.md → repo.project`. A consuming repo (nano-erp) runs several active projects in one Linear team and wants the loop to pull from any of them. Today Todo tickets in a second project are invisible: nano-erp had 5 wholly-actionable tickets stranded in a "Design System" project while the routine reported its Build-queue project empty and fell through to idle. A manual workaround exists but there is no first-class support, and the scoping is enforced in three places that must move together:

1. **`work-discovery` skill** — "Work off one Linear project … named in `CONTEXT.md → repo.project`."
2. **`/harness routine build`** — resolves `<repo.project>` and passes it to both the reclaim pre-flight and the pick step.
3. **`harness reclaim` CLI** — `--project` is **required** with `--stale`; the compiled tool has no unscoped sweep mode.

**What the original write-up (against nano-erp's *installed* copies) could not see:** since it was written, the harness grew a **tracker seam** (`harness/tracker.py`) that abstracts the backend — `tracker: linear | github | none`. Two facts from that seam reshape this work:

- **GitHub already ignores `project`.** `GitHubClient.fetch_reclaimable_issues` documents: "the `project` argument is accepted for protocol symmetry but the board itself *is* the queue, so it is not re-resolved." For a `tracker: github` repo (which the harness itself now is), the reclaim sweep is *already* whole-board; there is no sub-project narrowing to make optional.
- **The concept the write-up calls "team" is Linear-only.** `LinearClient.fetch_reclaimable_issues` filters `project: { name: { eq: $project } }`; widening it means filtering by *team* instead. GitHub has no "team" — it has a repo and a board. A `--team <key>` flag would import Linear vocabulary into a backend-agnostic verb and seam.

So the honest framing is not "add a team-wide mode" but **"make the project scope optional on the tracker seam, and let each backend interpret 'unscoped' as its own natural full queue."** For Linear that is the team (`repo.linear`); for GitHub it is the board it already sweeps. The guidance surface also still speaks pure Linear ("Work off one Linear project", `<repo.project>`) despite the harness running `tracker: github` — this change is the moment to make that wording tracker-neutral and conditional.

If nothing is done: multi-project Linear consumers keep hand-rolling a whole-team pick and lose the audited reclaim pre-flight, and the guidance stays Linear-shaped against a seam that is no longer Linear-only.

## Options

**Option A — Linear `--team` flag (as originally written)** · Add `harness reclaim --stale --team <key>` as an alternative to `--project`, thread `team` through `fetch_reclaimable_issues`, and drive it from the routine when `repo.project` is unset. · *Trade-offs:* matches the write-up literally, but `team` is meaningless for GitHub, so the seam method grows a parameter one backend can never honour; it leaks Linear vocabulary into the backend-agnostic verb; and it adds a second required-scope flag with exactly-one-of validation to maintain.

**Option B — Optional project on the seam; unset = the tracker's natural full queue** · Make `project` optional everywhere: `fetch_reclaimable_issues(*, project: str | None)`, `reclaim --project` optional, `repo.project` optional in CONTEXT. When `project` is unset, each backend sweeps its natural full scope — Linear filters by team (`repo.linear`) instead of project; GitHub keeps its existing whole-board behaviour unchanged. The guidance reads conditionally: `repo.project` set → scope to it; unset → the whole tracker queue. · *Trade-offs:* one new concept (nullable scope) instead of a new flag; respects the seam's abstraction; is a genuine no-op for GitHub. The Linear unset path must pass the team key to bound the query (the client already holds config, so this is threading, not new infrastructure). Slightly more than a "filter change" because the Linear query swaps its filter key by scope.

**Option C — Multi-project list (`repo.projects`)** · CONTEXT lists the projects the loop may pull from; the loop unions their queues. · *Trade-offs:* more precise than whole-team (the loop never touches a project you excluded), but does not match nano-erp's stated ask ("pull from *any* of them"), multiplies reclaim/pick calls per tick, and adds ongoing list-maintenance config. A reasonable future refinement, not this change.

## Recommendation

**Option B.** It realizes the write-up's own stated instinct — *absence of `repo.project` is the signal, no magic sentinel* — but corrects the mechanism: the lever is a nullable scope on the **seam**, not a Linear-shaped `--team` flag bolted beside `--project`. This is the smallest change that honours the existing abstraction (`engineering-principles`: smallest change, no leaky abstraction, separation of concerns). It leaves the harness's own `tracker: github` behaviour untouched (the board is already the full queue) while unblocking the Linear multi-project consumer, and it lets the guidance surface become tracker-neutral in the same stroke instead of accreting more Linear-specific prose.

The `reclaim --stale` sweep still keys entirely on the tracker's `updatedAt` (proposal `stale-run-reclamation` D2), so the reclaim semantics — idempotent, In-Review-untouched, tracker-keyed — are unchanged; only the enumeration's scope filter moves.

## Open decisions — resolved 2026-07-22

| Decision | Resolution | Recorded in |
|---|---|---|
| **D1 — Scope model.** Option B (nullable scope on the seam) vs A (Linear `--team` flag) vs C (`repo.projects` list). | **B — nullable scope on the seam.** | issue #174 (seam design); an ADR if the seam contract rises to cross-cutting |
| **D2 — Behaviour for `tracker: github` (the harness itself).** | **Unchanged.** GitHub's board is already the full queue; `repo.project` there is descriptive only. The feature's behavioural effect is Linear-only, documented as such. | CONTEXT template doc (issue #176) |
| **D3 — Sentinel vs absence.** | **Absence** of `repo.project` = full-queue mode. No `repo.project: all` sentinel. | CONTEXT template doc (issue #176) |
| **D4 — Idle-arm filing when unscoped.** | File `/assess` findings to the team backlog with no project; `repo.default_findings_project` is a follow-up, out of scope. | `commands/harness.md` routine quality (issue #175/#176) |

## Breakdown

Spawned as separate change specs on board `sluengen/2` (this repo's tracker), each shippable on its own:

1. **[#174] Nullable scope on the tracker seam + reclaim CLI** — `fetch_reclaimable_issues(*, project: str | None)` on the `Tracker` protocol and both backends (Linear: unset → filter by team from `repo.linear`; GitHub: unset → existing whole-board, no behaviour change); `reclaim --project` becomes optional with `--stale`; the `--stale requires --project` validation is removed and the tracker-less no-op path preserved. Tests: Linear unset sweeps across projects in one team; GitHub unset unchanged; scoped path unchanged; conformance test still pins both clients to the seam.
2. **[#175] Guidance surface: conditional, tracker-neutral scoping** — `work-discovery` SKILL states scope conditionally (project set → scope to it; unset → the whole tracker queue) with ranking rules unchanged; `/harness routine build` resolves scope from CONTEXT at runtime (project present → scoped calls; absent → unscoped reclaim + unscoped pick), and its Linear-only wording becomes tracker-neutral. (Bump both `guidance:` version stamps.)
3. **[#176] CONTEXT schema/template + idle-arm filing doc** — mark `repo.project` optional in `templates/context.md` (or wherever the schema doc lives), document both modes and the per-backend meaning of "unscoped", and document where idle-arm `/assess` findings file when unscoped (D4).

## Risks / unknowns

- **The Linear unset query still needs a team bound.** Dropping the project filter entirely would sweep the whole workspace, not the team. The Linear backend must filter by `repo.linear` when project is unset; confirm the client can reach that config (it is constructed by `tracker_client`, which reads CONTEXT, so this is threading not new plumbing) and that Linear's `issues` filter supports a team predicate the way it supports `project.name.eq`.
- **Unbounded enumeration.** Both backends request up to 100 active tickets unpaged; a whole-team sweep across several projects could exceed that where a single project would not. Verify the 100-cap comment ("a single project never holds more than that") still holds team-wide, or add paging if a large-team consumer needs it.
- **Doc-drift blast radius.** Making the guidance tracker-neutral touches shared surface shipped to every consuming repo; keep the change to scoping wording and resist a broader Linear→tracker rewrite (scope discipline).
- **Invalidation.** If a real consumer needs to *exclude* specific projects from the loop (not just widen to the whole team), Option C (multi-project list) becomes the right answer and B is insufficient — worth confirming nano-erp's need is genuinely "whole team" before building B.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
