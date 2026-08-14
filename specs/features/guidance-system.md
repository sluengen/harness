---
feature: guidance-system
status: implemented
last_updated: 2026-08-15
tickets: ["#401", "#407", "#354"]
---

# Guidance system

> Versioned, progressively disclosed instructions give agents the current contract for this repo without loading unrelated provider, workflow, or review detail.

## Behaviour

### Hot startup context

Agents begin with the generated process mirror and `CONTEXT.md`. The process mirror owns the universal lifecycle map and its non-negotiable test-first, worktree, independent-review, measurable-test, fresh-evidence, and as-built authorship rules. `CONTEXT.md` owns current repo values, concise constraints, and pointers to the records that hold rationale and history.

`process/harness.md` is the source for the root process mirrors. The distribution guards require `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` to remain byte-identical to it.

#### Scenario: an agent starts ordinary work

- GIVEN an agent loads the required root process mirror and `CONTEXT.md`
- WHEN it begins work in this repo
- THEN the active path contains the lifecycle invariants and current GitHub, branch, loop, path, and verification configuration
- AND historical tuning evidence and inactive provider recipes remain behind explicit pointers

### Tracker dispatch and filing

The `tracker` skill reads the top-level `CONTEXT.md:tracker` value and loads only the matching provider skill. Active repo guidance uses provider-neutral terms unless a provider condition is explicit.

`tracker.create` is the filing contract. It accepts a title, UTF-8 body file, exactly one assurance level, optional labels or priority, and mandatory Todo placement. The selected provider resolves identifiers at runtime, creates the issue, attaches it to the configured queue or project, applies the assurance label, and sets Todo explicitly. It returns the canonical identifier and URL only after placement succeeds. The caller reports a partial creation and never creates a duplicate, deletes the issue, or switches providers.

Capture commands gather their distinct content and delegate filing to this contract. Provider skills retain the API commands, credentials, body-file boundary, and placement recipe.

#### Scenario: placement fails after issue creation

- GIVEN the provider creates an issue but cannot attach it to the queue or set Todo
- WHEN `tracker.create` reports the result
- THEN the caller reports the existing issue identifier and URL and stops
- AND it does not create a duplicate, delete the issue, switch providers, or claim full success

### Assurance is chosen once, at filing

A created issue carries exactly one recognized `assurance:<level>` label. Assurance is a postcondition of `tracker.create`, not a hint: the provider confirms the label by re-reading the created issue rather than by trusting an exit status, and a provider that cannot apply exactly one — the backend has no such label, two landed, or the write was refused — reports the filing incomplete with its identifier and URL and stops rather than returning a queue-ready identifier.

Two directions are kept apart deliberately. `harness/assurance.py` answers *given a level, which stages must this run pay for*, and resolves anything missing, doubled, or unrecognized to `simple`. `skills/spec-authoring/SKILL.md` → *Choosing assurance* answers *given this work, which level does the filer put on it*, and is the single home for that judgment: `trivial` for a diff inside the repo's configured allowlist carrying no unresolved design or public-contract decision, `simple` as the default, `complex` for consequential architecture, data-model, interface, or security decisions or work spanning more than one lifecycle contract. Two rules carry the weight — uncertain work is `simple`, and `trivial` is never inferred from low severity, a short description, or a small estimated diff alone. The rubric states no level-to-stages mapping and the policy module carries no selection advice.

Every registered surface that files an issue names the rubric inside the instruction that files, and restates none of it: `/bug`, `/tweak`, `/propose`, `/assess`, `/harness ingest`, `/harness routine quality`, and `/build`'s DEFER path. `templates/change.md` and `/start` step 5 point at it too — they choose a level without filing. Existing unlabelled issues are not backfilled; they resolve to `simple` through the policy core.

#### Scenario: a provider cannot apply the assurance label

- GIVEN a filing surface passes `tracker.create` a title, a body file, and one chosen assurance level
- WHEN the provider creates the issue but the assurance label does not exist in the backend, or two land
- THEN the filing is reported incomplete with its identifier and URL and stops
- AND no queue-ready identifier is returned, because a queue reader treats an unclassified ticket as a classified one

#### Scenario: a filer cannot place the work

- GIVEN a filer writing a change spec who cannot confidently place the work
- WHEN the level is chosen
- THEN it is `simple`
- AND neither low severity, a short description, nor a small estimated diff on its own earns `trivial`, since all three are authored by whoever opened the issue

### One-level progressive disclosure

`commands/harness.md` is the public `/harness` router and shared contract. It selects exactly one registered workflow body for `run`, `routine build`, `routine quality`, or `ingest`. A bare command, unknown form, or missing required argument prints the supported forms and stops without mutation. Ticket content cannot choose a reference.

The `code-quality` core keeps scope, structure, production-real test inputs, measuring tests, fresh evidence, and gate ordering. It directly links the untrusted-fetch checklist and the specialized verification checklist, each with an explicit activation trigger. The `review-discipline` core keeps the two review stages, general quality bar, severity, finding shape, reviewer obligations, final-evidence ordering, and review-cycle stop policy. It directly links the diff-shape checklist and names the shapes that activate it.

Conditional references are one level deep. The topology guard discovers the reference directories, requires the exact registered set, checks matching version stamps, and rejects nested conditional references.

#### Scenario: `/harness run` is invoked

- GIVEN the public router receives `/harness run <ISSUE-ID>`
- WHEN the agent resolves its guidance
- THEN it reads the router and `commands/harness/run.md` completely
- AND it does not load the routine or ingest workflow bodies

