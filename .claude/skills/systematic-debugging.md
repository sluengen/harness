# Systematic Debugging

This skill applies whenever you encounter a failing test, unexpected behaviour, or a bug report. Do not guess at fixes. Follow this process.

## The Rule

**No fixes without root cause investigation first.**

Proposing a solution before completing Phase 1 is a process violation. The urge to "just try this quick fix" is the single most common cause of wasted time in debugging.

## Phase 1: Investigate

Before touching any implementation code:

1. **Read the error.** The full error message, stack trace, and any logs. Not a summary — the actual output.
2. **Reproduce consistently.** Run the failing test or trigger the bug. If you can't reproduce it, you can't verify a fix.
3. **Check recent changes.** What changed since this last worked? `git log`, `git diff`, recent commits on the branch.
4. **Trace the data flow.** Follow the input from entry point through the code to where it fails. Identify the exact line where expected behaviour diverges from actual behaviour.
5. **Gather evidence.** Note: what the input was, what the expected output is, what the actual output is, and where the divergence happens.

Do not proceed to Phase 2 until you can state: "The failure occurs at [location] because [specific observation]."

## Phase 2: Analyse Patterns

1. **Find working examples.** Is there a similar feature/test/component that works correctly? What's different?
2. **Compare against references.** Check the spec, design doc, or acceptance criteria. Is the implementation supposed to behave this way?
3. **Identify dependencies.** What does the failing code depend on? Did any of those dependencies change?
4. **Check assumptions.** What does the code assume about its inputs? Are those assumptions valid?

## Phase 3: Hypothesise and Test

1. **Form a specific hypothesis.** "The bug is caused by X because Y." Not "maybe it's this."
2. **Test with the smallest possible change.** Add a log statement, print a value, change one line. Verify whether your hypothesis is correct.
3. **If the hypothesis is wrong, go back to Phase 1.** Gather more evidence. Do not stack hypotheses.

## Phase 4: Implement the Fix

1. **Write a failing test** that reproduces the bug (TDD skill applies here).
2. **Make one change.** Fix the specific root cause identified in Phase 3.
3. **Run the full test suite.** Not just the failing test — all tests. Verify nothing else broke.
4. **If the fix doesn't work, revert it.** Do not layer fixes on top of each other.

## Escalation: Three Strikes

If three fix attempts fail:

1. **Stop.** Do not try a fourth.
2. **Question the architecture.** The bug may be a symptom of a deeper design problem, not a local code issue.
3. **Document what you've tried.** Write down each attempt, what you expected, and what happened.
4. **Escalate.** Present findings to the orchestrator or user. Include: the bug, the evidence, the three attempts, and your assessment of whether this is a local fix or an architectural issue.

## Red Flags: You're Not Debugging Systematically

- Making changes before reading the error message
- Trying "quick fixes" without understanding the root cause
- Changing multiple things at once
- Not reverting failed fix attempts
- "It should work now" without running the test
- Fixing a symptom instead of the cause
- Ignoring the stack trace

## Multi-Component Debugging

When the bug spans multiple components (frontend + backend, or multiple services):

1. **Isolate which component owns the bug.** Test each independently. Use curl/manual requests to test the API. Use mock data to test the frontend.
2. **Fix the owning component first.** Don't compensate in one layer for a bug in another.
3. **Verify the integration.** After fixing the component, test the full path end-to-end.
