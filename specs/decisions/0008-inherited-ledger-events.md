# ADR 0008 — A ledger event may assert what the emitting verb did not observe, if it names its source

- **Status:** Accepted
- **Date:** 2026-07-30
- **Source:** `specs/proposals/resume-earned-stages.md` (D1, D3)

## Context

Two gates key on `run_id`: `review`'s design enforcement (`no_design`) and `close`'s passing-review check (`no_passing_review`). A reclaimed ticket re-picked with `harness start --resume` mints a **new** `run_id` — deliberately, so the spend breakers get a fresh window — and both gates reset with it. The resumed run therefore re-pays for an Opus design call and a full review cycle the ticket has already paid for, even when the design comment is still on the ticket and a `pass` exists for the exact tree the resumed worktree holds.

The scope collision is the bug. Run-scoped state is two different things wearing one scope:

- **Budget** — `max_review_cycles`, `wall_clock_budget_minutes` — belongs to the run. Cancel+resume *should* open a new window; carrying it over is the wedge `commands/harness.md` warns about.
- **Certification** — a recorded design attempt, a `pass` bound to `reviewed_sha` — does not. ADR 0007 D2 already scopes the design artifact to the change spec ("it lives and dies with the change spec"), and a pass names an exact commit, which `close` re-checks against HEAD. Neither gate draws any *safety* from `run_id`.

Fixing that requires choosing how a resumed run comes to hold certification it did not itself earn. The cheap answer — widen both gate queries from the run to the ticket — is safe (`close`'s `reviewed_sha == HEAD` check does all the protective work) but leaves `harness events <resumed_run>` showing no design and no pass while `close` succeeds. The audit trail would be true only to a reader who knows the query is ticket-scoped.

## Decision

**Certification may cross a run boundary, but only as an event recorded on the inheriting run, naming the source run and the evidence it rests on.** Gate queries stay run-scoped; nothing reads across runs.

Concretely:

- A resumed run that recovered its predecessor's WIP records its **own** `design` event marked inherited, carrying `inherited_from` (the source `run_id`) and the source `design_hash`. The design *text* is recovered from the ticket comment, so the session can build against it — an adopt path costs a ticket read instead of an Opus call.
- A resumed run whose worktree HEAD equals a prior pass's `reviewed_sha` records its **own** `review` pass, carrying that same `reviewed_sha` and the source pass's verify-gate evidence, plus `inherited_from`. The writer verifies the source event exists with a matching SHA before writing.

The general rule this sets, which future work must honour: **an event may assert something the emitting verb did not itself observe only when (a) the assertion is verifiable from another recorded event, (b) the verb verifies it at write time, and (c) the event names its source.** An event that asserts an unverifiable fact, or one that hides where it came from, is forbidden regardless of how convenient the gate becomes.

## Alternatives rejected

- **Widen the gate queries to the ticket.** Smaller diff, and genuinely safe — `close`'s SHA binding is untouched and does all the work. Rejected because it makes the ledger untrue by omission: the run's own record shows nothing while the gate opens. The ledger's readability is the product, and "smallest change" is not a licence to make the record less true. It also fails to deliver the actual goal: it satisfies `no_design` while leaving the session with no design *text*, which on the clean-start path is worse than re-designing — a skipped verb dressed as a recovered design.
- **Never cross the boundary; always re-earn.** The status quo. Rejected because the charge falls hardest on long unattended runs, and it was not weighed when ADR 0007 made `design` unconditional — it arrived as a side effect rather than a decision.
- **Reuse the predecessor's `run_id` instead of minting a new one.** Would make the question disappear. Rejected: `commands/harness.md` is explicit that this carries the tripped wall-clock window and cycle count straight over, so the next `review` trips the identical breaker. Budget must reset even when certification does not.
- **Store the design text in the `design` event.** Would let the ledger reproduce a design without a ticket read. Rejected as ledger bloat for a payload deliberately kept to a hash and a `grounded_sha`; the ticket comment is already the artifact's home (ADR 0007 D2), and reading it back is what `harness/design_marker.py` deferred a parser *for*.

## Consequences

- **Design inheritance is gated on WIP recovery, not on the ticket alone.** Inherit only when the run resumed from the preserved branch; on a clean-start fallback, re-design — the tree the design described is gone. The signal already exists and is currently discarded (`_resolve_resume_start_point` returns a ref or `None`).
- **`harness/design_marker.py` gains the parser it deferred.** Its stated reason for shipping without one — "a parser with no reader would be speculative surface" — is now resolved by an actual reader, not overridden.
- **An inherited pass is a second way to open the close gate.** Accepted knowingly. It is bounded by the exact-SHA match and source-event verification — the same trust boundary the gate already sits behind — and its tests must cover the negatives explicitly: no source event, a source event for a different SHA, a source `fail`.
- **A stranded run that is *closable* should be closed, not reclaimed.** `close` has no spend breaker and the run stays `open`, so a run holding a HEAD-matching pass was never stranded, only unfinished. `reclaim --stale` classifies it rather than reverting it. This is the smaller half of the fix and carries no gate risk, so it ships first — inheritance then covers the genuine mid-build reclaim rather than the common case.
- **The cloud regime keeps the gap.** `review` was deliberately *not* given a checkpoint-push on a pass (proposal D4, rejected), so a passing tree is durable off-container only when the run separately ran `checkpoint`. Off-container, an unpushed pass is still re-reviewed. Revisit only if the loop moves off the documented local trigger.
