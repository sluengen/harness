# Workflow Authoring

Skill for building a slate-harness workflow YAML from a high-level description. Activates whenever the agent needs to author a new workflow.

## When this skill activates

- The `/build-workflow` slash command
- User asks to "build a workflow for X" / "scaffold a workflow that Y" / "create a new workflow"
- Asked to translate a recurring task description into a workflow file

## Protocol (REQUIRED — follow in order)

### Step 1 — Read the authoring guide

Read `AUTHORING.md` at the repo root **in full**. This is the canonical workflow author reference and the only document you need (besides standard prompt headers if you'll use one).

You do NOT need to read:
- `SPEC.md` — that's engine design rationale, not authoring reference
- `harness/` source code — the guide is sufficient
- Other workflows in `workflows/` — they're examples, not specifications

If you find yourself reaching for those, the answer is probably already in `AUTHORING.md`. Re-read the relevant section.

### Step 2 — Pick the canonical shape

Most workflows fit one of two shapes. Pick the one that matches the request before designing:

| Shape | When | Typical steps |
|---|---|---|
| **3-stage informational** | Fetch external data → AI summarises → write to disk | `script` (fetch) → `ai` (summarize) → `script` (write) |
| **4-stage code-mutating** | Modify code in isolation → review → ship | `worktree.create` → `ai` (implement) → `ai` (review) → `worktree.cleanup` |

Reach for richer grammar (loops, decisions, multi-stage variations) only when the canonical shape genuinely doesn't fit. The release-notes worked example in `AUTHORING.md` §7 is a 3-stage informational; the bugfix example in §2's loop snippet shows a 4-stage with iteration.

### Step 3 — Design the workflow

For each step you plan:

- **Type** — per `AUTHORING.md` §2 step types table
- **Standard prompt** — for AI steps, pick from `prompts/standard/{analyze,implement,review,summarize}.j2`. See §5 for required `template_vars` per prompt.
- **Contract** — inline YAML per §3 grammar (string/integer/boolean/number/list-of/nested object). Use `$contracts/<name>` references only if the schema is genuinely shared across workflows.
- **`writes:`** — names match the contract field names exactly (this is enforced; see §10 pitfalls)
- **Variable references** — `$inputs.X` and `$state.X` per §4 substitution table

Special cases (these are the load-time foot-guns from §10 pitfalls):

- `worktree.create` / `worktree.cleanup` — declare neither `contract:` nor `writes:`. The framework populates `worktree_path` + `worktree_branch` directly into `BaseState`; downstream steps reference them via `$state.worktree_path`.
- AI step inside a loop body that mutates files — `writes_files: true` with `writes: []` and no `contract:` is the canonical pattern (the body produces files; no state writes).
- Loop steps — `type: loop` is **required**, not implied by the presence of `loop:`.
- No multi-branch routing — `check.on_fail:` is single-direction. For "X on PASS, Y on FAIL" gate with `on_fail: cancel` and put the success path downstream; the workflow halts before downstream steps on the cancel path.

### Step 4 — Write the workflow

Write to `workflows/<name>.yaml` where `<name>` is snake-case lowercase, matching the workflow's `name:` field. If the user gave a specific filename, honour it; otherwise derive from the description.

### Step 5 — Validate

Run validation **in the same session** before reporting:

```python
from harness.workflow.loader import load_workflow
from pathlib import Path
loaded = load_workflow(Path("workflows/<name>.yaml"))
print(f"name={loaded.workflow.name}, steps={len(loaded.workflow.steps)}, types={[s.type for s in loaded.workflow.steps]}")
```

If `load_workflow` raises, **fix the YAML before reporting success**. The error message tells you what's wrong; the §10 pitfalls table covers the common ones.

A workflow that doesn't load is not a workflow — never report "done" without `load_workflow` returning cleanly.

### Step 6 — Report

Brief summary back to the user:

- Workflow path
- Step shape (e.g., "3-stage informational: fetch → summarise → write")
- Standard prompts used (and their `template_vars` if non-trivial)
- Any non-obvious design decisions
- Validation result (`load_workflow` output — name, step count, types)

If you logged any questions or design ambiguities, surface them — the user may want to clarify before the workflow gets used in anger.

## What this skill does NOT do

- **Doesn't run the workflow.** Authoring produces YAML; running is `slate-harness run <workflow>`.
- **Doesn't design new step types or grammar.** That's `SPEC.md` territory; outside this skill's scope.
- **Doesn't write Python contract classes.** Inline YAML contracts are canonical; sharing happens via `$contracts/<name>` (also YAML).
- **Doesn't reinvent state schemas.** State is *derived* from `writes:` declarations across the workflow — no `state_schema:` field exists.

## Reference

`AUTHORING.md` at the repo root. Don't repeat its content here; link to sections (§N) when relevant.

## Companion skill — ergonomics check

`.claude/skills/workflow-author-ergonomics.md` is the reproducible test of this skill's effectiveness. After material edits to `AUTHORING.md` or `harness/workflow/`, re-run that skill to catch regressions in the authoring surface.
