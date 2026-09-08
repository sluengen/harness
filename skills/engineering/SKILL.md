---
name: engineering
description: Use while designing, implementing, or modifying any code, and again before claiming work done. The build half of how and what — the durable principles every change is measured against, the test-first method, scope discipline, structure, and the verification gate. The developer builds to this file; the reviewer holds the work to the same one. Not for deciding whether the work should happen, or for reviewing someone else's diff — those are the spine's lifecycle and `review-discipline`.
model: inherit
---
# Engineering

The principles a change is measured against, the test-first method, scope and structure discipline, and the evidence a completion claim requires. The reviewer applies the same rules, so the bar is identical on both sides.

Load [`references/principles.md`](references/principles.md) when you want the rationale or the worked case behind a rule, not to apply the rule.

## The principles

Universal. A repo extends them in `AGENTS.md` and records consequential choices as decisions in the spec they govern (`architecture`); a repo principle never contradicts one here without a recorded decision saying so.

| Principle | Because |
|---|---|
| Simplicity over cleverness | The reader is the constraint, not the writer. |
| Smallest change that satisfies the spec | One condition is usually enough, and removing code is often the right answer. |
| No premature abstraction | An abstraction serving one caller is a liability, not reuse. Duplicate twice before extracting. |
| Separation of concerns | Each module owns one responsibility and one layer. Name the layer before editing it. |
| Stable contracts, replaceable implementations | The interface is the asset; boundaries should outlast the code behind them. |
| Validate at boundaries, trust within | Untrusted input is checked once, at the edge, then flows as validated data. |
| Design for extension, not speculation | Leave room to add; do not build the addition until it is asked for. |
| Atomic, reversible increments | A change you cannot revert in one step is too big. |
| Tests own the state they mutate | The suite provisions its own instance; it never borrows state that outlives the run. |
| Minimal dependencies | Every dependency is a standing cost and must earn its keep. |
| Make the right thing the easy thing | When you find yourself adding a rule, ask whether structure could make it unnecessary. |
| Errors surface, never swallowed | A silently discarded exception is a bug in waiting. |

Before writing anything, stop at the first rung that holds: does this need to exist → does the standard library do it → does a native platform feature cover it → does an installed dependency solve it → can it be one line → only then, the minimum code that works. The ladder governs *what to build*; it never licenses skipping the failing test or trimming a criterion.

Resolving the tension between principles is the work. When a change knowingly relaxes one, record the decision — architecture-principles spec for cross-cutting, change spec for local — rather than drifting.

## Evidence before implementation

ADR 0019 is the sole evidence matrix. Name what the change protects, then use its cheapest adequate evidence: executable behaviour and mechanically enforceable invariants begin RED and reach the smallest GREEN; a runtime floor needs its declaration plus functional execution on every supported environment. Review prose directly, and do not duplicate producer evidence in a consumer.

### Interrogate the criterion before you satisfy it

Satisfying a wrong criterion costs more than challenging it. Two checks, in order.

*Is the quantity the outcome, or a proxy for it?* If a change could move the number without moving what the number stands for, the criterion is defective. "This module drops below 300 lines" is satisfied by shifting the overflow into a sibling, which pushes reader-load sideways rather than down. Name the outcome the number stood for, propose that instead, amend the ticket. Being forced to write a line-counting test is the tell that the number was never the requirement.

*Is the evidence reachable by whoever produces it?* A criterion needing a credential this run has not got, a second backend, a board it cannot write, or an operator at a keyboard cannot be closed by building. Say so at the criterion, and name who produces the evidence and when.

Challenge a wrong criterion **before** implementing: give the evidence, offer a smaller replacement, get the owner's agreement, amend the tracker issue. Never descope silently, and never leave the rationale in a commit body — the ticket is the canonical record, so a Done ticket whose current criteria the diff did not meet is false.

## Test-first

No production code without a failing test first. If you wrote implementation before its test, delete it and start over; there is no exemption for "too simple" or "right after".

- *RED* — one minimal test, one criterion, real behaviour over mocks unless an external dependency forces otherwise. Drive it with inputs production actually produces: a test fed events no live path emits holds dead code falsely verified.
- *Verify RED* — confirm it *fails* rather than errors, and fails because the feature is missing. A test that passes immediately is testing existing behaviour.
- *GREEN* — the simplest code that passes. No untested edge cases, no optimisation.
- *Verify GREEN* — full suite: new test passes, nothing else broke, no new warnings.
- *Refactor under green*, then repeat for the next criterion.

A bug fix starts with the root cause: *the failure occurs at [location] because [observation]*, on evidence — the full error, a reproduction you can trigger on demand, what changed since it last worked. Changing code to see if it helps is guessing, and a fix aimed at a symptom on the wrong layer makes two bugs out of one. The reproducing test written first is the regression guard, and it must fail for the cause you named. When stuck, widen the evidence rather than narrowing the guesses.

