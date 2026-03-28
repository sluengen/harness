# Verification Before Completion

This skill applies to every agent, every task, every handoff. It is the final gate before you claim work is done.

## The Rule

**No completion claims without fresh verification evidence.**

Any statement that implies work is finished — "done", "fixed", "passing", "ready for review", "all tests green", "implemented" — requires that you have **just run** the verification command and **read the output** in this session.

## The Gate

Before making any positive status claim, follow these steps in order:

1. **Identify** — What command proves your claim? (`pytest`, `vitest run`, `ruff check .`, `npm run test`, `npm run build`)
2. **Execute** — Run the command. Now. Not "I ran it earlier." Fresh execution.
3. **Read** — Read the complete output. Exit codes, pass/fail counts, error messages. All of it.
4. **Verify** — Does the output actually support your claim? "5 passed" means passed. "5 passed, 1 warning" means investigate the warning. "5 passed, 1 skipped" means explain the skip.
5. **Then claim** — Only after steps 1-4 can you say "done" or "passing."

Skipping any step is dishonest, not efficient.

## What Counts as Verification

| Claim | Required verification |
|---|---|
| "Tests pass" | Run the full test suite. Show the output. |
| "Lint clean" | Run the linter. Show the output. |
| "Bug is fixed" | Run the regression test. Show it passing. |
| "Feature implemented" | Run the acceptance tests. Show them passing. |
| "Build succeeds" | Run the build. Show clean output. |
| "Ready for review" | All of the above that apply to the task. |

## Common Rationalisations (All Invalid)

| Rationalisation | Why it's wrong |
|---|---|
| "Should work now" | Confidence is not evidence. Run the test. |
| "I just ran it a few steps ago" | You've changed code since then. Run it again. |
| "The linter passed, so it's fine" | The linter doesn't check logic. Run the tests too. |
| "The subagent said it passed" | Verify independently. Trust but verify. |
| "It's a trivial change, can't break anything" | Trivial changes break things all the time. Run the test. |

## For Dev Agents (backend-dev, frontend-dev)

Before signalling ready for review:

1. Run lint (`ruff check .` or equivalent). Fix any errors.
2. Run the full test suite. Fix any failures.
3. Read the output of both. Confirm zero errors, zero warnings, zero skipped.
4. Then and only then update the manifest status or tell the orchestrator you're done.

**Lint first, then tests.** A lint failure is a blocker — don't waste time running tests against code that won't pass lint.

## For the Reviewer Agent

Before issuing a PASS verdict:

1. Run the full test suite yourself. Do not rely on the dev agent's claim that tests pass.
2. Read the output. Confirm all tests pass.
3. If any test fails, the verdict is FAIL regardless of code quality.

## For the Orchestrator

Before updating manifest status at a handoff:

1. Confirm the completing agent ran verification (check the session transcript).
2. If there's any doubt, ask the agent to re-run and show output.
