---
paths:
  - "agents/**"
  - ".codex/agents/**"
description: What binds while authoring a role definition and its Codex adapter.
---

# Authoring a role

A role ships twice: `agents/<role>.md` is what Claude Code dispatches, and
`.codex/agents/<role>.toml` is Codex's native adapter for the same role.
`tests/unit/test_codex_agent_adapters.py` holds the two bodies byte-equal, so
**every edit lands in both copies or the gate goes red.** The `.toml`'s leading
`#` block is a comment Codex never reads; the only reader-visible body is
`developer_instructions`.

## A `skills/` path in a role body resolves from the plugin root

Paths the plugin owns — `skills/`, `agents/`, `templates/`, `hooks/`, `.codex/`
— resolve from the **installed plugin's root**, never from the consumer
workspace. `tests/unit/test_native_codex_plugin.py` already holds the nine
workflow skills to that rule and states it in its own docstring; role bodies
are the same artefact class and carry the same rule, stated in the body rather
than guarded, because ADR 0017 D5 admits no guard over what prose means.

**The sentence cannot name a directory count.** A workflow skill can say *"two
directories above this SKILL.md"* because it ships in one place. A role body
cannot: it is byte-identical across `agents/` (one level under the plugin root)
and `.codex/agents/` (two), and `/harness:hydrate` step 9 vendors the `.toml`
into a *consuming* repo's `.codex/agents/`, where the plugin root is somewhere
else entirely and there is no `skills/` tree at all. Write the root by name, not
by position.

**A role that names no such path gets no sentence.** Adding the line to a body
that references nothing under `skills/` would be a second copy guarding nothing
(P0; the duplicated-operand refusal #640 ruled on).
