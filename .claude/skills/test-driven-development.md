# Test-Driven Development

This skill applies to all implementation work in slate-harness. It is not optional. It is how code gets written here.

## The Iron Law

**No production code without a failing test first.**

If you write implementation code before its test, delete it and start over. No exceptions for:
- "Keeping it as reference"
- "Adapting existing code while testing"
- "It's too simple to need a test"
- "I'll add the test right after"

## Red-Green-Refactor

### RED: Write a failing test

One minimal test that demonstrates the desired behaviour. The test:
- Has a clear, descriptive name (`test_state_store_appends_to_list_field`, not `test_works`).
- Tests actual behaviour, not mocks (mock only when an external dependency makes real calls infeasible).
- Focuses on a single acceptance criterion.

### Verify RED: Confirm it fails

Run the test. Confirm:
- It **fails** (a syntax error is not a valid RED — the test must execute and assert wrong).
- The failure message makes sense ("expected X, got Y" or "function not found").
- It fails because the feature is missing, not because the test is broken.

If the test passes immediately, you're testing existing behaviour. Rewrite it.

### GREEN: Write minimal code

The simplest implementation that makes the test pass. Do not:
- Add features beyond what the test requires.
- Refactor surrounding code.
- Optimise.
- Handle edge cases that aren't tested yet.

The goal is one green test, nothing more.

### Verify GREEN: Confirm it passes

```bash
uv run pytest <path-to-new-test-file>
```

Then run the full suite to confirm nothing else broke:

```bash
uv run pytest
```

### REFACTOR: Clean up

Now — and only now — clean up:
- Remove duplication.
- Improve names.
- Extract helpers.
- Simplify logic.

Run `pytest` after every refactor step. If anything breaks, undo.

### REPEAT for the next AC

## Bug fixes follow TDD

When fixing a bug:
1. Write a failing test that reproduces the bug.
2. Confirm it fails for the right reason.
3. Fix the bug with minimal code.
4. Confirm the test passes.
5. Confirm the full suite still passes.

The reproduction test becomes the regression test. **Never fix a bug without a regression test.**

## Common rationalisations (all invalid)

| Rationalisation | Why it's wrong |
|---|---|
| "Too simple to test" | Simple code breaks. Tests take seconds. They document the contract. |
| "I'll add tests after" | Tests written after pass immediately, proving nothing. They test what the code does, not what it should do. |
| "Already manually tested" | Manual testing has no record, can't be re-run, and will be forgotten. |
| "Deleting working code is wasteful" | Keeping unverified code is technical debt. Sunk cost fallacy. |
| "TDD slows me down" | TDD is faster than debugging. Every "quick fix" that skips TDD costs 3x in rework. |
| "Need to explore first" | Explore in a scratch file, throw it away, then start TDD fresh. |
| "The test is obvious" | Then it takes 30 seconds. Do it. |

## Red flags — stop and restart

If you catch any of these, delete the implementation and restart from RED:

- Writing code before tests.
- Tests that pass immediately on first run.
- Tests added after the implementation is "done".
- Multiple behaviours tested in one test.
- Unable to explain why a test initially failed.

## Verification before handoff

Before signalling ready for review:

- [ ] Every acceptance criterion has at least one test.
- [ ] Every test was observed failing before the implementation was written.
- [ ] Tests cover error and edge cases, not just happy paths.
- [ ] Full suite passes with clean output (no warnings, no skipped tests).
- [ ] Lint and types pass: `uv run ruff check .` and `uv run mypy harness`.

See `.claude/skills/verification-before-completion.md` for the full gate.
