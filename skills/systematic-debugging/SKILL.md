---
name: systematic-debugging
description: Use whenever you hit a failing test, unexpected behaviour, or a bug report — reproduce, isolate the root cause, fix minimally, prove it fixed. Load instead of guessing at a fix; pairs with engineering's test-first loop for the regression test.
---
# Systematic Debugging

Applies whenever you hit a failing test, unexpected behaviour, or a bug report. Do not guess at fixes.

## The Rule

**No fix without root-cause investigation first.**

Proposing a solution before you can state the root cause is a process violation. The urge to "just try this" is the single largest source of wasted debugging time: a fix that addresses a symptom on the wrong layer creates two bugs where there was one.

## Phase 1 — Investigate

Before touching implementation code:

1. **Read the error.** The full message, stack trace, and logs. Not a summary — the actual output.
2. **Reproduce consistently.** Trigger the failure on demand. If you cannot reproduce it, you cannot verify a fix.
3. **Check recent changes.** What changed since this last worked? `git log`, `git diff`, recent commits on the branch.
4. **Trace the data flow.** Follow the input from entry point to the failure. Find the exact line where actual diverges from expected.
5. **Gather evidence.** Note what the input was, what was expected, what actually happened, and where they diverge.

Do not proceed until you can complete this sentence: **"The failure occurs at [location] because [specific observation]."** A hypothesis is not a root cause until the evidence forces it.

## Phase 2 — Fix, test-first

Once the cause is known, the fix follows `engineering`:

1. **Write a failing test that reproduces the bug.** This proves you understand the cause and becomes the regression guard.
2. **Confirm it fails for the right reason** — the cause you identified, not a different one.
3. **Fix with the minimal change** (`engineering`: smallest working solution). Fix the cause, not the symptom.
4. **Confirm the test passes and nothing else broke.**

## Anti-patterns

- Changing code to see if it helps, without a hypothesis. That is not debugging; it is guessing.
- "Fixing" by adding a catch that swallows the error (`engineering`: errors surface).
- Patching the symptom at the call site when the cause is in the callee.
- Declaring it fixed because it no longer reproduces *once*. Reproduce the fix as deliberately as you reproduced the bug.

## When you are truly stuck

Widen the evidence, do not narrow the guesses: add logging at the boundaries, bisect the history (`git bisect`), or reduce to the smallest failing case. State what you have ruled out. The answer is in the evidence you have not looked at yet.
