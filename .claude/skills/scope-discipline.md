# Scope Discipline

How to enter, contain, and exit a task without overreach. Dev agents follow this while implementing; the reviewer enforces it.

This skill is about **what you read, what you touch, and what you leave alone** — not about the structural shape of code or the verification gate.

## The Rule

**Read first. Touch only what the task requires. Defer everything else.**

Coding agents drift in two predictable ways:
1. Patching off the first plausible read of the code.
2. Reshaping nearby code that was never part of the request.

Both inflate blast radius and produce work the user did not ask for.

## Phase 1 — Read before editing

Before opening any file in edit mode:

1. **Read the canonical source for this task.** The Linear issue, the relevant SPEC.md section (if implementing harness internals), the existing module(s) you'll modify, and at least one call site if applicable.
2. **Name the current pattern in one sentence.** "This module does X by Y; the failing case is Z." If you can't articulate the pattern, you don't yet understand the code well enough to change it. Read more.
3. **Confirm the task targets that pattern.** A plausible-looking edit on the wrong layer is the most expensive bug to undo. If the task description and the code disagree on where the change belongs, surface that to the user before editing.

Skipping this phase is the canonical source of "agent fixed the symptom on the wrong layer" outcomes.

## Phase 2 — Bound the surface area

Before each edit, ask: **is this file required for the task as written?**

- **Required** = the task cannot be completed without modifying it.
- **Tempting but not required** = the file is nearby, looks slightly wrong, or "while I'm here" applies. Leave it alone.

If a tempting-but-not-required edit looks valuable, write it down as a follow-up. Do not edit it.

### Specifically, do not (unless the task asks for it):

- Rename variables, files, or functions in untouched code paths.
- Remove or rewrite comments outside the modified region.
- "Clean up" formatting, imports, or dead code in files you didn't need to open.
- Add or change tests for code unrelated to the task.
- Refactor adjacent code into shared helpers.
- Touch files that appeared in `git status` from another session.

If a file shows up in `git status` and you didn't intend to modify it, that is a signal to investigate (likely a parallel-worktree artifact or stash side-effect) — not to commit it.

## Phase 3 — Smallest working solution

Inside the bounded surface area, prefer the smallest change that satisfies the task:

- One condition is usually enough.
- Removing code is often the right answer.
- New abstractions, layers, and helpers should be justified by the task — not introduced speculatively.

This is **not** a license to leave half-finished work. If the task calls for a new helper, build it. If a primitive doesn't exist for a concept and you need it for this task, build it in the same PR. The rule is: don't add what wasn't asked for, but do build what the task actually requires.

## Phase 4 — Tie the outcome back to the request

Before signalling done:

1. **Restate what the task asked for** in one sentence.
2. **Restate what you changed** in one sentence per modified file.
3. **Name the evidence** — the failing test that now passes, the AC that's now satisfied, the bug repro that no longer reproduces.

If you cannot draw a straight line from request → change → evidence, the task is not done.

## Carry-forward, not silent cleanup

When you notice something worth fixing that is out of scope:

- **Do not fix it silently.** Even a "tiny" unrelated edit increases blast radius.
- **Note it for the reviewer or user.** A line in the PR description or a comment to the user is enough. They decide whether it becomes a follow-up Linear issue.
- **In-scope MED/LOW review findings are different.** If the reviewer flags a 1-5 line fix on a file you already touched, do it in the same pass. That's the fix-now rule and it doesn't contradict this skill. The distinction: pre-review speculative cleanup is out; post-review feedback on touched files is in.

## Red flags

You are violating scope discipline if:

- You started editing before you could name the existing pattern in one sentence.
- Your diff includes files you didn't need to read for the task.
- You renamed, reformatted, or removed something "while you were there".
- You introduced a helper, hook, or abstraction the task did not require.
- Your handoff cannot explain how each modified file ties back to the request.
- You committed files that appeared in `git status` from a previous session without verifying they belonged to this task.

## What the reviewer checks

The "Scope Discipline" dimension (2x weight) maps onto this skill:

1. **Diff surface area** — every modified file should trace to the task. Files modified for "tidiness" without spec/AC backing are MED; substantial unrelated edits are HIGH.
2. **Pre-edit reading** — the dev's handoff should demonstrate they understood the pattern before editing (references the existing call site, names the layer they targeted). Patches that fix a symptom on the wrong layer are HIGH.
3. **Smallest working solution** — new abstractions or refactors the spec did not require are MED with "extract only when justified" feedback.
4. **Outcome traceability** — every claimed completion should map to evidence (test, AC, repro). Missing the request → change → evidence chain is HIGH.
