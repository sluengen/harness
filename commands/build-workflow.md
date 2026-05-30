# Build Workflow

Build a new harness workflow YAML from a high-level description. Activates the `workflow-authoring` skill.

## Usage

- `/build-workflow <description>` — describe what the workflow should do; the agent designs, writes, and validates the YAML
- `/build-workflow` (no args) — agent prompts you for the description first

## What this does

Activates `skills/workflow-authoring.md`, which guides the agent through a six-step protocol:

1. Read `AUTHORING.md` in full
2. Pick the canonical shape (3-stage informational or 4-stage code-mutating)
3. Design the workflow per the guide's grammar
4. Write to `workflows/<name>.yaml`
5. Validate via `harness.workflow.loader.load_workflow()`
6. Report back to you

The agent doesn't need to read `SPEC.md` or `harness/` source — `AUTHORING.md` is self-sufficient. This is a deliberate scope constraint; if the agent reaches for the engine internals, that's a guide-completeness signal worth surfacing.

## Examples

```
/build-workflow Summarise GitHub PRs merged in the last week into release notes markdown
```

```
/build-workflow Fix a Linear ticket end-to-end: pull the ticket, set up a worktree off main,
    have an agent investigate + apply a fix with tests, get a second-agent review,
    on PASS commit and push, on FAIL cancel
```

```
/build-workflow A nightly assessment that reads the codebase for architecture drift and
    produces a structured report
```

## When to invoke

- Building a new workflow for a recurring task you'll run more than once
- Scaffolding a workflow from a description before you customise it
- Re-creating a deleted workflow from intent

## NOT for

- Editing existing workflows — just edit `workflows/<name>.yaml` directly
- Designing the engine grammar itself — that's `SPEC.md` territory
- One-off scripts that don't warrant a workflow — use the CLI directly

## After invocation

The agent reports the workflow path and validation result. You can:

- Run it: `harness run <workflow-name> <inputs>`
- Inspect it: `cat workflows/<name>.yaml`
- Iterate: tell the agent what to change and re-invoke the skill, or edit directly

## Related

- `skills/workflow-authoring.md` — the protocol this command activates
- `skills/workflow-author-ergonomics.md` — reproducible test of the authoring surface; runs after `AUTHORING.md` or schema edits to catch regressions
- `AUTHORING.md` — the canonical workflow author reference (the skill leans entirely on this)