### Roles and distribution

Reviewer and steward agent bodies contain role, authority, supplied inputs, output expectations, and skill routing. Review method, assessment lenses, and repo-runtime engine history stay in their owning skills, commands, specs, and decisions.

Every conditional reference is a normal versioned registry entry. The generator creates adapters only for top-level commands; the Codex command adapter points to the `/harness` router, and skill-directory exposure includes their reference directories. Generated agent TOML preserves the concise source role body.

### Source-version integrity

For an equal source and lock version, `/update-guidance` classifies a file as `current` or `LOCAL` only when the fetched source hash matches the locked hash. A mismatch is `SOURCE DRIFT` regardless of the consumer's on-disk state. It stops the entire update before apply, reports the file and source/locked hashes, and requires the source file and registry version to be repaired.

`SOURCE DRIFT` leaves every installed file and `.guidance-lock.yaml` entry unchanged, including `source.ref`. It cannot enter conflict resolution or be accepted or overwritten locally.

### Measured active paths

The footprint guard uses the same UTF-8 `bytes / 4` estimate as `hooks/context-monitor.js`.

| Active path | Before #401 | As built |
|---|---:|---:|
| Required `AGENTS.md` + `CONTEXT.md` startup | 12,439.5 tokens | 5,408 tokens |
| Startup plus `/harness run` guidance | 29,176 tokens | 8,278.75 tokens |
| Startup plus `/harness routine build` guidance | 29,176 tokens | 6,739.5 tokens |
| Startup plus `/harness routine quality` guidance | 29,176 tokens | 5,964.75 tokens |
| Startup plus `/harness ingest` guidance | 29,176 tokens | 6,060.25 tokens |
| `code-quality` core | 5,226.75 tokens | 2,771.25 tokens |
| `review-discipline` core | 5,366.25 tokens | 3,252 tokens |
| Reviewer role | 985 words | 362 words |
| Steward role | 1,774 words | 248 words |

The command-payload guard measures the router plus its selected workflow, independently of required startup context. Every activated `/harness` command payload is below 5,000 estimated tokens.

## Data model

The guidance system changes no runtime application data. `registry.yaml` records each distributed source file's stable id, version, and profile. Registry/header checks where headers apply, plus derived-artifact parity, make version and distribution drift gate failures.

## Interface surface

- `commands/harness.md` is the public `/harness` command contract and routes to one workflow body.
- `skills/tracker/SKILL.md` owns provider-neutral tracker operations, including assurance as a `create` input and postcondition; the configured provider skill owns execution details and maps the chosen level to a label without carrying the rubric.
- `skills/spec-authoring/SKILL.md` → *Choosing assurance* is the one home for how a filing-time assurance level is chosen; `harness/assurance.py` remains the one home for what a level obliges a run to pay for.
- `skills/code-quality/SKILL.md` and `skills/review-discipline/SKILL.md` are the always-loaded cores for their domains and directly declare every conditional checklist trigger.
- `agents/reviewer.md` and `agents/steward.md` define role boundaries and route domain method to skills and commands.

## Known limitations

- UTF-8 `bytes / 4` is a stable context-budget heuristic, not an exact tokenizer count.
- Conditional guidance supports a hot root plus one reference level. A workflow that needs a deeper conditional tree must first change the topology contract and its guard.
- The assurance rubric is advisory prose an agent follows, so it is a quality control rather than a security boundary. The enforcing boundaries stay the repo's `assurance.trivial_certify` allowlist and the runtime fail-safe rewrite to `simple`; an applied label records that a choice was made, never that the choice was right.
- The guards over the rubric read prose, so they are bounded by sentence segmentation and by how tightly each polarity token is anchored to the verb it governs. They catch a rule deleted, negated, or excepted; a permission whose negation sits one or two words before the inference verb, and an uncertainty routed to a level the choice verb does not immediately name, are outside their reach.
- `harness/cli/promote.py`'s escalation files through `Tracker.create_issue`, which takes no labels, so a promotion escalation is filed without an assurance level and resolves to `simple`.

## Decisions

### Decision: Use hot roots with one level of registered references

*Decided 2026-08-11.*

**Context.** Required startup guidance and the monolithic `/harness`, code-quality, review-discipline, reviewer, and steward surfaces mixed frequently used invariants with provider recipes, workflow-specific procedures, assessment lenses, and historical rationale. Agents paid that context cost before reading the ticket or code, while duplicated ownership allowed active GitHub guidance to retain Linear instructions.

**Decision.** Keep universal and commonly applicable contracts in hot root documents. Move conditional workflow and checklist detail into direct, one-level references that the root names with explicit triggers and that the registry versions and distributes.

**Alternatives.**

- *Keep monolithic roots and edit for brevity* — retained unrelated activation cost and did not create an ownership boundary that guards could enforce.
- *Allow unrestricted nested references* — reduced individual file size but made the activated corpus hard to predict and let required instructions hide behind reference chains.
- *Create a new documentation framework* — added machinery and migration cost when the existing registry, generator, and tests already enforce distribution.

**Consequences.** Ordinary paths load fewer instructions while public names, lifecycle order, tracker states, and safety gates remain stable. Every new conditional file must be linked directly, registered, versioned, distributed, and covered by topology and semantic guards. Root documents must retain the invariants needed before any reference is selected.

## Cross-references

- [verb-model.md](verb-model.md)
- [cli-surface.md](cli-surface.md)
- [../architecture-principles.md](../architecture-principles.md)
