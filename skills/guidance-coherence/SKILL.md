---
name: guidance-coherence
description: Use when running the `system` scope of a `/assess` pass — the domain standards for the guidance system itself (skills, agents, commands, hooks, templates, process docs, CONTEXT). The seven coherence checks the steward applies: version integrity, the universal/repo boundary, reference resolution, MECE, lean, profile coherence, and CONTEXT currency. Load alongside `assessment-craft` (the methodology) for a `system` assessment, not for routine task work.
---
<!-- guidance:guidance-coherence@0.1.0 -->
# Guidance Coherence

The domain standards for the `system` scope of `/assess` — the coherence of the guidance system itself, the machinery agents work within. The `steward` pulls this skill just-in-time when the scope is `system`; the finding bar, severity, and insight test come from `assessment-craft`, and this skill supplies *what* a guidance assessment looks for.

You read the guidance as it exists, compare its parts against each other and against the filesystem, and report where it has drifted. You do not redesign it.

## Three lenses

| Lens | Definition | Catches |
|---|---|---|
| **MECE** | Every piece of knowledge has one source; other mentions are pointers, not copies. | Duplication, divergence risk. |
| **Lean** | Everything earns its keep; no longer or more complex than it needs to be. | Bloat, unused files, context pollution. |
| **Correct** | What is written matches what is true. | Stale references, wrong wiring, broken links. |

## The seven checks

1. **The universal/repo-specific boundary** — the load-bearing rule. Grep `skills/`, `agents/`, `commands/`, `process/`, `templates/` for repo proper-nouns, product names, workspace IDs, ticket numbers, or hardcoded paths that belong in a consuming repo's `CONTEXT.md`. Any leak is a **High** finding: it pollutes every repo that installs the file.
2. **Version integrity** — every distributable file's `guidance:` header version matches its entry in `registry.yaml`. A file edited without a version bump is invisible downstream — flag it. Every file in `registry.yaml` exists; every file on disk is registered.
3. **Reference resolution** — cross-references between files point at things that exist. A skill referenced by an agent exists; a template referenced by a command exists; a link resolves.
4. **MECE duplication** — the same rule stated in two files where one should be the source and the other a pointer. (Methodology duplicated into an agent that a skill already owns is the classic case.)
5. **Lean** — files or sections that no longer earn their keep; an agent that re-states a skill instead of loading it; a profile selecting a file nothing uses.
6. **Profile coherence** — `registry.yaml` profile membership is consistent; each profile's process doc and settings exist.
7. **CONTEXT currency** — the stack, commands, tracker, and paths recorded in `CONTEXT.md` still match the actual repo (the "Correct" lens applied to the repo's own facts file). A stale `CONTEXT.md` makes every agent start from wrong assumptions — flag the specific drift, **High** when it misroutes work (a wrong verify command, a wrong branch model).

## Output

Findings use the four parts and severity from `assessment-craft`, with IDs prefixed `SYSTEM-`; insights append `-INSIGHT`. A `system`-scope insight often targets the guidance directly — a hook to add, a section to move, a boundary to tighten. Zero findings is a legitimate, stated outcome.
