# Test-Driven Development

This skill applies to all implementation work — backend and frontend. It is not optional. It is not a suggestion. It is how code gets written in this project.

## The Iron Law

**No production code without a failing test first.**

If you write implementation code before its test, delete it and start over. No exceptions for:
- "Keeping it as reference"
- "Adapting existing code while testing"
- "It's too simple to need a test"
- "I'll add the test right after"

## Red-Green-Refactor Cycle

### RED: Write a failing test

Write one minimal test that demonstrates the desired behaviour. The test must:
- Have a clear, descriptive name that states what it tests
- Test actual behaviour, not mocks (unless external dependency makes this impossible)
- Focus on a single acceptance criterion or behaviour

### Verify RED: Confirm it fails correctly

Run the test. Confirm:
- The test **fails** (not errors — a syntax error is not a valid RED)
- The failure message makes sense ("expected X, got Y" or "function not found")
- It fails because the feature is missing, not because the test is broken

If the test passes immediately, you're testing existing behaviour — rewrite it.

### GREEN: Write minimal code

Write the simplest implementation that makes the test pass:
- Do not add features beyond what the test requires
- Do not refactor surrounding code
- Do not optimise
- Do not handle edge cases that aren't tested yet

The goal is one green test, nothing more.

### Verify GREEN: Confirm it passes

Run the full test suite. Confirm:
- Your new test passes
- All existing tests still pass
- No warnings or errors in the output

If other tests broke, fix them before moving on.

### REFACTOR: Clean up

Now — and only now — clean up:
- Remove duplication
- Improve names
- Extract helpers
- Simplify logic

Run tests after every change. If anything breaks, undo the refactor.

### REPEAT

Start the next RED phase for the next acceptance criterion.

## Common Rationalisations (All Invalid)

| Rationalisation | Why it's wrong |
|---|---|
| "Too simple to test" | Simple code breaks. Testing takes seconds. The test documents the contract. |
| "I'll add tests after" | Tests written after pass immediately, proving nothing. They test what the code does, not what it should do. |
| "Already manually tested" | Manual testing has no record, can't be re-run, and will be forgotten. |
| "Deleting working code is wasteful" | Keeping unverified code is technical debt. Sunk cost fallacy. |
| "TDD slows me down" | TDD is faster than debugging. Every "quick fix" that skips TDD eventually costs 3x in rework. |
| "Need to explore first" | Explore, then throw away the exploration and start TDD fresh. |
| "The test is obvious" | Then it takes 30 seconds to write. Do it. |

## Red Flags: Stop and Restart

If you catch yourself doing any of these, delete the implementation code and restart from RED:

- Writing code before tests
- Tests that pass immediately on first run
- Tests added after the implementation is "done"
- Rationalising "just this once"
- Unable to explain why a test initially failed
- Multiple behaviours tested in a single test

## Bug Fixes Follow TDD Too

When fixing a bug:
1. Write a failing test that reproduces the bug
2. Confirm it fails for the right reason
3. Fix the bug with minimal code
4. Confirm the test passes
5. Confirm all other tests still pass

This test becomes the regression test. Never fix a bug without one.

## Verification Before Handoff

Before signalling ready for review, verify:
- [ ] Every acceptance criterion has at least one test
- [ ] Every test was observed failing before the implementation was written
- [ ] Tests cover error cases and edge cases, not just happy paths
- [ ] Full test suite passes with clean output (no warnings, no skipped tests)
- [ ] Lint passes (`ruff check .` for Python, `vitest run` for frontend)
