# Pipeline Status

Show the current state of all tasks in the manifest as a clean, scannable summary, and archive stale completed tasks.

## Instructions

Read `manifest.yaml`, produce a status report, and condense old completed tasks.

### Step 1: Read the manifest

Read `manifest.yaml` in full.

### Step 2: Archive old completed tasks

Any task with `status: done` and `completed_date` older than 7 days from today must be condensed into the `archive:` section at the bottom of `manifest.yaml`.

**Archive format** — one-line YAML flow mapping per task:
```yaml
- {id: task-id, name: Task Name, status: done, completed_date: 'YYYY-MM-DD', pr: 'https://...'}
```

Keep only: `id`, `name`, `status`, `completed_date`, and `pr` (if present). Drop everything else — descriptions, artifacts, carry_forward, review fields, depends_on, assigned_to, priority, tier, type, notes, bugs.

**Rules:**
- If the task has `carry_forward` or `review_carry_forward` items that are NOT already captured in a `carry-forward-*` chore task in the maintenance section, create or append to the appropriate chore first (test-coverage, design-tokens, or code-cleanup). Do not lose carry-forwards.
- Move the task from wherever it sits (`tasks:`, `maintenance:`, or inline in the recently-completed area) into `archive:`.
- If an `archive:` section does not exist, create it at the bottom of the file with a comment header.
- Do not archive tasks that are not `done`.
- Do not archive tasks completed within the last 7 days — they stay in their current section with their description intact.

### Step 3: Group remaining tasks by state

Organise non-archived tasks into these groups (omit empty groups):

**In Progress** — tasks with status: specifying, designing, building, reviewing
**Ready** — tasks with status: ready_for_spec, ready_for_design, ready_for_dev, ready_for_review, ready_for_deploy (and no unresolved blockers)
**Blocked** — tasks in backlog or with a `blocked_by` field that references an incomplete dependency
**Recently Done** — tasks with status: done (within last 7 days), sorted by completed_date descending, show last 5

### Step 4: Format the output

Use this format:

```
## Pipeline Status — [today's date]

### In Progress
| Task | Stage | Assigned |
|------|-------|----------|
| [task name] | [human-readable stage] | [assigned_to or —] |

### Ready to Start
| Task | Waiting for | Priority |
|------|-------------|----------|
| [task name] | [next agent: PM / architect / dev / reviewer / deploy] | [P0–P5] |

### Blocked
| Task | Blocked by |
|------|------------|
| [task name] | [reason — dependency task or blocked_by note] |

### Recently Shipped
| Task | Completed | Tag |
|------|-----------|-----|
| [task name] | [completed_date] | [tag if present] |

### Flags
[Only include this section if something needs attention:]
- [task] has been in [status] since [date] with no recent activity
- [task] depends on [other task] which is still in progress

### Housekeeping
[Only include if tasks were archived this run:]
- Archived N tasks completed before [cutoff date]
```

### Stage labels (for In Progress column)

| Manifest status | Human label |
|---|---|
| specifying | Writing spec |
| designing | Designing |
| building | Building |
| reviewing | Under review |
| ready_for_deploy | Awaiting deploy |

### Step 5: Output

Print the status report to the conversation. The manifest edits (archiving) are written directly — no confirmation needed.
