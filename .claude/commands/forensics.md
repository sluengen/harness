# Forensics

Investigate a failed or stuck pipeline run and produce a structured diagnostic report.

## When to use

- A pipeline task is stuck (status hasn't changed when it should have)
- An agent session died mid-task and you need to understand what happened
- A reviewer FAIL needs root cause analysis beyond the review report
- Orphaned branches or abandoned work need investigation

## Instructions

1. **Gather evidence.** Run these in parallel to build a picture:
   - `git log --oneline -20` — recent commit history
   - `git branch -a` — all local and remote branches
   - `git status` — working directory state
   - Read `manifest.yaml` — current task statuses
   - Check for `.continue-here.md` — abandoned handoff files
   - Check `reviews/` — recent reviewer reports
   - Check `bugs/` — open bugs that might be related

2. **Check for anomalies.** Look for:
   - **Stuck tasks:** manifest status that hasn't progressed (e.g., `ready_for_review` with no reviewer report)
   - **Orphaned branches:** branches with no corresponding manifest task, or branches with WIP commits that were never merged
   - **Abandoned work:** uncommitted changes, stale stashes (`git stash list`), `.continue-here.md` files
   - **Reviewer FAIL chains:** tasks that failed review multiple times (check `reviews/` for multiple reports on the same task)
   - **Missing artifacts:** tasks marked `ready_for_review` but missing test files, or `ready_for_deploy` but missing reviewer PASS
   - **Time gaps:** large gaps between commits that suggest a session died

3. **Write the report.** Save to `reviews/forensics-{YYYY-MM-DD}.md`:

```markdown
# Forensics Report — {date}

## Summary
{1-2 sentence overview of what was found}

## Anomalies Found

### {Anomaly Title}
- **Type:** stuck_task | orphaned_branch | abandoned_work | reviewer_fail_chain | missing_artifact | time_gap
- **Evidence:** {specific commits, files, or manifest entries}
- **Likely cause:** {what probably happened}
- **Recommended action:** {what to do about it}

## Manifest Corrections
{any manifest status updates that should be made, or "None needed"}

## Cleanup Actions
{branches to delete, stashes to inspect, files to remove, or "None needed"}
```

4. **Present findings.** Summarize the key findings to the user with recommended next actions.

## Rules

- **Read-only investigation.** Do not modify source code, manifest, or any state. Only write the forensics report.
- **Evidence-based.** Every anomaly must cite specific commits, files, or data. No speculation without evidence.
- **Redact sensitive data.** Strip credentials, tokens, or personal data from report output.
- **Acknowledge gaps.** If evidence is insufficient to determine root cause, say so. Don't guess.
