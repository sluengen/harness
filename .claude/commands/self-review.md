# Self-Review

Evaluate the quality of recent agent output against the project's review scorecard.

## When this command is invoked

The orchestrator runs `/self-review` at two mandatory pipeline checkpoints:

1. **After PM produces a spec** (`ready_for_design`) — review the product spec before the architect starts. Catch missing ACs, ambiguous scope, or untestable criteria before they become design gaps.
2. **After architect produces a design** (`ready_for_dev`) — review the design before the dev starts. Catch incomplete specs, missing test strategy, or ambiguous implementation guidance before they become code bugs.

The orchestrator can also run `/self-review` ad-hoc on any artifact — a draft spec, a design doc, a one-off edit — to apply structured review thinking outside the pipeline.

Run `/self-review --feature <task-id>` after a release ships to trace the full SDLC and score alignment at every handoff.

**Before starting, read `.claude/skills/code-review.md`.** This command applies the review skill's two-stage methodology (spec compliance → quality) using the weighted scorecard for scoring.

## Instructions

You are performing a structured self-review. Your job is to honestly evaluate output quality — not to be generous.

### Step 1: Identify What to Review

Determine the review scope from the conversation context:

- **Agent-level review (default):** Evaluate the most recent agent output in this conversation against the input that triggered it.
- **SDLC-level review** (if `$ARGUMENTS` contains `--feature <name>`): Trace a feature from its original request through every SDLC artifact (spec, design, tests, code) and score alignment at each handoff.

### Step 2: Load the Scorecard

Read `.claude/review-scorecard.yaml` to get:
- The scoring dimensions and their weights
- The pass/fail threshold
- The scoring scale (0-3)

### Step 3: Identify the Agent

Determine which agent produced the output being reviewed. Use the `applies_to` field on each dimension to select only the relevant dimensions for that agent. If reviewing the full SDLC, score each handoff separately.

### Step 4: Score Each Dimension

For each applicable dimension:

1. Read the dimension's `question`
2. Examine the output against that question
3. Assign a score (0-3) using the scale definitions
4. Note specific evidence for the score — quote or reference the output directly

**Scoring discipline:**
- A score of 3 means zero issues. Do not give 3 if you can identify any gap.
- A score of 2 is the expected outcome for solid work. This is not a penalty.
- Scores of 0-1 should include specific, actionable descriptions of what's missing.

### Step 5: Calculate Weighted Score

```
weighted_score = sum(score * weight for each dimension) / sum(max_score * weight for each dimension)
```

Where `max_score` is 3 for every dimension. Compare against the `threshold` in the scorecard.

### Step 6: Write the Result

Write a YAML file to `reviews/` with the filename format:
```
reviews/YYYY-MM-DD-<agent>-<short-description>.yaml
```

Use this structure:

```yaml
result:
  date: "YYYY-MM-DD"
  agent: <agent-name>
  task: "Brief description of what the agent was asked to do"
  input_summary: "Key requirements from the input"
  scores:
    <dimension_id>: <score>
    # ... one entry per applicable dimension
  evidence:
    <dimension_id>: "Brief justification for the score"
    # ... one entry per scored dimension
  weighted_score: <float 0-1, rounded to 2 decimal places>
  passed: <true|false>
  issues:
    - "Specific issue description with reference to output"
  remediation: "What should be changed to address issues, or null if passed"
```

### Step 7: Report

Output a summary to the conversation:

1. **Agent / Feature reviewed**
2. **Scores table** — dimension, score, weight, evidence summary
3. **Weighted score** and pass/fail
4. **Issues** — numbered list of specific problems found
5. **Remediation** — concrete next steps if below threshold

If below threshold: recommend specific changes. Do NOT automatically re-do the work — present findings to the user and let them decide.

### SDLC-Level Review (--feature mode)

When reviewing a full feature, trace these handoffs:

1. **Request to Spec**: Does the product spec in `specs/products/` capture the original request?
2. **Spec to Design**: Does the architect's design address every acceptance criterion?
3. **Design to Implementation**: Does the code implement the design?
4. **Implementation to Tests**: Do tests cover every acceptance criterion?
5. **Overall**: Does the shipped feature match the original intent?

Score each handoff independently, then produce an overall SDLC score. Write one result file per handoff plus a summary file.
