---
name: engineering
description: Use while designing, implementing, or modifying any code, and again before claiming work done. The build leg of the triad — the durable principles every change is measured against, the test-first method, scope discipline, structure, and the verification gate. The developer builds to this file; the reviewer holds the work to the same one.
---
# Engineering

How code gets built here: the principles every change is measured against, the test-first method, the scope and structure discipline, and the evidence a completion claim requires. One file for one moment — no agent builds without all of it. The reviewer enforces the same rules (`review-discipline` references this file, so the bar is identical on both sides). The principles are *stated* here and *argued* in [`references/principles.md`](references/principles.md), where rationale, worked cases, and learned examples accrete.

## The principles

Universal. A repo extends them in `CLAUDE.md` and records consequential choices as decisions in the spec they govern (`architecture`); a repo principle never contradicts one here without a recorded decision saying so.

**Simplicity over cleverness.** The reader is the constraint, not the writer. Prefer the boring solution understood in one pass.

**Smallest change that satisfies the spec.** One condition is usually enough. Removing code is often the right answer. Do not add what the task did not ask for.

**No premature abstraction.** Duplicate twice before you extract. An abstraction serving one caller is a liability, not reuse.

**Separation of concerns.** Each module owns one responsibility and one layer. Name the layer a change belongs to before editing it.

**Stable contracts, replaceable implementations.** The interface is the asset; design boundaries to outlast the code behind them.

**Validate at boundaries, trust within.** Untrusted input is checked once, at the edge, then flows as validated data.

**Design for extension, not speculation.** Leave room to add; do not build the addition until it is asked for.

**Atomic, reversible increments.** Every commit leaves the project working. A change you cannot revert in one step is too big.

**Tests own the state they mutate.** The suite provisions its own instance and disposes of it; it never borrows state that outlives the run.

**Minimal dependencies.** Every dependency is a standing cost and must earn its keep.

**Make the right thing the easy thing.** When you find yourself adding a rule, ask whether structure could make the rule unnecessary.

**Errors surface, never swallowed.** A silently discarded exception is a bug in waiting. Handle it, or let it propagate.

### Before you write it

Walk the rungs in order and stop at the first that holds: does this need to exist at all → does the standard library do it → does a native platform feature cover it → does an installed dependency solve it → can it be one line → only then, the minimum code that works. The ladder governs *what to build*, never whether to test or what the spec requires: it does not license skipping the failing test, and it does not license trimming an acceptance criterion.

### Trade-offs are conscious, not silent

The principles pull against each other; resolving the tension is the work. When a change knowingly relaxes a principle, record the decision (architecture-principles spec for cross-cutting, the change spec for local) rather than drifting. The reviewer treats principle violations as findings and cites the principle, not a preference.

## Evidence before implementation

ADR 0019 is the sole evidence matrix. Before implementation, name what the change protects and use its native or cheapest adequate evidence. For executable behaviour and mechanically enforceable invariants, begin RED and make the smallest GREEN; for a runtime or compatibility floor, provide its declaration and functional execution on every supported environment. Review prose directly, never with a predicate or wording guard, and do not duplicate producer evidence in a consumer.

Challenge a criterion whose outcome, target, or evidence is wrong before implementation: provide evidence and a smaller replacement, obtain the owner's approval, and amend the tracker issue. Never descope silently. This is a reasoning rule, not a new form or score.

## Test-first

**No production code without a failing test first.** If you wrote implementation before its test, delete it and start over — no exceptions for "too simple", "as reference", or "right after".

- **RED.** One minimal test demonstrating the desired behaviour; one criterion per test; real behaviour over mocks unless an external dependency forces it. Drive it with inputs the production code actually produces, not invented ones — a test feeding events no live path emits proves nothing and holds dead code falsely verified.
- **Verify RED.** Run it; confirm it *fails*, not errors, and fails because the feature is missing. A test that passes immediately is testing existing behaviour — rewrite it.
- **GREEN.** The simplest code that passes. No untested edge cases, no optimisation.
- **Verify GREEN.** Full suite; new test passes, nothing else broke, no new warnings.
- **REFACTOR under green**, then repeat for the next criterion.

Bug fixes follow the same loop — the reproducing test written first is the regression guard, and no bug is fixed without one. Loops need a test that proves they *stay* in the loop for the live state, separate from the terminal-exit test. A guard with several independent trigger conditions needs one test per condition, proven by deleting each condition and watching a named assertion go red. A new lifecycle stage is exercised under every configuration the repo claims to support, not only its own unit suite. Every rationalisation for skipping any of this is catalogued in [`references/principles.md`](references/principles.md) — all invalid.

