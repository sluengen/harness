# Workflow Author Ergonomics

A reproducible test of whether `AUTHORING.md` is good enough on its own to compose a working workflow from a blank page. Any agent can re-run this skill on demand.

## What this skill measures

**Can a cold reader produce a validating workflow using `AUTHORING.md` as the only reference?**

That's the *testable* slice of the original "10-minute mental tax" question. It catches:

- Workflow YAML that fails `Workflow.model_validate()` — the surface is unclear or incomplete
- `writes:` / `contract:` field-name mismatches — the derivation rule isn't obvious
- Missing standard prompt template_vars — the guide isn't covering required inputs
- Reach for fields the guide doesn't document — gap in §3 grammar or §10 pitfalls
- Concepts the agent had to guess at — a "blocker" pain-point flag

It does NOT measure the *non-testable* slice — human cognitive friction, reading speed, anxiety about getting it wrong. That gap is acknowledged. For an evolving tool, reproducible-and-catches-regressions beats one-shot-and-precise.

## When to run

- **After any change to `AUTHORING.md`** — regression check
- **After any change to `harness/workflow/schema.py`** — validation surface drift
- **Before any v1.x point release** — canary
- **Periodically** (e.g., monthly) as part of routine quality checks

## The protocol

Run the test as a fresh sub-agent dispatch from a Claude Code session. The orchestrator:

1. Dispatches `general-purpose` (or any catch-all agent) — NOT `dev`, NOT `architect`. Fresh context, no project-specific priors.
2. Provides the prompt below, parameterised with one *scenario* (defined later).
3. Receives the agent's output and runs validation.
4. Repeats for each scenario in the suite.
5. Aggregates results into a report at `lessons/ergonomics/<YYYY-MM-DD>-<run-id>.md`.

### Sub-agent prompt (parameterised)

```
You are testing the authoring ergonomics of the harness workflow system.

Your ONLY reference is `AUTHORING.md` at the repo root. Do NOT read:
- SPEC.md (design rationale — explicitly out of scope for this test)
- harness/ source code (would be cheating)
- workflows/*.yaml (would be cheating — except as the guide explicitly cites them)
- prompts/standard/*.j2 (you may consult ONLY the headers, since the guide
  references their `template_vars` requirements)

Allowed tools: Read (against AUTHORING.md and the standard prompt headers only),
Write (your final YAML output).

## Your task

{SCENARIO_DESCRIPTION}

Write the workflow as `workflows/ergonomics-test-{SCENARIO_ID}.yaml`. The
workflow must validate via `Workflow.model_validate(yaml.safe_load(open(path)))`.

## Pain-points log

While you work, maintain a structured log of every point where AUTHORING.md
was unclear, missing, or ambiguous. Each entry:

- **severity**: `blocker` (had to guess) | `confusing` (took multiple re-reads) | `minor` (small ambiguity)
- **section**: which part of AUTHORING.md (e.g., "§3 Inline contracts", "§5 State and writes")
- **description**: what you wanted to know and what the guide didn't tell you cleanly

## Output

When done, write the workflow YAML to its path, then submit a final report as
a JSON object with these fields:

{
  "scenario_id": "<the scenario id you ran>",
  "workflow_path": "<path you wrote>",
  "pain_points": [{"severity": "...", "section": "...", "description": "..."}],
  "self_assessment": "did you produce something you believe loads? brief explanation",
  "consulted_only_authoring_md": true|false
}

Do NOT consult SPEC.md, harness source, or other workflows. If the guide
genuinely doesn't tell you something, flag it as `blocker` and make your
best guess — don't go looking elsewhere.
```

## Validation (orchestrator side)

After the sub-agent submits, the orchestrator:

```python
from pathlib import Path
import yaml
from harness.workflow.loader import load_workflow

path = Path(f"workflows/ergonomics-test-{scenario_id}.yaml")
try:
    loaded = load_workflow(path)
    validates = True
    error = None
except Exception as e:
    validates = False
    error = str(e)
```

If `load_workflow` raises, that's an automatic FAIL for the scenario regardless of the agent's self-assessment.

## Scenarios

Three scenarios cover the breadth of the authoring surface. Run all three for a full ergonomics check; run one for a smoke check.

### Scenario A — informational, 3 stages

**Tests:** simplest end-to-end pattern; standard prompt reuse; basic inline contracts.

> Write a workflow that pulls Notion pages tagged `release-notes` from the last 14 days, asks an AI agent to summarise them into markdown organised by tag, and writes the result to `~/.harness/artifacts/<run-id>/notes.md`. The workflow has no inputs beyond the lookback window (default 14 days).

