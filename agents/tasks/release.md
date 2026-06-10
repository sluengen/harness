# Agent task: release notes + dev → main PR

A short, agent-run procedure that replaces the retired `workflows/release.yaml`
(CAL-574). The deterministic workflow engine that walked that YAML is gone; the
behaviour now lives here as steps the orchestrating Claude session executes
directly (the same way `/harness run` drives the verbs). It was never wired into
an automated trigger, so there is no loss of running behaviour — only a change
of execution model.

## When to run

When cutting a release: summarise the Linear tickets completed since the last
release into release notes and open a PR from `dev` to `main`.

## Inputs

- `since_days` — how far back to pull completed tickets (default `7`).
- `output_path` — where to write the release notes markdown (default: a
  `release-notes-<date>.md` under the repo root).
- `repo` — the GitHub `owner/name` the PR is raised against.

## Steps

### 1. Fetch the completed tickets

Query Linear for tickets completed in the window. `LINEAR_API_KEY` comes from
the repo `.env` (never hard-code it).

```bash
SINCE=$(python3 -c "from datetime import datetime,timedelta; print((datetime.utcnow()-timedelta(days=${SINCE_DAYS:-7})).strftime('%Y-%m-%dT%H:%M:%SZ'))")
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query($since:DateTimeOrDuration!){issues(filter:{completedAt:{gt:$since},state:{type:{eq:\"completed\"}}},first:100){nodes{id identifier title labels{nodes{name}}}}}","variables":{"since":"'"$SINCE"'"}}'
```

For each ticket, derive a `kind` from its labels (`bug` / `feature` /
`improvement` / `chore`), defaulting to `feature`.

### 2. Summarise into release notes

Group the tickets by kind and write release-notes markdown with sections
**Features**, **Bug fixes**, and **Improvements**. This is the agent's own
summarisation step — read the ticket list, produce concise human-readable notes.

### 3. Write the notes to disk

Write the markdown to `output_path` (or the dated default). Print the path.

### 4. Raise the PR

```bash
TODAY=$(date +%Y-%m-%d)
gh pr create \
  --repo "$REPO" \
  --title "Release — ${TODAY}" \
  --body-file "$OUTPUT_PATH" \
  --base main \
  --head dev
```

## Done when

The release notes file exists and `gh pr create` returns a PR URL from `dev`
into `main`.
