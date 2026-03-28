# Harness Review

Audit the pipeline harness for coherence. The harness is the machinery that agents work within — CLAUDE.md, agent definitions, commands, skills, hooks, architecture specs, and templates. This review checks that the harness operates as a single cohesive unit.

Usage: `/harness-review`

## Instructions

### Step 1: Check for recent reports

Read `reviews/` directory listing (via Glob: `reviews/*harness-review*.yaml`). If a report exists within the last 14 days, notify the user:

```
Note: A harness review from [date] already exists at [path].
Running a new assessment — this will produce a second report for comparison.
```

Then continue.

### Step 2: Invoke the harness-reviewer agent

Invoke the `harness-reviewer` agent. Pass this instruction:

> Run a full harness coherence assessment. Check all three principles (MECE, Lean, Correct) across every scope area: CLAUDE.md, agent definitions, skills, commands, hooks, specs/arch/, specs/templates/, strategy/principles.md, review scorecard, and context/anti-patterns.md. Write your report to `reviews/[today's date]-harness-review-report.yaml` using the template at `specs/templates/harness-review-report.yaml`.

Wait for the agent to complete and return the report path.

### Step 3: Parse the report

Read the report. Extract:
- `report.summary`
- `report.finding_count`
- All findings at Critical or High severity
- All `recommended_actions` entries

### Step 4: Present results to the user

Present findings in this structure:

---

```
## Harness Review — [date]

[report.summary]

### Finding Summary
Critical: N  |  High: N  |  Medium: N  |  Low: N

### Action Required (Critical + High)

[For each Critical/High finding:]
**[id] — [severity]** ([principle, e.g. MECE | Lean | Correct])
[description, condensed to 2–3 sentences]
Evidence: [evidence field]

[If no Critical or High findings:]
No critical or high-severity findings. Harness coherence is good.

### Recommended Actions
[For each entry in recommended_actions:]
- `[id]`: [name] — [files_affected]

[If no recommended_actions:]
No actions recommended.

### Full Report
[path to the YAML file]
```

---

### Step 5: Offer to apply recommended actions

If `recommended_actions` is non-empty, ask the user:

> The reviewer has drafted [N] recommended action(s). Would you like to apply them now?

If yes: execute each action as described. Commit each change individually.

If no: do nothing. The actions remain in the report for future reference.

### When there are no findings

If `finding_count` totals 0 across all severities, output:

```
## Harness Review — [date]

[report.summary]

All scope areas are coherent. No findings.
Full report: [path]
```
