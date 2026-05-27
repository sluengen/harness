# Verification Before Completion

This skill applies to every agent, every task, every handoff. It is the final gate before claiming work is done.

## The Rule

**No completion claims without fresh verification evidence.**

Any statement that implies work is finished — "done", "fixed", "passing", "ready for review", "all tests green", "implemented" — requires that you have **just run** the verification command and **read the output** in this session.

## The Gate

Before any positive status claim, follow these steps in order:

1. **Identify** — what command proves the claim? See the table below.
2. **Execute** — run the command. Now. Not "I ran it earlier." Fresh execution.
3. **Read** — read the complete output. Exit codes, pass/fail counts, error messages.
4. **Verify** — does the output actually support the claim? "5 passed" means passed. "5 passed, 1 warning" means investigate the warning. "5 passed, 1 skipped" means explain the skip.
5. **Then claim** — only after steps 1-4 can you say "done" or "passing."

Skipping any step is dishonest, not efficient.

## What counts as verification

| Claim | Required verification |
|---|---|
| "Tests pass" | `uv run pytest`. Show the output. |
| "Lint clean" | `uv run ruff check .`. Show the output. |
| "Types check" | `uv run mypy harness`. Show the output. |
| "Bug is fixed" | Run the regression test. Show it passing. |
| "Feature implemented" | Run the acceptance tests. Show them passing. |
| "Ready for review" | All three (lint, types, tests). |

## Order matters: lint → types → tests

Run them in this order. Each is a blocker:

1. **Lint first.** `ruff check .` is fast (sub-second) and catches the cheap issues. Don't waste time running tests against unlinted code.
2. **Types second.** `mypy harness` (strict mode) catches contract mismatches. Faster than tests, slower than lint.
3. **Tests last.** `pytest` is the slowest. Run it once everything above is green.

## Common rationalisations (all invalid)

| Rationalisation | Why it's wrong |
|---|---|
| "Should work now" | Confidence is not evidence. Run the test. |
| "I just ran it a few steps ago" | Code has changed since then. Run it again. |
| "The linter passed, so it's fine" | The linter doesn't check logic. Run the tests too. |
| "The sub-agent said it passed" | Verify independently. Trust but verify. |
| "Trivial change, can't break anything" | Trivial changes break things all the time. Run the test. |

## For dev agents

Before signalling ready for review:

```bash
uv run ruff check .       # must be clean
uv run mypy harness       # must be clean (strict mode)
uv run pytest             # must pass — every collected test, no skips left unexplained
```

Read each command's output. Confirm zero errors, zero warnings, zero unexplained skips.

### Bash output capture: known workaround

The Claude Code Bash tool sometimes auto-backgrounds long-running commands like `uv run pytest` and reports `(Bash completed with no output)` even though the test ran. The workaround that has been confirmed to work in this repo:

```bash
.venv/bin/python -m pytest -q > /tmp/pytest.txt 2>&1 ; tail -10 /tmp/pytest.txt
```

Redirect to a file, then read the file. This avoids whatever buffering quirk causes the empty-output behaviour. Same pattern works for `ruff` and `mypy`. Use the venv's binaries directly (`.venv/bin/python`, `.venv/bin/ruff`, `.venv/bin/mypy`) rather than `uv run` if backgrounding persists.

If you see `(Bash completed with no output)` from a verification command, do not interpret silence as success — re-run with the file-redirect pattern and read the file.

## For the reviewer

Before issuing a PASS verdict:

1. Run all three commands yourself. Don't rely on the dev agent's claim.
2. Read the output. Confirm clean.
3. If any fail, the verdict is FAIL regardless of code quality.

## What this isn't

This skill is the *running of* the evidence. Connecting it back to the original request — "this test proves AC2 is satisfied" — lives in `skills/scope-discipline.md` (Phase 4 — tie outcome back to request).
