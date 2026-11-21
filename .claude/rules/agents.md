---
paths:
  - "agents/**"
description: What binds while authoring a role definition.
---

# Authoring a role

**A role's instructions live in a skill; an agent file is a runtime profile.**
The file holds the role's settings — `name`, `description`, `tools`,
`isolation`, `model`, `effort`, and on Claude Code `skills:` — and a one-line
body naming the skill section the role follows. Nothing a second host would need
a copy of goes in it. A rule a role needs is written into that skill, never into
the body. `specs/architecture-principles.md` → *Decision: A role's instructions
live in a skill; an agent file is a runtime profile* records why.

**The body names its skill by name, never by a `skills/` path.** A name
resolves on both hosts. A path does not: the body is read in a consuming repo's
workspace, by Claude Code as the agent's prompt and by Codex at the head of a
built-in agent's brief (the spine's *Roles* bullet), and that workspace has no
`skills/` tree. A reference file is named relative to its skill, as in "`references/audit.md`
in the `hydrate` skill".

**`skills:` lists the skill the body names, namespaced `harness:<skill>`.** The
host injects that skill's `SKILL.md` into the role at start, so a role that never
opens the skill still holds it. A name that does not resolve is skipped with a
debug-log warning and nothing else, so a new entry is checked by dispatching the
role and asking for a line of the skill it was not told to read. A skill
carrying `disable-model-invocation: true` cannot be preloaded, so a role whose
skill is one of those carries no `skills:` and its dispatcher hands it the path:
`harness-audit` follows a reference in `hydrate`, and hydrate step 12 says so.
