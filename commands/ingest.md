# Ingest Task

Accept user intent, structure it into an agent-ready Linear issue, and create it.

## Usage

- `/ingest <description>` — describe what you want; Claude structures and creates the issue
- `/ingest` — Claude prompts for intent first

## When to use

- You have an idea, bug, or task you want the harness to work on
- You want to queue something for `/start` without hand-writing the issue
- You need to convert a rough note into a spec the implementing agent can act on

## Protocol

### Step 1 — Gather intent

If a description was provided, use it. If not, ask in one turn:

> What do you want done? Describe the goal, and optionally: what triggered it, how you'll know it's done, any constraints.

Do not ask follow-up questions. One prompt is enough; infer the rest from what the user provides.

### Step 2 — Draft the issue

**Title** — concise action phrase, verb-first, under 80 characters:
- "Add retry logic to webhook intake"
- "Fix state substitution when value is None"
- "Expose --dry-run flag on harness CLI"

**Description** — Markdown written for the implementing agent, not a human reader.
The agent reads this cold with no conversation context, so it must be self-contained.

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

Rules:
- Acceptance criteria must be checkable — not "make it better" but "calling X with Y returns Z"
- Technical notes are hints, not commands — the agent decides approach
- Omit empty sections; don't force a section that adds nothing

**Priority** — infer from the user's language:

| Signal | Priority |
|--------|----------|
| "broken", "blocking", "urgent", "ASAP" | Urgent (1) |
| "important", "high priority", "soon" | High (2) |
| no signal | Medium (3) |
| "nice to have", "low priority", "someday" | Low (4) |

### Step 3 — Preview and confirm

Show the user:

```
Title:    <title>
Priority: <Urgent / High / Medium / Low>

--- Description ---
<formatted description>
-------------------

Create this issue? (yes / edit / cancel)
```

If the user wants edits, apply them and re-show. Do not call the API until explicitly confirmed with "yes".

### Step 4 — Fetch team ID and projects

Run both in parallel — team ID is needed for issue creation, projects for the picker in Step 5.

**Teams:**
```bash
source .env && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query{teams{nodes{id key name}}}"}'
```

Use the `id` of the team you want to create the issue under (check the `key` field to identify it).

**Projects for that team:**
```bash
source .env && curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query{teams{nodes{id key projects{nodes{id name}}}}}"}'
```

Use the projects from the team whose `id` you identified in the previous step.

### Step 5 — Pick a project

List the project names and ask the user:

```
Available projects:
  1. <Project A>
  2. <Project B>
  3. None

Which project should this issue belong to?
```

Wait for the user's selection before proceeding. If they pick "None", omit `projectId` from the mutation.

### Step 6 — Create the issue

Use `jq --arg` to JSON-encode all string fields (handles newlines and special characters automatically), pipe to curl.

**With a project:**
```bash
source .env && jq -n \
  --arg teamId "<team-id>" \
  --arg title "<title>" \
  --arg description "<description>" \
  --arg projectId "<project-id>" \
  --argjson priority <1|2|3|4> \
  '{"query":"mutation($input:IssueCreateInput!){issueCreate(input:$input){success issue{identifier url}}}","variables":{"input":{"teamId":$teamId,"title":$title,"description":$description,"projectId":$projectId,"priority":$priority}}}' \
| curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @-
```

**Without a project:**
```bash
source .env && jq -n \
  --arg teamId "<team-id>" \
  --arg title "<title>" \
  --arg description "<description>" \
  --argjson priority <1|2|3|4> \
  '{"query":"mutation($input:IssueCreateInput!){issueCreate(input:$input){success issue{identifier url}}}","variables":{"input":{"teamId":$teamId,"title":$title,"description":$description,"priority":$priority}}}' \
| curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d @-
```

Check that `success` is `true` in the response. If not, show the full response and stop.

### Step 7 — Report

```
Created: <ISSUE-ID>
Project: <project name or "none">
URL:     <linear url>

Next: /start <ISSUE-ID>
```

## What the agent sees

The implementing agent (via the build workflow's `fetch-ticket` step) receives `ticket_title` and
`ticket_description` verbatim and acts on them cold — no conversation, no clarification.
A well-written description is the difference between a clean first pass and multiple review failures.

## Related

- `commands/start.md` — runs the build workflow for a given issue ID
- `workflows/build.yaml` — the workflow `/start` triggers
- `prompts/build/implement.j2` — the prompt the implementing agent receives
