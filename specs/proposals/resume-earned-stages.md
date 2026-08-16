<!-- guidance:template-proposal@0.1.2 -->
---
proposal: resume-earned-stages
status: superseded         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-30
related: [run-ledger, verb-model, stale-run-reclamation, design-verb, 0007-design-verb, 0008-inherited-ledger-events]
---

# Proposal: A reclaimed ticket should not re-earn the stages it already has

***Superseded 2026-08-15** by [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md) — the run ledger, the `run_id`-scoped certification and the paid stages this rescopes are gone. A gate marker named after the git tree now carries the only certification the process keeps, which makes the re-earning problem structurally impossible rather than solved. Kept for the audit; nothing below describes current behaviour.*

> Since ADR 0007 made `design` unconditional, a reclaimed-and-re-picked ticket pays for an Opus design engine call and a full review cycle it has already paid for — because both gates key on `run_id`, and a resumed run is a new run. This proposes scoping *certification* to the ticket and the tree (where it belongs) while leaving *budget* scoped to the run (where it belongs).

## Problem / motivation

`harness reclaim` reverts a stranded ticket to Todo; the next pick runs `harness start <TICKET> --resume`, which mints a **new `run_id`** with a fresh `started_at`. That is deliberate — it opens a new spend-breaker window, and `commands/harness.md` is explicit that reusing the old row would carry the tripped wall-clock and cycle count straight over.

But two gates are keyed on `run_id` as well, and they reset with it:

- **`review`'s design gate** — `_read_latest_design_event(db_path, resolved_run_id)` (`harness/cli/review.py:574`). No design event for *this* run ⇒ exit 5, `reason=no_design`. So the resumed run must re-run the Opus design engine.
- **`close`'s review gate** — `_evaluate_gate` (`harness/cli/close.py:371-431`) selects `review` events `WHERE run_id = ? … AND json_extract(data_json, ?) = 'pass'`. No pass for *this* run ⇒ `no_passing_review`. So the resumed run must re-run the review engine, even when the tree it holds is byte-identical to one that already passed.

Nothing is destroyed by a reclaim. The design comment is still on the ticket; both ledger events still exist under the dead `run_id`. **Only the query scope is wrong.** Two observed costs:

1. **Mid-build death.** A run designs, implements half the ticket, dies. Reclaim preserves the checkpoint-pushed branch; `--resume` recovers it. The resumed session is handed working code produced *against a design it is then forbidden to see* — and must spend an Opus call to regenerate a design for work already done.
2. **Death between `review` and `close`.** A run passes review, then the session stops (context, wall clock, container). Once it is idle past `loop.wall_clock_budget_minutes` (110 min) the sweep reclaims it — since #260 that is not a threshold *mirroring* the wall-clock breaker but the very same configured value. The fresh run re-designs *and* re-reviews to reach a `close` that was one command away.

The status quo cost is not the wasted tokens alone. It is that the most expensive, least-recoverable runs — the long ones — are the ones charged twice, and the charge lands on the unattended loop where no human is watching it.

### The distinction the design turns on

Run-scoped state is two different things wearing one scope:

| | Scope it belongs to | Why |
|---|---|---|
| `max_review_cycles`, `wall_clock_budget_minutes` | **the run** | Budget. Cancel+resume *should* open a new window; carrying it over is the wedge `commands/harness.md` warns about. |
| a recorded design attempt | **the ticket** | ADR 0007 D2: the artifact "is the change spec's Design section… it lives and dies with the change spec." |
| a `pass` bound to `reviewed_sha` | **the tree** | The pass names an exact commit. `close` already re-checks `reviewed_sha == HEAD`; run identity adds nothing to that guarantee. |

The bug is that certification inherited budget's scope. Nothing about either gate's *safety* comes from `run_id`.

### Three facts that constrain any fix