Expected shape: 3 steps (fetch script → AI summarise → write script). Uses `prompts/standard/summarize.j2`. Inline contracts on each step. No worktree, no loop, no decision.

### Scenario B — code-mutating, 4 stages

**Tests:** the canonical 4-stage shape; worktree opt-in; specialist review.

> Write a workflow that takes a Linear ticket ID, sets up a worktree off `main`, has an AI agent investigate the ticket and apply a fix (a code change with tests), runs a separate AI reviewer against the diff with criteria "correctness, test coverage, regression risk", and on PASS commits and pushes the branch. On reviewer FAIL, the workflow cancels.

Expected shape: 4 stages (intake/worktree → build → review → outtake). Uses `worktree.create` + `worktree.cleanup` with `merge_to_base`. AI nodes use standard prompts where they fit. Includes a `check` step gating on `state.review_status`.

### Scenario C — loop, code mutation + iteration

**Tests:** loop block syntax (including `type: loop` requirement); `writes_files: true` with empty contract; in-loop check + state-driven termination.

> Write a workflow that takes a feature description, sets up a worktree, then enters a loop that alternates between "implement the feature" (AI, mutates files) and "run pytest" (script, captures pass/fail). Loop terminates when tests pass or after 5 iterations. On loop exit, if tests pass commit and merge; otherwise cancel.

Expected shape: worktree.create → loop block { implement, run-tests } until `state.tests_pass` → (gate) → worktree.cleanup. The `implement` step has `writes_files: true` and `writes: []`. Tests `type: loop` declaration.

## Pass / Fail criteria

The skill passes if and only if:

1. **All three scenarios produce a workflow that validates** via `load_workflow()`. Any FAIL on validation = skill FAIL.
2. **No pain-point in any scenario is severity `blocker`.** A blocker means the agent had to guess at a load-bearing concept — the guide failed at its job.
3. **All scenarios reported `consulted_only_authoring_md: true`.** If the agent had to break the constraint, the guide isn't self-sufficient.

A `confusing` pain-point is non-blocking but actionable — gets folded into the next AUTHORING.md revision. A `minor` is logged for trend-watching but doesn't trigger work.

## Report format

The orchestrator writes `lessons/ergonomics/<YYYY-MM-DD>-<run-id>.md` with:

- Run metadata (date, AUTHORING.md SHA, schema.py SHA)
- Per-scenario: produced workflow path, validation result (with error if any), self-assessment, pain-points table
- Aggregate: total blocker count, total confusing count, overall PASS/FAIL verdict
- Action items: every blocker becomes a guide-improvement task; recurring confusing entries (3+ runs flag the same section) become a guide-improvement task

## Why this isn't the human test

Honestly: an agent has trained-in priors. A "blocker" for an agent — an unanswered question — might be no challenge for a human, and vice versa. An agent's reading speed is irrelevant. An agent's "self-assessment" is shaped by what it expects to be asked, not what it actually struggled with.

What this skill catches reliably:

- **Validation regressions.** If the guide says something incompatible with `Workflow` schema, the agent will produce invalid YAML.
- **Surface gaps.** If the guide doesn't document a required field, the agent will either guess (blocker) or omit it (validation fail).
- **Composition errors.** `writes:` / `contract:` mismatches, missing standard prompt vars, `type:` omissions — all surface immediately.

What it misses:

- **Human cognitive friction.** A 200-line dense section may be readable to an agent that doesn't experience reading effort but unfit for a human.
- **Implicit knowledge gaps.** An agent's training data fills in things a human author would have to learn.
- **"Where do I even start" friction.** Agents are good at following protocol; humans need a clear on-ramp.

A periodic human read-through, separate from this skill, can address those. The intent to bound v1 scope on a human test is satisfied differently — by *this skill running cleanly* + *AUTHORING.md being maintained against its findings*. If the skill ever starts producing blockers, the guide needs revision before the next release.

## Running this skill

For now, the runner is the orchestrating Claude Code session. To execute:

1. Read this skill in full.
2. Dispatch a `general-purpose` sub-agent per scenario (parallel is fine — they're independent).
3. Collect the JSON reports.
4. Validate each produced workflow via `harness.workflow.loader.load_workflow()`.
5. Aggregate into the report.

A future enhancement (post-v1) could turn this into a workflow that lives in `workflows/ergonomics-check.yaml` and runs via `harness run ergonomics-check`. For v1, the skill markdown plus orchestrator coordination is sufficient.