Three shapes need more than one test: a loop needs proof it *stays* in the loop, separate from the terminal-exit test; a guard with independent trigger conditions needs one test per condition, proved by deleting each and watching a named assertion go red; a new lifecycle stage is exercised under every configuration the repo supports.

## Scope

Read first. Touch only what the task requires. Defer everything else.

- Name the current pattern in one sentence and confirm the task targets it. If you cannot name it, read more. If task and code disagree about where the change belongs, surface it first.
- A file is *required* — the task cannot complete without it — or *tempting*. Leave tempting alone: no renames in untouched paths, no reformatting files you did not need to open, no committing files another session left in `git status`.
- A function returning placeholder data must not be reachable from a live control except behind an off-by-default flag.
- Grep before writing a helper. One near-copy is named and justified in the change spec; two means extract.
- When a generator already writes the fact you need to a drift-guarded artifact, read the artifact rather than re-deriving it.
- An extraction sweeps for its copies, and a copy that *differs* is the finding, not the leftover.
- Out-of-scope discoveries are carried forward in the handoff, not fixed silently — except a reviewer-flagged small fix on code you already touched.

### A retirement sweeps for every home of what it retired

A removal sweeps for its dependents: grep the removed name and update every handler, config key and document that pointed at it. The diff of a removal includes its dependents.

A retired *claim* needs the same sweep and cannot use the same instrument. When a change makes a sentence false — an absolute like "this never pushes", a stated count, a described mechanism — there is no identifier to grep, so grep the retired phrase and the mechanism it described. Three things this needs which a name-sweep does not:

- *A docstring is a home*, as are section comments, manifests, fixture names and specs. The homes that survive are the ones nobody thought to open.
- *Derive the count; never remember it.* Report *n* homes because you just counted *n*. A recorded count is itself a claim, and a stale one hides the survivor.
- *Enumerate before repairing.* Fixing the instances a reviewer showed you leaves the siblings that reviewer did not see, and the next cycle finds one. Sweep the branch, fix the set, put the grep and its hits on the ticket.

Measured: three consecutive tickets spent most of their review budget on this class, and one found the same retired sentence in a third cycle, in a docstring the second cycle's repair had not reached.

## Structure

Defaults; a repo overrides the numbers in `harness.yaml`.

| Unit | Soft | Hard |
|---|---|---|
| Module / file | 300 lines | 500 (justify near the top, or ticket) |
| Function / handler | 40 lines | 60 |

Declarative files default to 1.5× the hard limit, declared as a linter override in the same change that mechanizes the rule. Load [`references/size-guard.md`](references/size-guard.md) when adding that tripwire guard to a repo.

- Maintain the declared layer separation: no business logic in transport, no transport concepts in services, no queries outside the data layer.
- Extract on the third strike; twice is coincidence. A permission check or domain rule that must stay in sync extracts on the *second* copy. A comment admitting a unit "mirrors" a sibling is the third strike on its own.
- Top-level units compose; they do not inline 500 lines of rendering.

Load [`references/untrusted-fetch.md`](references/untrusted-fetch.md) when fetching a URL derived from user input or page-declared content.

## Verification

No completion claim without fresh evidence. Identify the command that proves the claim, execute it *now* — "I ran it earlier" is not evidence, you have changed code since — read the full output, and confirm it supports the claim: "5 passed, 1 skipped" means explain the skip. Lint before types before tests.

| Claim | Required evidence |
|---|---|
| Tests pass | Full suite run, output read |
| Bug fixed | The regression test, shown passing |
| Measurable criterion met | A test measuring the quantity and asserting the bound — a structural change that ought to reduce it is not proof that it did |
| Ready for review | All of the above that apply |

Whether a guard is evidence at all is four further rules, in [`references/specialized-verification.md`](references/specialized-verification.md) → *What makes a guard evidence*. Load it whenever you add or edit one.

**A guard is bounded by the change it guards.** State the guard-to-change ratio in the cost line (`templates/change.md` → *Cost*); above 3 : 1 the guard needs a recorded reason naming the user outcome it protects at this repo's stage. A second defence that shares an operand with the first is not a second defence, and an addition names what it retires — including the guard it has just made redundant (P0, P2).

**A contract a consumer-owned file participates in ships with its migration.** Where a change moves a value, a variable's meaning, or a file's shape that a repo outside this one already carries a copy of, the change is not done until `/harness:init --refresh` carries the rewrite that migrates the copies — and the evidence is a run against the **real** consumer files at the commit before their hand fix, never a scratch repo written to the new shape. A scratch repo is written by whoever is proving the point and agrees with them; the shapes that break are the ones nobody thought to write down.
