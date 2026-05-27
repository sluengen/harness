# Code Review

Procedure and standards for the reviewer agent. Two stages: acceptance compliance, then quality.

## Stage 1 — Acceptance Compliance

Read the Linear issue's acceptance criteria. For each, can you point to:
- The implementing code (file:line)?
- The test that proves it (test file::test name)?

If any AC has no implementation OR no test, the verdict is **FAIL**. Stage 1 is binary.

For tasks that implement harness internals, read the relevant SPEC.md section. If the implementation diverges from the spec without a documented reason, flag it — either the code is wrong, or the spec needs updating.

## Stage 2 — Quality

Walk every dimension. Score findings by severity:

| Severity | Meaning |
|---|---|
| CRITICAL | Blocks merge. Security holes, data loss, contract violations, broken tests. |
| HIGH | Blocks PASS verdict. Fix in this PR. Missing AC test coverage; > 20 LOC of unrelated diff; mypy errors. |
| MEDIUM | Fix in this PR (1-5 line touch on already-modified files). Missing docstring on a public API; suboptimal but correct algorithm. |
| LOW | Carry-forward unless trivial. Style preferences; naming nits. |

**Fix-now rule:** MED/LOW on already-touched files get fixed in the same PR. Carry-forward only for genuinely out-of-scope follow-ups.

## Dimensions

### Acceptance compliance (3x weight)

For each AC: implementation present? Test present? Test runs?

### TDD compliance (3x weight)

- Were tests written first? Check commit shape: tests before implementation, or interleaved test-then-impl, NOT all tests at the end.
- Do tests cover error and edge cases, not just happy paths?
- Are tests independent — would they pass if reordered?

### Type safety (2x weight)

- `uv run mypy harness` runs clean in strict mode.
- No silent `Any` unless justified with `# type: ignore[<rule>]` and a reason.
- Pydantic models at boundaries (workflow load, contract validation, dispatch input/output).

### Scope discipline (2x weight)

Per `skills/scope-discipline.md`:

- Every modified file traces to the task — no "while I was there" edits.
- No speculative refactors or new abstractions the task didn't require.
- `git diff --stat` should look surgical relative to the AC.

### Spec alignment (2x weight, when applicable)

For changes implementing harness internals (anything under `harness/`):

- Does the change match what `SPEC.md` describes?
- If it diverges, is the divergence intentional and justified? Surface it.
- If the spec is wrong, flag it as a follow-up issue, don't silently let the code drift.

### Security (2x weight)

- All external input (workflow YAML, CLI args, agent output) validated via Pydantic before use.
- No `eval`, `exec`, `pickle` on untrusted data.
- Subprocess calls use list-form args, never `shell=True` with user input.
- Path operations validate inside expected prefix.
- Secrets from env vars only; never logged or committed.

### Code structure

- Modules align with SPEC §3 (one responsibility per module).
- No cyclic imports between top-level packages.
- Functions stay short (~50 LOC unless cyclomatic complexity is genuinely needed).
- Public APIs have docstrings; the `WHY` is captured when non-obvious.

### Verification

You run all three yourself before issuing the verdict — don't rely on the dev's claim:

```bash
uv run ruff check .
uv run mypy harness
uv run pytest
```

If any fail, verdict is FAIL.

## Verdict Format

```markdown
# Review: <task-id>

**Verdict:** PASS | FAIL

## Acceptance criteria
- [✓] AC1 — implemented at `harness/foo.py:42`, tested by `tests/unit/test_foo.py::test_bar`
- [✗] AC2 — no implementation found
...

## Verification
- ruff: clean
- mypy: clean
- pytest: 23 passed, 0 failed

## Findings

### CRITICAL
- (none)

### HIGH
- `harness/foo.py:67` — eval used on user-provided expression. Replace with AST whitelist.

### MEDIUM
- `tests/unit/test_foo.py::test_baz` — covers happy path only; add a test for malformed input.

### LOW
- `harness/foo.py:23` — variable `x` could be more descriptive.

## Notes
Brief commentary on overall quality, suggestions, follow-up issues to file.
```

## Repeated FAIL escalation

If a review goes FAIL twice on the same task:

- **Stop the review loop.**
- **Surface the blocking issues to the user** with the latest verdict.
- The user decides whether to keep iterating or change scope.

Don't keep spinning — repeated FAIL is signal that something needs human judgement.

## What the reviewer doesn't do

- Doesn't write code. Reads it.
- Doesn't make architectural decisions. Surfaces divergence; user decides.
- Doesn't accept "I'll add tests later." That's an automatic FAIL.
- Doesn't pass with warnings. Either it's clean or it's FAIL.
