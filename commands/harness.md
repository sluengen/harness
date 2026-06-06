# /harness — Harness pipeline commands

Commands that launch or interact with the **harness pipeline itself**. These are distinct from the agent-led workflow commands (`/start`, `/review`, `/ship`); they trigger the automated execution engine.

---

## /harness run \<ISSUE-ID\>

Trigger the build workflow for a Linear issue. The harness handles everything — worktree, implementation, review, commit, push.

### Usage

- `/harness run <ISSUE-ID>` — run the build workflow for the given Linear issue
- `/harness run <ISSUE-ID> --repo PATH` — run the build workflow targeting a different repo

### Cross-repo usage

```bash
/harness run SLT-42 --repo /path/to/slate
```

The harness runs from its own directory; `--repo` points it at the target codebase. Combine with `--verify-command` to override the verification gate and `--branch-prefix` to control branch naming in the target repo.

### Prerequisites

Before running any commands, load the project environment:

```bash
source .env
```

`LINEAR_API_KEY` and other credentials live in `.env` at the repo root (gitignored). If the file is missing, create it:

```bash
# .env
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxx   # from linear.app → Settings → API → Personal API keys
```

> **No Linear CLI is installed.** All Linear interaction in this project goes through the GraphQL API directly — `curl` in shell scripts, `urllib.request` in Python. Do not search for a `linear` binary or attempt `npx linear`.

`harness` is not installed globally in development — invoke it via `bin/harness` (preferred) or `uv run`:

```bash
# preferred — immune to VIRTUAL_ENV conflicts
source .env && PYTHONPATH=. bin/harness run build --linear=<ISSUE-ID>

# alternative — only when VIRTUAL_ENV is unset
source .env && PYTHONPATH=. uv run harness run build --linear=<ISSUE-ID>
```

### Instructions

**Step 1 — Fetch the ticket**

```bash
source .env && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query{issue(id:\"<ISSUE-ID>\"){identifier title description state{name} labels{nodes{name}} url}}"}'
```

Print a brief for the user:

```
Task:   <title>
Linear: <ISSUE-ID>
URL:    <url>
State:  <current state>
```

If the issue is already Done or has unresolved dependencies listed in the description, stop and report.

**Step 2 — Run the build workflow**

```bash
source .env && PYTHONPATH=. bin/harness run build --linear=<ISSUE-ID>
```

When `--repo`, `--verify-command`, or `--branch-prefix` were supplied, pass them through:

```bash
source .env && PYTHONPATH=. bin/harness run build --linear=<ISSUE-ID> \
  [--repo /path/to/target-repo] \
  [--verify-command "bash scripts/verify.sh"] \
  [--branch-prefix "feature/"]
```

The workflow handles the rest: worktree, implement, review, gate, commit, push, merge.

**Step 3 — Report the outcome**

```bash
source .env && PYTHONPATH=. bin/harness status <run-id>
source .env && PYTHONPATH=. bin/harness logs   <run-id>
```

Report whether the run completed, was cancelled by the gate (review FAIL), or failed with an error. Surface the reviewer's findings if the gate fired.

---

## /harness build-workflow \<description\>

Build a new harness workflow YAML from a high-level description. Activates the `workflow-authoring` skill.

### Usage

- `/harness build-workflow <description>` — describe what the workflow should do; the agent designs, writes, and validates the YAML
- `/harness build-workflow` (no args) — agent prompts you for the description first

### What this does

Activates `skills/workflow-authoring.md`, which guides the agent through a six-step protocol:

1. Read `AUTHORING.md` in full
2. Pick the canonical shape (3-stage informational or 4-stage code-mutating)
3. Design the workflow per the guide's grammar
4. Write to `workflows/<name>.yaml`
5. Validate via `harness.workflow.loader.load_workflow()`
6. Report back to you

The agent doesn't need to read `SPEC.md` or `harness/` source — `AUTHORING.md` is self-sufficient.

### Examples

```
/harness build-workflow Summarise GitHub PRs merged in the last week into release notes markdown
```

```
/harness build-workflow Fix a Linear ticket end-to-end: pull the ticket, set up a worktree off dev,
    have an agent investigate + apply a fix with tests, get a second-agent review,
    on PASS commit and push, on FAIL cancel
```

### After invocation

The agent reports the workflow path and validation result. You can:

- Run it: `bin/harness run <workflow-name> <inputs>`
- Inspect it: `cat workflows/<name>.yaml`
- Iterate: tell the agent what to change and re-invoke the skill, or edit directly

### Related

- `skills/workflow-authoring.md` — the protocol this command activates
- `skills/workflow-author-ergonomics.md` — regression check after `AUTHORING.md` or schema edits
- `AUTHORING.md` — the canonical workflow author reference

---

## /harness ingest \<description\>

Accept user intent, structure it into an agent-ready Linear issue, and create it.

### Usage

- `/harness ingest <description>` — describe what you want; Claude structures and creates the issue
- `/harness ingest` — Claude prompts for intent first

### When to use

- You have an idea, bug, or task you want the harness to work on
- You want to queue something for `/harness run` without hand-writing the issue
- You need to convert a rough note into a spec the implementing agent can act on

### Protocol

**Step 1 — Gather intent**

If a description was provided, use it. If not, ask in one turn:

> What do you want done? Describe the goal, and optionally: what triggered it, how you'll know it's done, any constraints.

Do not ask follow-up questions. One prompt is enough; infer the rest from what the user provides.

**Step 2 — Draft the issue**

**Title** — concise action phrase, verb-first, under 80 characters.

**Description** — Markdown written for the implementing agent, not a human reader. The agent reads this cold with no conversation context, so it must be self-contained.

```markdown
## Context
<One or two sentences: why this matters, what triggered it, relevant background.>

## Goal
<What done looks like. One or two sentences.>

## Acceptance criteria
- [ ] <Specific, observable, checkable item>
- [ ] <Specific, observable, checkable item>
- [ ] Tests cover the new behaviour

## Technical notes
<Optional. Approach hints, files to look at, known constraints, SPEC references.>

## Out of scope
<Optional. Explicit guard rails against scope creep.>
```

**Priority** — infer from the user's language:

| Signal | Priority |
|--------|----------|
| "broken", "blocking", "urgent", "ASAP" | Urgent (1) |
| "important", "high priority", "soon" | High (2) |
| no signal | Medium (3) |
| "nice to have", "low priority", "someday" | Low (4) |

**Step 3 — Preview and confirm**

Show the user the title, priority, and description. Wait for "yes" before calling the API.

**Step 4 — Fetch team ID and create the issue**

```bash
source .env && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query{teams{nodes{id key name}}}"}'
```

Use `jq --arg` to JSON-encode all string fields when calling the create mutation. Check that `success: true` in the response.

**Step 5 — Report**

```
Created: <ISSUE-ID>
URL:     <linear url>

Next: /harness run <ISSUE-ID>
```

### Related

- `/harness run` — runs the build workflow for a given issue ID
- `workflows/build.yaml` — the workflow `/harness run` triggers
