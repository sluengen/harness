# File a Bug

Capture a bug report from a conversational description and write it to `bugs/`.

Usage: `/bug [optional: description]`

If a description is provided in `$ARGUMENTS`, use it as the starting point. Otherwise, prompt the user to describe the bug.

---

## Instructions

### Step 1: Gather the description

If `$ARGUMENTS` is non-empty, treat it as the user's initial description. Read it carefully and extract everything you can:
- What is broken (summary)
- Which screen or flow
- What the user expected vs what happened
- Any error messages or visible symptoms
- Auth state (guest / signed in / signed out) if mentioned
- Browser or device if mentioned

If `$ARGUMENTS` is empty, ask: *"What's the bug? Describe what's broken, which screen you were on, and what you expected to happen."*

### Step 2: Fill gaps with targeted questions

Only ask for fields you could not infer from the description. Ask all missing questions in a single message — do not ask one at a time.

**Infer from context where possible:**
- If the bug is on a visible screen → area is likely `frontend`
- If it's an API or data issue → `backend`
- If it involves login, tokens, or permissions → `auth`
- If the user says "crashed", "lost data", or "can't use" → `critical` or `high`
- If they say "looks wrong", "slightly off", or "minor" → `low` or `medium`

**Fields to ask about if not clear:**
- **Severity** — critical / high / medium / low (use the definitions: critical = app broken for all users; high = core flow broken; medium = non-critical feature broken; low = cosmetic/edge case)
- **Steps to reproduce** — if the description didn't include them
- **Expected vs actual** — if not already clear
- **Affected spec** — do they know which acceptance criterion or feature spec this relates to? (Optional — leave blank if unsure)

### Step 3: Confirm before writing

Present a brief summary of what you're about to file:

```
Filing bug:
  Summary:  [one-line description]
  Severity: [critical | high | medium | low]
  Area:     [frontend | backend | auth | data | infra]
  Steps:    [1–3 line summary]
```

Ask: *"Anything to add or change before I file this?"*

Incorporate any corrections, then proceed.

### Step 4: Determine the next bug number

Read the `bugs/` directory. Find all files matching `BUG-NNN-*.md`. Take the highest number and increment by 1. Zero-pad to three digits (e.g. `001`, `012`, `123`).

If the directory is empty or has no matching files, start at `001`.

### Step 5: Derive the slug

From the one-line summary, produce a 3–5 word kebab-case slug. Strip articles and filler words. Examples:
- "Edit panel clears all fields on save" → `edit-clears-fields`
- "Auth token not sent on first load" → `auth-token-missing-first-load`
- "Toast shows wrong colour for errors" → `toast-wrong-colour-errors`

### Step 6: Write the bug file

Create `bugs/BUG-NNN-slug.md` using the structure below. Fill in everything gathered; leave the Resolution section blank (it's filled when fixed).

```markdown
# BUG-NNN: [one-line summary]

**Status:** open
**Severity:** [critical | high | medium | low]
**Product area:** [frontend | backend | auth | data | infra]
**Date filed:** [today's date YYYY-MM-DD]
**Filed by:** user

---

## Description

[One paragraph describing what is broken.]

## Steps to reproduce

[Numbered steps. If unknown, write "Not yet reproduced — see description."]

## Expected behaviour

[What should happen.]

## Actual behaviour

[What actually happens. Include error messages verbatim if provided.]

## Environment

- **URL:** [URL if known, otherwise "unknown"]
- **Screen / flow:** [screen name or flow description]
- **Auth state:** [signed in | guest | signed out | unknown]
- **Browser:** [if known, otherwise "unknown"]
- **Device:** [if known, otherwise "unknown"]

## Affected spec

[Link to spec file and AC section if known. Leave blank if not known.]

---

## Resolution
*To be filled in when fixed.*

### Root cause

### Fix summary

### Regression test added

- **Added:** —
- **Test file:** —
- **Test name:** —

### Spec / AC updated

- **Updated:** —
- **File + section:** —
- **Change:** —

### Architectural implication

- **ADR impact:** —
- **Summary:** —
```

### Step 7: Update the index

Read `bugs/README.md`. Find the index table (the `| ID | Slug | ...` table at the bottom). Add a new row for this bug:

```
| BUG-NNN | [slug] | [severity] | open | [area] |
```

Write the updated file.

### Step 8: Confirm to the user

Report back:

```
Filed: bugs/BUG-NNN-slug.md
Severity: [severity]
Status: open
```

If the affected spec was identified, note it. If it wasn't, suggest: *"If you know which spec AC this relates to, add it to the `Affected spec` section — it'll make the fix process smoother."*
