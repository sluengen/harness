# System Health

Run the system steward to assess health across all active products and surface architectural drift, ADR staleness, design-code gaps, dependency concerns, and test weaknesses.

Usage: `/system-health`

## Instructions

### Step 1: Check for recent reports

Read `reviews/` directory listing (via Glob: `reviews/*system-steward*.yaml`). If a report exists within the last 14 days, notify the user:

```
Note: A health report from [date] already exists at [path].
Running a new assessment — this will produce a second report for comparison.
```

Then continue.

### Step 2: Invoke the system-steward agent

Invoke the `system-steward` agent. Pass this instruction:

> Run a full health assessment. Check all five areas: architecture principle violations, ADR staleness, design-to-code gaps, dependency health, and test health. Write your report to `reviews/[today's date]-system-steward-health-report.yaml` using the template at `specs/templates/health-report.yaml`.

Wait for the agent to complete and return the report path.

### Step 3: Parse the report

Read the report. Extract:
- `report.summary`
- `report.finding_count`
- All findings at Critical or High severity
- All `recommended_tasks` entries

### Step 4: Present results to the user

Present findings in this structure:

---

```
## System Health Report — [date]

[report.summary]

### Finding Summary
Critical: N  |  High: N  |  Medium: N  |  Low: N

### Action Required (Critical + High)

[For each Critical/High finding:]
**[id] — [severity]** ([section, e.g. Architecture | ADR | Design | Dependency | Tests])
[description, condensed to 2–3 sentences]
Evidence: [evidence field]

[If no Critical or High findings:]
No critical or high-severity findings. System health is good.

### Recommended Tasks
[For each entry in recommended_tasks:]
- `[id]`: [name] — [pipeline]

[If no recommended_tasks:]
No refactor tasks recommended.

### Full Report
[path to the YAML file]
```

---

### Step 5: Offer to add recommended tasks to the manifest

If `recommended_tasks` is non-empty, ask the user:

> The steward has drafted [N] refactor task(s) for the manifest. Would you like to add them now?

If yes: add each entry under `tasks:` in `manifest.yaml` as-is. Do not change any fields — the steward has already set priority, pipeline, and description.

If no: do nothing. The tasks remain in the report for future reference.

### When there are no findings

If `finding_count` totals 0 across all severities, output:

```
## System Health Report — [date]

[report.summary]

All five assessment areas are clean. No findings.
Full report: [path]
```
