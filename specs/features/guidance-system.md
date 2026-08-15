---
feature: guidance-system
status: implemented
last_updated: 2026-08-15
tickets: ["#401", "#407", "#354", "#288", "#435"]
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
- THEN the active path contains the lifecycle invariants and current GitHub, branch, path, and verification configuration
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

Two directions are kept apart deliberately. `commands/build.md` → `## Assurance` answers *given a level, which stages must this run pay for*, and sends anything missing, conflicting, or unrecognised to `simple`. `skills/spec-authoring/SKILL.md` → *Choosing assurance* answers *given this work, which level does the filer put on it*, and is the single home for that judgment: `trivial` for a diff inside the repo's configured allowlist carrying no unresolved design or public-contract decision, `simple` as the default, `complex` for consequential architecture, data-model, interface, or security decisions or work spanning more than one lifecycle contract. Two rules carry the weight — uncertain work is `simple`, and `trivial` is never inferred from low severity, a short description, or a small estimated diff alone. The rubric states no level-to-stages mapping and the stage table carries no selection advice.

Every registered surface that files an issue names the rubric inside the instruction that files, and restates none of it: `/bug`, `/tweak`, `/propose`, `/assess`, and `/build`'s DEFER path. `templates/change.md` and `/start` step 5 point at it too — they choose a level without filing. Existing unlabelled issues are not backfilled; they resolve to `simple` through the policy core.

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

### `/build` owns the stage obligations

`commands/build.md`'s `## Assurance` table is the one home for the level-to-stages mapping. It was a *rendering* of a policy module until #435, when ADR 0015 deleted the module and the ledger beside it; the table is what survived, and it is now read directly rather than checked against a second copy. Its three rows state the evidence each level owes, and its stated destination for missing, conflicting, or unrecognised assurance is `simple`.

Three obligations make the policy enforceable on the agent-led path, which is now the only path and has no ledger to enforce it. A `complex` run whose design stage produces no usable design **stops**: absence, a failed design sub-agent, and an artifact that does not cover the change spec's contracts and scenarios are one outcome, and none of them licenses design-blind implementation. Absence of a usable design is a stop, not a degradation. `## 3. Ship` binds every commit to the tree its assurance stage produced — `certified_tree` for a `trivial` run, `reviewed_tree` for a reviewed one — through the same `HEAD^{tree}` identity comparison and the same refusal to integrate on a mismatch, so the level that produces no verdict is no longer the level with no tree-identity check. And no one writes an as-built record on a `trivial` run: the certifier rejects any as-built-record surface, so a certified diff carries no shipped behaviour to record, and a change that does carry some fails certification and becomes a `simple` run where the reviewer records it. Writing one after `certified_tree` is the ordinary case of the invalidation rule, not an exception to it.

Each obligation is guarded as a **pair** — a presence assertion that the rule is stated, and an inversion sweep that fires when a unit grants what the rule forbids — because a presence assertion alone passes on text stating the opposite. The two halves carry separate exclusive killers: deleting a rule kills presence alone, and splicing a permissive sentence in its place kills the sweep alone. Every control mutates the real file text and asserts its splice landed, so a control cannot silently measure unmodified prose or pass on a hand-written clean string.

#### Scenario: a level's row is softened in the command but not in the policy module

- GIVEN `commands/build.md`'s `## Assurance` table drops an obligation from a row, collapses two rows onto the same evidence, or sends unresolved assurance to `trivial`
- WHEN the guard parses the table
- THEN the derived stages no longer equal `harness.assurance.required_stages` for that level and the suite fails
- AND the expected side is imported, so a misreading of the prose fails rather than passes

#### Scenario: a `complex` run's design stage returns nothing usable

- GIVEN a `complex` run whose design sub-agent produced no artifact, failed, or returned one that does not cover the change spec's contracts and scenarios
- WHEN the orchestrator reaches implementation
- THEN the run stops, unconditionally, and re-runs the design stage or abandons and names the design stage as what failed
- AND no qualifier releases the stop; a stop made discretionary in either word order fails the guard

### One-level progressive disclosure

The `code-quality` core keeps scope, structure, production-real test inputs, measuring tests, fresh evidence, and gate ordering. It directly links the untrusted-fetch checklist and the specialized verification checklist, each with an explicit activation trigger. The `review-discipline` core keeps the two review stages, general quality bar, severity, finding shape, reviewer obligations, final-evidence ordering, and review-cycle stop policy. It directly links the diff-shape checklist and names the shapes that activate it.

Conditional references are one level deep. The topology guard discovers the reference directories, requires the exact registered set, checks matching version stamps, and rejects nested conditional references. Ticket content cannot choose a reference.

The routing half of this behaviour went with the runtime. A `/harness` router selected one of four registered workflow bodies for `run`, `routine build`, `routine quality` and `ingest`; #435 deleted all five documents, so the only conditional references left are the two checklists below, reached from their cores by an explicit trigger.

#### Scenario: a conditional checklist is activated

- GIVEN an agent has loaded the `code-quality` core and reaches an untrusted fetch
- WHEN it resolves the trigger the core states
- THEN it reads that one checklist completely
- AND it does not load the diff-shape checklist, which belongs to a different core

### Roles and distribution

Reviewer and steward agent bodies contain role, authority, supplied inputs, output expectations, and skill routing. Review method, assessment lenses, and repo-runtime engine history stay in their owning skills, commands, specs, and decisions.

