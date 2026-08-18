# Principles, argued

The elaboration behind `SKILL.md`'s stated principles: rationale, worked cases, and the learned examples that earned each rule its place. **Admission rule:** an entry here names the occurrence that produced it — the incident, ticket, or red gate — or it does not land. This file is where the build leg *learns*; the body stays the working surface.

## Why the ladder ends at "minimum code that works"

Most needs die on an earlier rung. A speculative need is no need (rung 1) — the cheapest code is the code never written, and "we might need it" ages into unowned surface faster than it ages into value. The standard library and platform rungs exist because hand-rolled reimplementations of `pathlib`, retry loops, and date handling are where a disproportionate share of subtle defects live. When two rungs both hold, take the higher: the ladder is a reflex, not a research project.

## Rationalisations against test-first, all invalid

| "..." | Why it is wrong |
|---|---|
| Too simple to test | Simple code breaks. The test documents the contract in seconds. |
| I'll add tests after | Tests written after pass immediately, proving nothing about intent. |
| Already tested manually | Manual testing has no record and cannot be re-run. |
| Deleting working code is wasteful | Keeping unverified code is the debt. Sunk cost. |
| TDD slows me down | TDD is faster than debugging the thing you skipped testing. |
| Need to explore first | Explore, then throw the exploration away and start RED. |

## Worked cases

**Placeholder stubs reaching live surfaces.** Two instances one day apart in one repo — a share-card stub and an OCR stub, both wired to live, ungated CTAs, both filed after the fact rather than caught at merge. The rule (off-by-default flag or remove the control) was codified on the second instance rather than waiting for a third.

**Re-deriving what a generator already writes.** Two implementations of one screen-graph consumer, a week apart, against one generated flow graph: the one reading the committed artifact picked up new routes for free; the one re-parsing the source drifted within three tickets. The drift test guards the artifact, not your derivation — a second derivation needs its own hand-maintained inventory, told about new inputs only when someone remembers.

**The extraction that certifies a unification that did not happen.** A surviving copy with a divergent body is strictly worse than the duplication the extraction set out to remove: the green diff now testifies that the tree is unified when it is not. Hence the rule — diff every found copy against the canonical body *before* deleting it; a differing copy is the finding.

**The sync-comment as the third strike.** The rule-of-three cannot see a duplication whose copies are each individually tiny. A comment saying "keep in sync with X" names the original outright — the admission is the trigger, not the size.

## Testing the state you mutate

Real infrastructure is the right call, but a suite pointed at a shared database or live account eventually destroys work that mattered — and until it does, it accretes cleanup workarounds for its own residue. Structural isolation (the suite provisions and disposes of its own instance) beats a rule everyone has to remember, which is the *make the right thing the easy thing* principle applied to the test bed.
