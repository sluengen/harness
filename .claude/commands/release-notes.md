# Release Notes

Generate formatted release notes for a completed task, ready to paste into a GitHub release, repo changelog, or announcement.

Usage: `/release-notes <task-id>`

## Instructions

### Step 1: Find the task

Read `manifest.yaml`. Find the task matching `$ARGUMENTS`. If the task is not found, report the error.

If the task status is not `done`, warn the user:
```
Warning: [task-id] is not yet done (status: [status]). Generating notes from available artifacts — some sections may be incomplete.
```

### Step 2: Gather artifacts

Read each artifact listed in the task's `manifest.yaml` entry. Typically:

- **Product spec** (`artifacts.product_spec`) — source of user stories, ACs, and scope
- **Reviewer report** (`artifacts.review`) — source of what passed, any carry-forward items
- **Design doc** (`artifacts.design`) — source of technical detail if needed for breaking changes

Also note:
- `tag` — the version tag created at deploy (e.g. `v0.3`, `v0.4`)
- `completed_date`
- `review_carry_forward` — non-blocking items deferred to the next version

### Step 3: Produce release notes

Write the release notes in this structure. Omit any section that has nothing to include — don't leave empty headings.

---

```markdown
## [Tag] — [completed_date]

[One sentence summary of what this release is. Focus on the biggest user-facing change, not the implementation.]

### What's New

[Bulleted list of new features and improvements. Written for the user, not the developer.
- Use plain language — describe the outcome, not the implementation.
- Group related items if there are many.
- Lead with the highest-value changes.]

### Bug Fixes

[Bulleted list of bugs fixed. Omit this section if none.]

### Breaking Changes

[Bulleted list of changes that require action from existing users. Be specific:
- What changed
- What the user needs to do
Include this section if the spec or design flagged breaking changes, or if the reviewer noted migration requirements. Omit if no breaking changes.]

### Migration Guide

[Step-by-step instructions for upgrading from the previous version, if breaking changes exist. Copy exact migration steps from the spec or reviewer report where available. Omit if no breaking changes.]

### Known Issues

[Non-blocking items from review_carry_forward that are visible to users. Frame as known limitations, not bugs. Omit internal/technical carry-forward items. Omit this section if nothing user-visible.]

### Full Changelog

[link to compare view if tag is known, e.g.:]
`github.com/[owner]/[repo]/compare/v0.2...v0.3`
```

---

### Step 4: Output

Print the release notes to the conversation. Do not write any files — the user will copy and paste where needed.

After the notes, add a one-line summary of where to post them:
```
Ready to post: GitHub release at tag [tag] on [repo]
```

### Writing style

- Written for the audience of the product — match the tone and vocabulary defined in the brand guidelines
- Past tense for what changed ("Added", "Fixed", "Removed")
- No jargon that isn't in the product spec or strategy docs
- Breaking changes get a full sentence of explanation — never just a bullet point
