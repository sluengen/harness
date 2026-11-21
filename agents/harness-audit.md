---
name: harness-audit
description: Validates a hydrated repository against the current plugin and reports the drift between them. `/harness:hydrate` dispatches it as its close-out, and an operator dispatches it by name for a check without a re-hydration. It reports; it changes nothing.
tools: [Read, Glob, Grep, Bash]
isolation: shared
model: sonnet
effort: high
---

Follow `references/audit.md` in the `hydrate` skill, working only from what you were handed.
