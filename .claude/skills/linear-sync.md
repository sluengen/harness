# Linear Sync

Knowledge for reading from and writing to a Linear workspace. Used by the orchestrator during `/dev-loop` and `/start-task` to keep Linear and the manifest in sync.

## Setup

<!-- PROJECT: Replace these placeholders with your project's values -->
- **Team**: {Your Team Name} (ID: `{team-id}`)
- **MCP server**: `linear` (HTTP transport, OAuth auth)

## Field Mapping — Linear → Manifest

| Linear field | Manifest field | Notes |
|---|---|---|
| Title | `name` | Human-readable task name |
| Identifier (e.g. PRJ-42) | used in `id` | Slugified: `prj-42-short-description` |
| Priority (1=Urgent, 2=High, 3=Normal, 4=Low) | `priority` | 1→P0, 2→P1, 3→P2, 4→P3 |
| Label: `Feature`/`Bug`/`chore`/`refactor` | `type` | One type label per issue. Case-insensitive match. |
| Label: `frontend`/`backend`/`fullstack` | routing | Determines which dev agent and whether brand_review applies |
| Status | `status` | See status mapping below |
| Description | `description` | Preserved verbatim |

## Status Mapping

Linear uses its default statuses. The manifest tracks granular pipeline state; Linear sees the coarse view.

### Linear → Manifest (intake)

| Linear status | Manifest status |
|---|---|
| Backlog | `backlog` |
| Todo | `todo` (DAG evaluation determines next artifact) |

### Manifest → Linear (progress updates)

The manifest tracks coarse status (`todo` | `in_progress` | `done`). Pipeline position is derived from the artifact DAG for reporting.

| Manifest status | Linear status |
|---|---|
| `backlog` | Backlog |
| `todo` | Todo |
| `in_progress` (DAG position: proposing, specifying, ready_for_dev, building) | In Progress |
| `in_progress` (DAG position: ready_for_review, reviewing, ready_for_deploy) | In Review |
| `done` (pipeline complete, PR created) | In Review |

**Note:** The pipeline never moves issues to Done. Pipeline completion → "In Review". The user moves to Done after UAT.

## Label Taxonomy

All labels are flat, team-level (not grouped — MCP cannot read grouped/project labels).

| Group | Labels | Mutually exclusive? |
|---|---|---|
| Type | `Feature`, `Bug`, `chore`, `refactor` | Yes |
| Stack | `frontend`, `backend`, `fullstack` | Yes |
| Pipeline | `needs-input`, `review-failed` | No (additive) |

`Feature` and `Bug` are workspace-level defaults (capitalised). `chore` and `refactor` are team-level.

## Sync Rules

1. **Linear is intake, manifest is execution.** Issues flow Linear → manifest at pull time. Status flows manifest → Linear as the pipeline progresses.
2. **Never delete Linear issues.** If a task is cancelled, move to Canceled status — don't delete.
3. **Comment, don't clutter.** Post PR links and blocker notes as Linear comments. Don't modify the issue description after intake.
4. **Pipeline labels are orchestrator-managed.** Only the orchestrator adds/removes `needs-input` and `review-failed`. Don't set these at intake.
5. **Existing manifest tasks coexist.** Tasks without `linear_id` are manually-added and unaffected by Linear sync.

## Operations Reference

### MCP Operations

| Operation | Tool | Used for |
|---|---|---|
| Pull next task | `list_issues` (state: "Todo", sorted by priority) | Task selection |
| Read issue details | `get_issue` | Full description, labels |
| Update status | `save_issue` (stateId) | Sync pipeline progress |
| Add comment | `save_comment` | PR links, status updates, blocker notes |
| Add/remove label | `save_issue` (labelIds) | Pipeline labels (needs-input, review-failed) |
| List statuses | `list_issue_statuses` (team) | Resolve status name → ID |

### Direct API (portable — works in local, cloud, and CI)

If your project has Python API clients in `tools/`, prefer those over MCP. Auth via `LINEAR_API_KEY` env var.

| Operation | Typical method | Used for |
|---|---|---|
| Pull next task | `LinearClient.list_todo_issues(team_id)` | Task selection |
| Read issue details | `LinearClient.get_issue(identifier)` | Full description, labels |
| Update status | `LinearClient.update_issue(id, state_id=)` | Sync pipeline progress |
| Add comment | `LinearClient.add_comment(issue_id, body)` | PR links, status updates, blocker notes |
| Add/remove label | `LinearClient.update_issue(id, label_ids=)` | Pipeline labels |