- **F1 — the ledger cannot reproduce a design.** `DesignEventData` (`harness/events/payloads.py:150`) carries `design_hash` and `grounded_sha`, not the text. The only surviving copy of the design is the ticket comment written by `format_design_comment` — and `harness/design_marker.py` deliberately has **no parser**, on the stated grounds that "a parser with no reader would be speculative surface." Any fix that gives a resumed session a *usable* design must create that reader.
- **F2 — a design's validity depends on whether the WIP came back.** Resumed from the preserved branch, the prior design *is* the design that produced this tree. Fallen back to a clean start (no durable WIP, or the branch no longer fetches), the tree it described is gone. `start --resume` already knows which happened — `_resolve_resume_start_point` returns a ref or `None` — and currently discards the distinction.
- **F3 — a stranded passing run is closable in place.** `close` has no spend breaker and resolves its open run from the worktree. So scenario 2's run does not need reclaiming at all: it needs `close`. It is the sweep, keying on time alone, that converts a finishable run into a re-pickable one. (Local regime only — in a cloud container the worktree is gone.)

## Options

**Option A — Widen the two gate queries to the ticket.** `review`'s design lookup and `close`'s pass lookup select over all runs for the ticket instead of one run. · *Trade-offs:* smallest possible diff, and `close` stays exactly as safe (the `reviewed_sha == HEAD` check is untouched and does all the work). But it makes the ledger lie by omission: `harness events <resumed_run>` shows no design and no pass, yet `close` succeeds. Auditing the run then requires knowing the query is ticket-scoped. It also does nothing about F1 — enforcement is satisfied while the session still has no design text, which on the clean-start path (F2) is *worse* than re-designing: it buys a skipped Opus call at the price of building blind.