Every conditional reference is a normal versioned registry entry. The generator creates adapters only for top-level commands, and skill-directory exposure includes their reference directories. Generated agent TOML preserves the concise source role body.

### Source-version integrity

For an equal source and lock version, `/update-guidance` classifies a file as `current` or `LOCAL` only when the fetched source hash matches the locked hash. A mismatch is `SOURCE DRIFT` regardless of the consumer's on-disk state. It stops the entire update before apply, reports the file and source/locked hashes, and requires the source file and registry version to be repaired.

`SOURCE DRIFT` leaves every installed file and `.guidance-lock.yaml` entry unchanged, including `source.ref`. It cannot enter conflict resolution or be accepted or overwritten locally.

### Measured active paths

The footprint guard uses the same UTF-8 `bytes / 4` estimate as `hooks/context-monitor.js`.

| Active path | Before #401 | As built |
|---|---:|---:|
| Required `AGENTS.md` + `CONTEXT.md` startup | 12,439.5 tokens | 5,408 tokens |
| `code-quality` core | 5,226.75 tokens | 2,771.25 tokens |
| `review-discipline` core | 5,366.25 tokens | 3,252 tokens |
| Reviewer role | 985 words | 362 words |
| Steward role | 1,774 words | 248 words |

Four rows were dropped in #435 rather than re-measured: each was a `/harness` command payload — the router plus one selected workflow body — and all five documents are deleted. Their bound (every activated payload below 5,000 estimated tokens) went with them; re-pointing it at the surviving reference trees would have invented a limit nothing has ever held them to.

## Data model

The guidance system changes no runtime application data. `registry.yaml` records each distributed source file's stable id, version, and profile. Registry/header checks where headers apply, plus derived-artifact parity, make version and distribution drift gate failures.

## Interface surface

- `skills/tracker/SKILL.md` owns provider-neutral tracker operations, including assurance as a `create` input and postcondition; the configured provider skill owns execution details and maps the chosen level to a label without carrying the rubric.
- `skills/spec-authoring/SKILL.md` → *Choosing assurance* is the one home for how a filing-time assurance level is chosen.
- `commands/build.md` → `## Assurance` is the one home for what a level obliges a run to pay for, and carries the stop, ship-binding, and as-built-record-owner obligations that nothing else enforces now the ledger is gone.
- `skills/code-quality/SKILL.md` and `skills/review-discipline/SKILL.md` are the always-loaded cores for their domains and directly declare every conditional checklist trigger.
- `agents/reviewer.md` and `agents/steward.md` define role boundaries and route domain method to skills and commands.

## Known limitations

- UTF-8 `bytes / 4` is a stable context-budget heuristic, not an exact tokenizer count.
- Conditional guidance supports a hot root plus one reference level. A workflow that needs a deeper conditional tree must first change the topology contract and its guard.
- The assurance rubric is advisory prose an agent follows, so it is a quality control rather than a security boundary. The one enforcing boundary left is the repo's own `assurance.trivial_certify` command — a repo-supplied script, kept by ADR 0015 — whose allowlist fails closed and upgrades anything it cannot certify to `simple`; an applied label records that a choice was made, never that the choice was right.
- The guards over the rubric read prose, so they are bounded by sentence segmentation and by how tightly each polarity token is anchored to the verb it governs. They catch a rule deleted, negated, or excepted; a permission whose negation sits one or two words before the inference verb, and an uncertainty routed to a level the choice verb does not immediately name, are outside their reach.
- The guards over `/build`'s stage obligations read polarity per occurrence, anchoring each negation to the verb it governs across a gap of at most two words that may contain no blocking verb. Measured escapes, recorded at their size rather than papered over: an **outer negation over a well-formed inner prohibition** (*"There is no rule that a mismatch must not be integrated"*, *"A thin design is not a reason the run cannot proceed"*) is spelled correctly in its inner clause and grants in its matrix clause, which no token-window anchor reaches; closing it needs clause structure, and a double-negation heuristic is not available because the rules' own sentences carry two and three negation tokens. A design-stage exception worded with `implement` rather than a continuation verb is likewise uncovered, because widening the continuation vocabulary would make the rule's own sentence an offender.
- The derived `## Assurance` table check reads *is there an un-negated unit naming this obligation*, so a **release clause appended to a row cell** — *"The reviewer sub-agent is optional"* — leaves the derived stages unchanged while the prose releases the obligation. The direction is deliberate: the `trivial` cell states both obligation nouns under a `never`, and an obligation appended with the `never` intact is the drift that must fail. The release direction is not covered.
- The `## 3. Ship` inversion sweeps recognise an enumerated release and mismatch vocabulary, unlike the design sweep, which flags any continuation verb no negation governs and so fails closed. An appended grant outside that vocabulary (*"the `certified_tree` check is a formality"*, *"integration proceeds even when the trees differ"*) escapes, and the permissive as-built-record sweep requires the literal noun `as-built record`, so a grant spelled *"record what shipped"* escapes too. Deleting or replacing a rule is caught in every case; appending a contradiction in fresh vocabulary is not.

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

- [../architecture-principles.md](../architecture-principles.md)
- [../decisions/0015-harness-v4-thin-verification-layer.md](../decisions/0015-harness-v4-thin-verification-layer.md)
