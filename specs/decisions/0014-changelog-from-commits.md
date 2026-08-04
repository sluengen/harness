# ADR 0014 — The changelog derives from commits at release; the fragment system is deleted

- **Status:** Accepted
- **Date:** 2026-08-04
- **Source:** `specs/proposals/changelog-from-commits.md`
- **Amends:** [ADR 0010](0010-rebased-tree-recertification.md) — its conflict-removal decision is preserved; the mechanism it chose is replaced.

## Context

ADR 0010 moved `CHANGELOG.md`'s `[Unreleased]` block to per-change `changelog.d/` fragments (#267) because two concurrent runs conflicted at a shared insertion point **by construction**, on a file whose correct merge semantics are "keep both lines". That cost run `01KYR7T7B5E3QDC3WP7ZGYHTGV` two full rebase → gate → re-review → close rounds and went on to refuse a close on two further ticks. `merge=union` was rejected on direct evidence from the same run. **That decision was correct and its property is not in question here.**

What has accumulated on top of it is. Measured 2026-08-04:

- **486 lines of guard, 1,388 lines of test, 47 tests, and a 107-line runbook** enforcing a presence check (`require`), a structural check (`check`), a per-fragment byte budget, a fragment-count bound, a reserved no-ticket stem class (#287, shipped the same day), and a doc-guard suite asserting `RELEASING.md` describes all of it.
- **Zero released entries produced.** `CHANGELOG.md` holds exactly one `## ` heading — `[Unreleased]` — carrying 12 entries that predate #267 and are frozen by the may-not-grow ratchet. The only release ever tagged, `v1.0.0`, is dated 2026-05-27, three months *before* the fragment system existed. **The fold has never run.**
- **24 pending fragments, 5 of them (21%) `### None` exemptions** — files whose entire content is a statement that no entry is warranted.
- **44–54% vocabulary overlap** between a fragment and its own commit body (#281, #291), each around 2.5 KB, written by the same agent in the same pass.
- **80 of the last 80** non-merge commits on `dev` carry a valid `type`; `harness/cli/release.py` contains **zero** references to the changelog.

The system diagnosed its own duplication and mispriced the remedy: the per-fragment byte guard fails with *"Reasoning longer than that belongs in the change spec, the commit body, or the review record — where it already lives in full"* — correctly identifying the second copy, then capping its length rather than asking why it exists.

The generic argument for write-time fragments is sound: capture the *user-facing* entry while context is fresh, in the reader's language. This repo does not realize it, because one agent writes the fragment and the commit body in a single pass with no change of audience. The #287 fragment discusses `_sort_key`'s `int(...)` and `merge-base..HEAD` — implementer language in both files.

## Decision

**The changelog is derived from commits at release time. The `changelog.d/` fragment system, and every guard enforcing it, is deleted.**

- **Source of truth is the commit log.** `git log <last-tag>..HEAD --no-merges`, grouped by conventional-commit `type` mapped onto Keep-a-Changelog categories, with the ticket id parsed from the subject. A human edits the result once, at release.
- **ADR 0010's property is preserved and strengthened.** The prohibition is on a *shared append point*, not on a particular file layout. Commits never conflict, and unlike fragments there is no second file to forget, mis-name, or exempt. Any future changelog mechanism must clear the same bar: a plain `[Unreleased]` block does not.
- **There is no exemption concept.** Not every commit becomes an entry; the release editor drops what does not matter. The 21% of fragments that exist solely to declare "no entry warranted" have no successor, by design.
- **The audience is the deciding input, and it is recorded as uncertain.** The operator's answer — "nobody yet, realistically" — is what selects deletion over the drafted alternative (commits by default, fragment as an optional override). That alternative's whole value is a curated-prose escape hatch, which is conditional on a reader existing. **If a real external reader appears, revisiting this is legitimate and the override is the shape to revisit toward.** This ADR is contingent on an empirical claim, and says so.
- **Measurement gates the work.** Nothing is deleted before the fold has run once on the pending window and its output has been compared against what `git log` would produce over the same range. If the folded section wins, this decision is revisited.

The general rule this sets: **a record that is compelled per-change, and that duplicates a record already being written, is a tax rather than a control.** Enforcement should be added when the thing it enforces has demonstrated its output, not before.

## Alternatives rejected

- **Keep it and judge after one release (Option A).** The system is three days old, so "has produced no output" is partly youth. Rejected as the *destination* but adopted as the *gate*: item 1 runs the fold precisely so this option gets its fair test, and retains the standing to overturn the decision. What makes it wrong as a resting place is that each further edge case adds a layer — #287 was the second in three days — and every layer a later simplification must unwind.
- **Commits by default, fragment as an optional override (Option D).** The drafted recommendation, and correct in general: it keeps the curated-prose hatch for the minority of changes whose meaning is not their commit subject, while deleting the compulsion. Rejected on the audience answer alone. It costs two sources, a merge rule, and the `check` guard to keep the format honest — machinery held in reserve for a reader who does not exist. This is the alternative to restore first if that changes.
- **Delete the presence guard only, keep fragments optional (Option C).** A much smaller change that removes the ceremony and the exemption rate. Rejected because it leaves no backstop: an entry that should have been written simply vanishes and nothing notices. Commit-derivation is what makes forgetting recoverable.
- **Make the exemption machine-verifiable** (tie a fragment to its change). Considered and rejected on its own terms before this proposal: there is no reliable source for "this change's ticket" that survives CI, a shallow checkout, or a detached `promote` worktree, and `require` already abstains three ways for exactly that class of unknowability. It would also overrule `RELEASING.md`'s stated position that the enforcement *is* reviewer visibility. Moot under this decision.

## Consequences

- **Commit subjects become load-bearing.** They already are, at 80/80, but under a convention nothing enforces mechanically. A sloppy subject becomes a sloppy changelog line where today it is invisible. Deliberately **not** answered with a subject-format guard: that would move the compulsion rather than remove it. The release editor fixes it by hand, and if that proves untenable it is evidence the saving was smaller than claimed.
- **A derived entry is written for the wrong audience by default.** The claim that one human editing pass at release corrects this is untested here, because no release has occurred under any of these systems.
- **#287 becomes dead code and is deleted with the rest.** It shipped 2026-08-04, hours before this decision, and was a correct fix to a real defect. Its necessity — a reserved filename class invented to accommodate the process's own outputs — is the clearest single symptom this ADR acts on. The reasoning is preserved in the deleting change's commit body; the mechanism is not.
- **Three records of history remain unreconciled** — `README.md`'s era summary, `CHANGELOG.md`'s 12 frozen entries, `CHANGELOG-archive/2026.md`'s 74. This decision makes one of them cheaper to produce and consolidates none. Given the audience answer, that consolidation may be the more valuable change; it is deliberately left to its own proposal rather than smuggled in here, which would repeat the error being corrected.
- **The pending window must be drained before the machinery that reads it is deleted.** `CHANGELOG.md` has 4 lines and 577 bytes of headroom against its ratchet and the window holds 24 fragments, so the fold's output almost certainly lands in `CHANGELOG-archive/2026.md` with the ratchet re-baselined. Ordering is not optional: delete `fold` first and the 24 fragments become unreadable by anything but hand.