**Option B — Record inheritance explicitly on the resumed run.** The resumed run gets its own events, marked as inherited with provenance. For design: `harness design` gains an adopt path — when the run resumed from a preserved branch and the ticket carries a prior design comment, it recovers that text (F1's reader), re-records a `design` event naming the source run and `design_hash`, and posts nothing new. Costs a ticket read, not an Opus call. For review: `start --resume` (or a small verb) writes an inherited `review` pass only when the recovered HEAD equals the source pass's `reviewed_sha`, carrying the same `reviewed_sha` and gate evidence plus `inherited_from`. · *Trade-offs:* the ledger stays literally readable — every run's certification is visible on that run, with a link to where it came from — which is the property this repo's whole audit story rests on. Solves F1 as a side effect, and the adopt path gives `design_marker`'s parser the real reader it was waiting for. Costs: a new event field (or status value) on two payloads; an inherited pass is a *written* pass, so the code that writes it becomes a close-gate surface and must verify the source event itself.

**Option C — Do not reclaim a closable run; close it.** `reclaim --stale` learns one more additive ledger check: an open run holding a `pass` whose `reviewed_sha` equals its worktree HEAD is reported as `closable`, not reverted. The routine's step 0 then drives `close` on those before it picks new work. · *Trade-offs:* fixes scenario 2 outright with no cross-run carry-forward at all — the run is never abandoned, so nothing needs inheriting, and the honest observation (F3) is that it was never stranded, only unfinished. Degrades cleanly to today's behaviour in the cloud regime, where the ledger and worktree are unreachable. Costs: the pre-flight gains the ability to merge, which is a real expansion of what step 0 does even though the routine already ships via `close` in its normal arm; and it does nothing for scenario 1.

**Option D — Make a passing review durable.** `review` checkpoint-pushes on a `pass` (or the guidance requires it), so the pass's tree always survives its container. · *Trade-offs:* closes the gap that makes scenario 2 unrecoverable in the cloud regime, and is the same insight as `stale-run-reclamation` D4 ("preserve is only real if WIP is durable") applied to review instead of implement. But it is orthogonal to the lookup-scope bug and adds a push to a verb documented as read-only-plus-a-verdict. Better as its own change than folded in here.

**Option E — Do nothing; accept the double charge.** · *Trade-offs:* zero risk to the gates, and reclaim-then-resume is not the common path. But the charge falls hardest on long unattended runs, and it grew with ADR 0007 rather than being designed in — the cost was not weighed when `design` became unconditional.

## Recommendation

**Adopt C and B, in that order; treat D as a separate change; reject A.**

They address different failures and should not be collapsed:

- **C first, because scenario 2 is not a carry-forward problem.** F3 says the run was closable the whole time. Reverting it to Todo, re-picking it, re-designing, re-reviewing and then closing is an elaborate way to reach a state one command away. The smallest honest fix is for the sweep to stop destroying it. This also sequences well: C ships without touching either gate, so it carries no gate risk at all.
- **B for scenario 1, because the ledger has to stay readable.** Option A is a smaller diff and is *safe* — `close`'s SHA binding genuinely does all the protective work. But this repo's central claim is that the ledger is the audit trail, and a gate that silently reads another run's row breaks the reading. `engineering-principles`' "smallest change" is not a licence to make the record less true; and A's failure to address F1 means it does not actually deliver the thing the operator asked for (a resumed session that *has* its design), only the thing that looks like it (a skipped verb).
- **Gate B's design inheritance on F2.** Inherit only when the run resumed from the preserved branch. On a clean-start fallback, re-design — the tree the design described is gone, and inheriting there would hand the session a design for code that no longer exists. The signal is already computed and thrown away in `_resolve_resume_start_point`; using it costs nothing.
- **D stays separate** because it changes what `review` does rather than what a gate reads. Folding a push into this proposal would couple a durability fix to a scope fix, and either one failing review would hold the other.
- **A is rejected** on the audit-trail ground above, not on safety. If B proves too heavy, A is the fallback — but then it should be A *plus* the design-comment reader, or it delivers a skipped call rather than a recovered design.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — Widen the query, or record inheritance?** Option A (gates read ticket-scoped; ~small diff, ledger lies by omission) vs Option B (resumed run gets its own marked events with provenance; larger, ledger stays readable). *Rec: **B** — the ledger's readability is the product.* | user | ADR + run-ledger feature spec |
| **D2 — May the pre-flight merge?** Option C has `/harness routine build` step 0 drive `close` on a closable stranded run, before it picks work. The routine already ships via `close` in its normal arm, but this is a new trigger point. Alternative: the sweep only *reports* `closable` and a human drains them. *Rec: **let it close** — an unattended loop that can ship its own work can finish someone else's; a reported-only list needs a human the loop exists to not need.* | user | run-ledger feature spec / `commands/harness.md` |
| **D3 — Is an inherited `review` pass acceptable at all?** B writes a `pass` event no engine produced. It is *true* (same SHA, same tree, source event cited) and the writer verifies the source, but it makes a new code path a close-gate surface. Alternative: inherit design only, and let a resumed run always re-review. *Rec: **inherit it**, gated on an exact `reviewed_sha == HEAD` match and carrying `inherited_from` — but note that if C lands, the case this serves is rare, so deferring it costs little.* | user | ADR + run-ledger feature spec |
| **D4 — Does a passing review imply a push (Option D)?** Separate change either way; the question is whether it is in scope now or filed for later. *Rec: **file it separately**, sequenced after C — C makes it less urgent in the local regime and leaves it as the cloud-regime fix.* | user | verb-model feature spec |

**Cross-cutting.** D1 and D3 together decide whether a ledger event may ever assert something a verb did not itself observe. That is a principle future work must honour, so on acceptance it belongs in an ADR, not only in a feature spec.

### Resolved 2026-07-30

- **D1 → Option B, record inheritance.** The resumed run gets its own `design` event marked inherited, naming the source run and `design_hash`, and recovers the design *text* off the ticket comment so the session can actually build against it. Option A is rejected on the audit-trail ground, not on safety: `close`'s SHA binding genuinely does all the protective work, but a gate that silently reads another run's row makes `harness events <run_id>` untrue by omission, and the ledger's readability is the product.
- **D2 → the pre-flight may close.** `reclaim --stale` reports a closable stranded run and `/harness routine build` step 0 finishes it before picking new work. The routine already ships via `close` in its normal arm, so this is a new trigger point rather than a new capability; a report-only variant would need the human the unattended loop exists to not need.
- **D3 → inherit the review pass** (decided *against* the proposal's own recommendation to defer). A resumed run whose HEAD equals a prior pass's `reviewed_sha` records a `review` pass carrying that same SHA and gate evidence plus `inherited_from`, after verifying the source event. The operator accepted the new close-gate surface on the strength of the exact-SHA bound: the assertion is true of the tree being merged, and the alternative — re-reviewing a byte-identical tree — is the double charge this proposal exists to remove. Breakdown item 5 is therefore **in scope**, not deferred.
- **D4 → rejected. `review` does not push.** The verb stays read-only-plus-a-verdict; no checkpoint-push is folded into a pass, now or as a follow-up. **Consequence, accepted deliberately:** a passing tree is durable off its container only when the run separately ran `checkpoint`. So in the cloud regime a pass that was never checkpoint-pushed is unrecoverable, `--resume` falls back to a clean start, HEAD does not match, and the resumed run re-reviews — exactly today's cost. D2 covers the local regime, which `commands/harness.md` documents as the default deployment; the cloud regime keeps the gap. This also bounds D3: the inherited-pass path is reachable only when the tree came back, which off-container means a checkpoint happened to land after the pass.

**Recorded in:** [ADR 0008](../decisions/0008-inherited-ledger-events.md) — the cross-cutting D1+D3 principle: when a ledger event may assert something the emitting verb did not itself observe. The `run-ledger` feature spec records the *mechanics* as each breakdown item ships, written by the reviewer on PASS — not up front, since the behaviour does not exist yet.

## Breakdown

Ordered so each ships and is useful on its own. Items 1–2 are Option C, items 3–5 are Option B. Option D is **rejected** (D4), so there is no push-on-pass item.

1. **`reclaim --stale` classifies a closable run.** An open run whose worktree HEAD matches a recorded `pass` is reported in `SweepOutput` as `closable` and **not** reverted. Additive ledger check, in the same shape as `#216`'s liveness override: unreachable ledger or worktree ⇒ today's behaviour exactly.
2. **Wire the closable path into `/harness routine build` step 0.** Drive `close` on each closable run before the pick, per D2. Guidance change plus the routine body.
3. **A reader for the design comment.** `design_marker.parse_design_comment` — the counterpart `harness/design_marker.py` deliberately deferred until it had a reader (F1). Recovers the design text and its stated `design_hash` from a ticket comment; single-sourced against the formatter with a round-trip test, and non-colliding with the reclaim and handoff markers.
4. **`design` adopts a prior design instead of re-running the engine.** When the run resumed from a preserved branch (F2) and the ticket carries a prior design, record a `design` event marked inherited with `inherited_from` and the source `design_hash`, emit the recovered `design_markdown` as normal `DesignOutput`, and post no new comment. Clean-start fallback ⇒ run the engine as today.
5. **Inherited review pass on resume.** Per D3 (accepted): when a resumed run's HEAD equals a prior pass's `reviewed_sha`, record a `review` pass carrying the same `reviewed_sha` and the source pass's gate evidence, plus `inherited_from`, after verifying the source event exists with a matching SHA. Otherwise no-op — a resumed run holding a different tree reviews normally. Ships **after** item 1, so the common case (a closable run) is already handled and this covers the genuine reclaim.

### Spawned issues (2026-07-30, GitHub board `sluengen/2`)

Created in dependency order; the loop picks by ID order, which matches the sequencing above — the no-gate-risk half lands before anything touches a gate.

| Item | Issue | Depends on |
|---|---|---|
| 1 — `reclaim --stale` classifies a closable run | [#255](https://github.com/sluengen/harness/issues/255) | #254 gap 1 (see Risks) |
| 2 — drive `close` on closable runs in routine step 0 | [#256](https://github.com/sluengen/harness/issues/256) | #255, #254 gap 1 |
| 3 — `parse_design_comment` reader | [#257](https://github.com/sluengen/harness/issues/257) | — |
| 4 — `design` adopts a prior design | [#258](https://github.com/sluengen/harness/issues/258) | #257 |
| 5 — inherited review pass | [#259](https://github.com/sluengen/harness/issues/259) | #255, #258 |

The #254 dependency was found reconciling against the queue **after** these issues were filed (2026-07-30) and is recorded in Risks below; #257 is the only item with no prerequisite, so it is the cleanest first pick.

Item 5 is the highest-risk item (it adds a second way to open the close gate) and is sequenced last deliberately: with #255 shipped, the common case is already handled, so #259 is never the only thing between a stranded run and a merge.

## Risks / unknowns

- **An inherited pass is a written pass.** Item 5 creates a second way to open the close gate. The mitigation is that the writer verifies the source event and the exact SHA — the same trust boundary the gate already sits behind — but it remains a new surface, accepted knowingly at D3. It ships after item 1 so it is never the only thing standing between a stranded run and a merge, and its tests should include the negative cases explicitly: no source event, a source event for a different SHA, and a source `fail`.
- **A stale design on a resumed branch.** F2's gate keys on *how the run started*, not on how far HEAD has since moved. A design grounded many commits back is still inherited. This matches ADR 0007's own bar — enforcement is "attempted and recorded," and even a *failed* attempt satisfies it — but it means "has a design" can mean "has an old design." The `--design-file` hash check keeps the review side honest either way; the build side relies on the session reading it.
- **C's benefit is regime-dependent, and D4 leaves that standing.** Item 1 needs the worktree and the ledger, so it is a local-regime fix. The default deployment is local (`commands/harness.md`), so this is the common case, not the edge — but a cloud routine gets nothing from it, and with Option D rejected there is no durability fix behind it either. Off-container, a pass that was never checkpoint-pushed is still re-reviewed. That is the accepted residual cost of this proposal, not an oversight; revisit it only if the loop actually moves off the local trigger.
- **Items 1–2 depend on `#254`, and item 2 is where the hazard bites.** Reconciled 2026-07-30. #254 records a sweep that reclaimed **two live sessions** (ERP-213, ERP-215) because time was the only liveness signal — mid-gate-retry, zero commits, no ledger event for ~2h40m. Item 1's closable classification inherits that exposure, and item 2 turns it from a misclassification into a **merge**: a session alive but quiet at a *clean* HEAD matching an earlier pass would be closed out from under itself. A dirty worktree is already safe (`close` refuses `dirty_worktree`) and a concurrent close is bounded by an existing test, but a live session **paused at a clean, previously-passed SHA** has nothing protecting it. So items 1–2 land **after** #254's gap 1 (the worktree-mtime sparing signal), or item 1 incorporates that signal directly. The sweep must not grow two independently-shaped "don't reclaim this" paths, because they mean opposite things downstream: *spared because alive* must **not** be drained; *closable because finished* must be.
- **`#254`'s "no undo" gap is not addressed here.** Inheritance lowers the *cost* of a false-positive reclaim, which is tempting to read as a partial undo. It is not: items 4–5 both gate on `runs.resumed_from`, and a preserved branch exists only when a `checkpoint` pushed it — #254's incident had zero commits and nothing pushed, so nothing would have been inherited. That gap has no claimant.
- **`worktree_path` is recorded container-absolute, which item 1's predicate must respect.** Verified against #249's live open run: the recorded path is `/workspace/.worktrees/harness/<id>`, which does **not** resolve on the host (`close.py:238` consumes it verbatim, correct inside the `~/bin/harness` container and meaningless outside). Item 1 must resolve HEAD exactly as `close` does — same path, same regime — and must not rebase the path onto the repo root, since diverging the predicate from the gate it predicts is the one thing it cannot do. A host-side implementation would make the feature a **silent** no-op, because "not closable" is also the fail-safe answer.
- **What would invalidate the recommendation:** if a design engine call became cheap (a `design:<tier>` label defaulting below Opus — the refinement ADR 0007 D1 anticipated and deliberately did not build), scenario 1's cost mostly evaporates and items 3–5 stop paying for themselves. Item 1 stands regardless, since it saves a whole re-pick cycle rather than one engine call.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