## Scope

**Read first. Touch only what the task requires. Defer everything else.**

- Before editing: read the canonical files (spec, target modules, one call site); name the current pattern in one sentence; confirm the task targets that pattern. If you cannot name it, read more. If the task and the code disagree on where the change belongs, surface it before editing.
- Bound the surface: a file is **required** (the task cannot complete without it) or **tempting** (nearby, slightly wrong, "while I'm here") — leave tempting alone. No renames in untouched paths, no reformatting files you did not need to open, no committing files another session left in `git status`.
- A function returning placeholder data must not be reachable from a live control except behind an off-by-default flag — wire the flag or remove the control.
- Grep before writing a helper: one existing near-copy is named and justified in the change spec; two means extract — the third copy is not a judgement call.
- When a generator already writes the fact you need to a committed, drift-guarded artifact, read the artifact; never re-derive from its inputs.
- **A removal sweeps for its dependents** — grep the removed name and update every handler, config key, and doc that pointed at it; the diff of a removal includes its dependents. **An extraction sweeps for its copies** — grep the whole tree, and diff every copy against the canonical body before deleting it: a copy that *differs* is the finding, not the leftover.
- Out-of-scope discoveries are carried forward in the handoff, not fixed silently — except a reviewer-flagged small fix on code you already touched, which you do in the same pass.

## Structure

Defaults; a repo overrides numbers in `CLAUDE.md`, the principles do not change.

| Unit | Soft | Hard |
|---|---|---|
| Module / file | 300 lines | 500 (justify near the top, or ticket) |
| Function / handler | 40 lines | 60 |

Declarative files (schemas, token maps) default to 1.5× the hard limit, declared as a linter override in the same change that mechanizes the rule. [`references/size-guard.md`](references/size-guard.md) is a ready-to-adopt test enforcing the justification tripwire mechanically.

- Maintain the repo's declared layer separation; no business logic in transport, no transport concepts in services, no queries outside the data layer.
- **Extract on the third strike** — twice is coincidence. A permission check or domain rule that must stay in sync extracts on the **second** copy. A comment admitting a unit "mirrors" or "must be kept in sync with" a sibling is the third strike on its own, whatever the copy count.
- Top-level units compose; they do not inline 500 lines of rendering or 50 fields of parsing.

For fetches of URLs derived from user input or page-declared content, load [`references/untrusted-fetch.md`](references/untrusted-fetch.md). For security-control tests, over-limit files, guards over derived sets, cross-layer aggregates, or nullable narrowing, load [`references/specialized-verification.md`](references/specialized-verification.md) and apply the matching section.

## Verification

**No completion claim without fresh evidence** — the spine's third law, operationalised:

1. Identify the command that proves the claim (`CLAUDE.md` commands). 2. Execute it *now* — "I ran it earlier" is not evidence, you have changed code since. 3. Read the full output. 4. Verify the output supports the claim — "5 passed, 1 skipped" means explain the skip. 5. Then claim. Lint before types before tests; do not run the slow gate on code the fast gate rejects.

| Claim | Required evidence |
|---|---|
| Tests pass | Full suite run, output read |
| Bug fixed | The regression test, shown passing |
| Measurable criterion met | A test that **measures the quantity** and asserts the bound — a structural change that ought to reduce it is not proof it did |
| Ready for review | All of the above that apply |

- **A new guard cites the occurrence it prevents** — the craft-file entry or the incident where its defect class was observed, written beside the assertion. A guard nobody can trace to an occurrence is speculative, and an assessment may read it as a deletion candidate.
- **A guard that regenerates its reference pins the generator in the same commit, and a guard whose failure mode is warn-and-pass has not been shown to run until it has failed once for the real reason** — an unpinned generator makes a green a fact about the runner as much as about the tree (`review-discipline` craft: *A regenerated reference measures the generator, not the tree*), and a warn-and-pass path exits green without having compared anything, so its result is indistinguishable from a real pass and "it passed locally" can be true and mean nothing.
- **A guard owns only a mechanically decidable contract** — artifact integrity, generated-output correspondence, and other executable or structural properties can fail a check. Do not add a prose predicate, wording guard, vocabulary test, or pinned sentence to judge meaning; review prose directly.
- **A green suite is only evidence if its inputs are real** — a test driving on synthesized events no production path emits exercises a branch the live system never reaches.
