---
name: test-driven-development
description: Use at the start of any implementation task — building a feature, fixing a bug, or writing production code. Enforces the test-first iron law — write the failing test before the implementation, watch it fail for the right reason, then write the minimal code to pass. Load before writing code, not after.
---
<!-- guidance:test-driven-development@0.5.0 -->
# Test-Driven Development

Applies to all implementation work. Not a suggestion. It is how code gets written here.

## The Iron Law

**No production code without a failing test first.**

If you write implementation before its test, delete it and start over. No exceptions for "keeping it as reference", "it's too simple", or "I'll add the test right after".

## Red-Green-Refactor

### RED — write a failing test

One minimal test that demonstrates the desired behaviour. Clear name stating what it tests. One acceptance criterion per test. Test real behaviour, not mocks, unless an external dependency forces it.

**Use real inputs, not invented ones.** Drive the test with data the production code actually produces. A test that fabricates inputs or events no live code path ever emits proves nothing about the real system — it can stay green while the branch it claims to cover never runs in production, holding dead code falsely verified. Derive fixtures from what the code under test (or its real upstream) writes, not from what you imagine it writes.

**Cover the active loop, not just its exit.** A poll/retry/follow loop needs a test that proves it stays in the loop for the live state, separate from the terminal-exit test. A single test seeding the terminal state proves only the exit — a loop that never iterates passes it. Seed the live state, advance it mid-loop, and assert the loop acted on the intermediate state before exiting.

**Cover each of a guard's conditions, not just the one that trips first.** A guard with several independent trigger conditions (refuse-vs-diverge, stale-vs-malformed, an `||` of checks) needs one test per condition, each seeded so *only* that condition fires. Prove it the same way you prove a RED: delete each condition in turn and confirm a **named** assertion goes red for it. A condition whose deletion leaves the suite green is untested, however many assertions surround it — the guard is covered, the condition is not.

### Verify RED — confirm it fails correctly

Run it. Confirm it *fails* (not errors): a syntax error is not a valid RED. The failure message must make sense ("expected X, got Y", "function not found") and must fail because the feature is missing, not because the test is broken. If it passes immediately, you are testing existing behaviour: rewrite it.

### GREEN — minimal code

The simplest implementation that makes the test pass. No features beyond what the test requires. No edge cases that are not yet tested. No optimisation. One green test, nothing more.

### Verify GREEN — confirm it passes

Run the full suite. Your new test passes, all existing tests still pass, no new warnings. If something else broke, fix it before continuing.

### REFACTOR — clean up under green

Now, and only now: remove duplication, improve names, extract helpers (per the rule of three in `code-quality`). Run tests after every change. If anything breaks, undo.

### REPEAT for the next criterion.

## Rationalisations, all invalid

| "..." | Why it is wrong |
|---|---|
| Too simple to test | Simple code breaks. The test documents the contract in seconds. |
| I'll add tests after | Tests written after pass immediately, proving nothing about intent. |
| Already tested manually | Manual testing has no record and cannot be re-run. |
| Deleting working code is wasteful | Keeping unverified code is the debt. Sunk cost. |
| TDD slows me down | TDD is faster than debugging the thing you skipped testing. |
| Need to explore first | Explore, then throw the exploration away and start RED. |

## Bug fixes follow TDD too

1. Write a failing test that reproduces the bug.
2. Confirm it fails for the right reason.
3. Fix with minimal code.
4. Confirm it passes and nothing else broke.

That test is now the regression guard. Never fix a bug without one.

## Before handoff

- [ ] Every acceptance criterion has at least one test.
- [ ] Every test was observed failing before its implementation existed.
- [ ] Tests cover error and edge cases, not just the happy path.
- [ ] The full suite passes with clean output (no warnings, no unexplained skips).

The test command is repo-specific: see `CONTEXT.md`.
