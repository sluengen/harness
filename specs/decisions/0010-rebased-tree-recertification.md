# ADR 0010 — A rebased tree may inherit certification for the hunks it did not change; the verify gate is never inherited

- **Status:** Accepted
- **Date:** 2026-07-30
- **Source:** the `rebase-stable-certification` proposal (settled; removed from the tree by #547, kept in git history)

> **Landed retrospectively on 2026-08-01.** Decided 2026-07-30; the file sat on an unmerged local branch while its breakdown tickets were built and closed, so the decision was in force well before its record was. Nothing below is reconstructed — this is the file as written on the decision date, with only its status reconciled to what shipped. Implemented by #266 and #267; item 3 (`review --since`) was retired unbuilt as #268 — see the source proposal.

## Context

The close gate requires a `review` event with `verdict='pass'` whose `reviewed_sha` equals the run worktree's HEAD (`harness/cli/close.py:371`). A rebase rewrites every commit SHA on the run branch, invalidating that pass wholesale — including for the hunks the rebase left byte-identical.

Base movement alone does **not** cause this, contrary to the intuition that motivated the question. `close_merge.merge_run_branch` fetches `origin/<base>`, creates a detached throwaway worktree at that tip, and merges the run branch into it (`harness/close_merge.py:85-195`); the run worktree's HEAD is never touched, so a base that advanced during the run is integrated with no rebase and no gate impact. The gate breaks only when the run branch's own HEAD moves, which happens two ways: a genuine merge conflict (whose `CloseMergeError` message itself instructs "rebase the run branch… re-review, and close again"), or a pre-emptive rebase by the orchestrating session, which buys nothing at all.

The measured waste, from this repo's ledger: 260 `pass` events across 222 runs — 38 excess passes. Of the 27 runs holding two or more distinct passing SHAs, **18 had zero intervening `fail`**, carrying 24 review cycles that produced no finding. That is an upper bound rather than a clean attribution, because refusals are unrecorded (ADR 0009) and a double pass can also be a voluntary post-pass commit. The mechanism is nonetheless confirmed in the operating record: run `01KYR7T7B5E3QDC3WP7ZGYHTGV` spent two full rebase → gate → re-review → close rounds, and both conflicts were in `CHANGELOG.md` only.

Two things constrain any fix:

- **A rebased diff is not wholly old.** It decomposes into hunks the pass already covered and hunks the rebase introduced — the conflict resolution, which is new, unreviewed content. In the run above that content was a hand-merged changelog, exactly where a duplicated or dropped entry hides.
- **A clean rebase is not semantic proof.** Runs `01KYR8ZJS21SF2WYAXKEEBPQ38` and `01KYR7T7B5E3QDC3WP7ZGYHTGV` each added a different method to the same `Tracker` Protocol in the same file, and git merged them textually without complaint.

So the question is not whether the binding is too tight. It is that re-certification is all-or-nothing: the only way to move a pass to a new SHA is to buy a whole new review.

## Decision

**The SHA binding stays exactly as it is. What becomes cheaper is re-certification, not the precision of the record — and the verify gate re-runs on the new tree in every case, unconditionally.**

Concretely:

- **`reviewed_sha` remains an exact commit SHA.** It is a cheap, unforgeable statement of what was reviewed, and `close`'s ability to name the commit it merged depends on it. Content identity (`git patch-id`, a diff digest) does not replace it.
- **A pass may be recorded for a new HEAD by reviewing only the delta**, via `harness review --since <sha>`: the engine reviews `git diff <passed_sha>..HEAD` rather than the whole change. The recorded pass names the source pass it extends.
- **A delta-scoped pass opens the close gate only atop an ancestor pass**, never on its own. At write time the verb verifies that the named source `review` event exists with `verdict='pass'`, and that its `reviewed_sha` is an ancestor of the new HEAD. This is [ADR 0008](0008-inherited-ledger-events.md)'s rule applied to a third case: the event asserts coverage the emitting verb did not itself observe, the assertion is verifiable from another recorded event, the verb verifies it before writing, and the event names its source.
- **Verify-gate evidence is never inherited across a tree change.** `close`'s `no_gate_evidence` conjunct must be satisfied by a gate that ran on the new HEAD. Inheriting it would be an event asserting something unverifiable, which ADR 0008 forbids outright — and the gate re-run is the only thing in the system that catches a clean-textual-merge semantic conflict.
- **The conflict source is removed, not just survived.** `CHANGELOG.md` moves to per-change fragments under `changelog.d/`, folded at release, so two concurrent runs no longer conflict by construction on a file whose merge semantics are "keep both lines".
- **A run must not rebase for base movement.** `close` integrates `origin/<base>` itself. `close_merge`'s conflict message stops prescribing a rebase as the sole remedy, and `commands/harness.md` states the rule.

## Alternatives rejected

- **Bind the pass to content identity instead of a SHA** (`git patch-id --stable`, or a digest of the three-dot diff). Rejected: it answers the wrong half. A conflict resolution changes the diff, so the identity changes too — and the conflict case is the dominant one. It also discards the exactness the merge record depends on, and `patch-id` deliberately ignores line numbers and whitespace, making it *looser* than the current check in ways nobody has reasoned about.
- **Accept a merge-forward HEAD whose tree is a recomputed merge.** The run merges `origin/<base>` into its branch, and `close` accepts a HEAD when a passing `reviewed_sha` is an ancestor, HEAD is a merge commit whose other parent is on the base, and HEAD's tree equals an independently recomputed merge of the two — proving no content was smuggled in. Genuinely stronger than a delta review where it applies (deterministic proof rather than a judgement), and the throwaway-worktree machinery already exists. Rejected as **narrower**: it covers only the conflict-free case, which the two cheap fixes above largely eliminate, and it would require switching the integration idiom from rebase to merge-forward against the repo's linear-history habit. Held as the fallback if the delta review proves awkward.
- **Treat every rebase as a new review (the status quo).** Rejected: it charges a full engine cycle to re-learn a verdict for unchanged hunks, and the charge falls hardest on the unattended loop, where concurrent runs make base movement routine.
- **Widen the gate to accept any pass for the ticket.** Not seriously considered here — ADR 0008 already rejected the ticket-scoped variant of this for making the ledger untrue by omission.

## Consequences

- **The waste this fixes is measurable only after ADR 0009 ships.** Sequencing puts telemetry first: `close`'s `stale_review` refusal rate is the quantity that says whether the delta-scoped review earns its surface. It was accepted on a 24-excess-pass upper bound; if the measured rate comes back negligible, dropping the delta review is the correct outcome and its ticket is where that is recorded.
- **Semantic conflict remains undetected by any of this.** Only the re-run verify gate catches it. A cheaper re-certification path means merges land more often, so a coverage hole in the gate is proportionally more dangerous. This is why the gate re-run is non-negotiable and why the recomputed-tree alternative was not stacked on top.
- **A delta review cannot see a conflict whose halves are both outside the delta.** The `Tracker` Protocol case is exactly that shape. Accepted, because the gate re-run covers it and because the alternative — always reviewing everything — is the cost being removed.
- **The changelog fold in `RELEASING.md` changes shape.** The three-threshold rule and the CHANGELOG size-guard tests are written against one accumulating file; fragments replace the first-pass byte fold with an assembly step. This is more than a mechanical move and carries its own ticket.
- **`close_merge`'s conflict message is load-bearing guidance.** It has been instructing the rebase that causes the invalidation. Correcting a message is not cosmetic here; it is the cheapest of the fixes and removes a whole class of self-inflicted re-review.
