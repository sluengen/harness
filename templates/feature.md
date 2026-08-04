<!-- guidance:template-feature@0.2.1 -->
---
feature: {short-slug}
status: implemented        # implemented | partial | planned
last_updated: YYYY-MM-DD    # day of the last commit that changed this file — bump it on every content edit
linear: [CAL-NNN]          # Linear issues that shaped this feature
---

# {Feature name}

> One sentence: what this feature is and who it serves.

## Behaviour

What the product does today. Present tense, not "we will". This section is the canonical answer to "how does {feature} work?"

### {Surface or sub-behaviour}

Group by user-visible behaviour, not by code module. One coherent surface per section.

#### Scenario: {name}

- GIVEN {precondition}
- WHEN {action}
- THEN {outcome}

Use scenarios where behaviour is non-obvious or edge cases are easy to forget.

## Data model

Tables, fields, relationships, invariants. Omit if the feature has no persistent state.

## Interface surface

Endpoints, commands, or component contracts: shapes, auth rules, error cases. **Name the production call site for each exported entry — a test is not a consumer. An entry with no production caller is recorded under Known limitations as "no consumer yet: adopt or retire by {ticket}", never listed as delivered API.** Brief; point to the generated contract (OpenAPI, types) for full detail. Omit if not applicable.

## Known limitations

What the feature deliberately does not do, and edge cases known to be unhandled. Each references its tracking ticket if one exists.

## Decisions

Consequential decisions that shaped this feature, recorded inline (`templates/decision.md`): context, decision, alternatives rejected, consequences. Superseded decisions are updated in place with a dated note. Omit if the feature carries none.

## Cross-references

- specs/features/{related-feature}.md

---

**Editing rule.** This file is written by the **reviewer**, not the builder, when a Linear issue touching the feature lands — based on what the diff actually does, as the last commit before merge. The builder may draft a rewrite hint in the change spec, but the canonical version here is the reviewer's record. The agent that promises is not the agent that records delivery (`spec-driven-development`).
