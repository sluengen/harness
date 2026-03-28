# Notion Sync

<!-- PROJECT: This skill is a template. Replace all placeholder values with your
     project's Notion database IDs, repo paths, and content mapping. Remove this
     comment block when configured. -->

Project content is managed in Notion and synced to the codebase. This skill defines what lives where, how sync works in both directions, and the rules that prevent conflicts.

## Content Types

Two distinct content types, each with its own sync pattern:

| Type | Notion entity | Repo file(s) | Source of truth |
|------|---------------|--------------|-----------------|
| **App Copy** | App Copy database | (generated copy file path) | Notion for text; code for key existence |
| **Rich docs** | Notion pages | Spec markdown files | Notion after user begins editing there |

## Notion Entity References

<!-- PROJECT: Add your Notion page IDs and URLs here -->
| Entity | URL | ID |
|--------|-----|----|
| Parent page | (your Notion URL) | (your page ID) |
| App Copy database | (your Notion URL) | — |

## Rich Doc Mapping

<!-- PROJECT: Map your Notion pages to repo files -->
| Notion page | Repo file |
|-------------|-----------|
| (page name) | (repo path) |

---

## App Copy — Pull (Notion → Code)

Pull reads the App Copy database and generates the copy source file.

### Steps

1. **Fetch** — Read all rows from the App Copy data source.
2. **Group** — Group entries by the screen prefix in the Key field (the part before the first `.`). Each prefix becomes a top-level object key.
3. **Generate** — Write the copy file in a typed, const-exported format.
4. **Verify** — Run the type checker to confirm the generated file is valid.

### Generation Rules

- Keys use the dot notation from the Notion Key field: `screen.element` becomes `copy.screen.element`.
- Values are plain strings. Dynamic placeholders use `{name}` syntax. Components handle interpolation at the call site.
- Preserve existing key order within groups (sorted alphabetically if generating fresh).
- The file header must include the sync timestamp and Notion database URL.
- The copy file is committed to the repo — it is the deployed artifact.

---

## App Copy — Push (Code → Notion)

Push scans frontend components for hardcoded strings that should be in Notion but aren't.

### When to Push

- After a frontend-dev agent adds a new component or screen with new user-facing strings.
- After a reviewer flags hardcoded strings that bypass the copy file.
- On user request.

### Steps

1. **Scan** — Search frontend source files for string literals in JSX that are not already referenced in the copy file.
2. **Diff** — Compare found strings against existing keys in the Notion database.
3. **Create** — For each new string, create a row in the App Copy database with key, copy, screen, type, status, and file location.
4. **Report** — List the new keys added so the user knows what needs editorial review.

### Push Does NOT

- Overwrite existing Notion entries. If a key already exists, skip it.
- Delete Notion entries for removed strings. Orphan cleanup is manual.
- Change any code. Push is Notion-only.

---

## Rich Docs — Pull (Notion → Repo)

### Steps

1. **Fetch** — Read the Notion page content.
2. **Convert** — Transform Notion markdown to standard markdown. Preserve all structure.
3. **Write** — Write to the mapped repo file.
4. **Preserve frontmatter** — If the repo file has YAML frontmatter, preserve it. Notion content replaces only the body.

### Conflict Check

Before overwriting the repo file, compare the current file's git last-modified date with the Notion page's `last_edited_time`. If the repo file was modified more recently, **warn the user**. Do not overwrite without confirmation.

---

## Rich Docs — Push (Repo → Notion)

### Steps

1. **Read** — Read the repo markdown file.
2. **Convert** — Transform standard markdown to Notion-compatible markdown.
3. **Update** — Replace the Notion page content.
4. **Skip frontmatter** — Do not push YAML frontmatter to Notion.

### When to Push

- After an agent modifies a mapped spec file through the pipeline.
- On user request.

### Conflict Check

Same as pull but reversed: if the Notion page was edited more recently than the repo file, warn before overwriting.

---

## Component Migration

When refactoring a component to use the copy file:

1. **Import** the copy module.
2. **Replace** hardcoded strings with copy key references.
3. **Dynamic strings**: For strings with `{n}` placeholders, replace at the call site.
4. **Do not** move enum labels to the copy file. They are separate concerns.
5. **Do not** create wrapper functions or abstraction layers. Direct property access is the pattern.

---

## Validation

After any sync operation:

| Direction | Validation |
|-----------|-----------|
| App Copy pull | Run type checker — generated file must be valid |
| App Copy push | Verify new rows appear in Notion with correct values |
| Rich doc pull | `git diff` the target file — review the delta is expected content |
| Rich doc push | Fetch the Notion page back and spot-check formatting |

---

## Agent Responsibilities

| Agent | Responsibility |
|-------|---------------|
| **frontend-dev** | Import from copy file, never hardcode user-facing strings. Flag new strings for push. |
| **reviewer** | Check that components use the copy file. Hardcoded strings that should be in copy are a High severity finding. |
| **marketing-comms** | Edit copy in Notion. Do not edit the copy file directly. |
| **orchestrator** | Run pull/push on user request. Run push after frontend-dev completes a task with new screens. |
