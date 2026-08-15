---
feature: guidance-system
status: implemented
last_updated: 2026-08-16
tickets: ["#401", "#407", "#354", "#288", "#434"]
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

### `/build` renders the stage obligations it does not own

`commands/build.md`'s `## Assurance` table is a rendering of `harness/assurance.py`, not a second home for the mapping. Its three rows state the evidence each level owes, and `tests/unit/test_build_assurance_workflow.py` parses those rows and asserts each equals `harness.assurance.required_stages(level)` with the expected values imported rather than restated. The parsed row set must equal `ASSURANCE_LEVELS`, so a level dropped, a fourth level invented, or a dead parser fails rather than passing over nothing, and the section's stated destination for missing, conflicting, or unrecognised assurance must equal `DEFAULT_ASSURANCE`. Prose and policy module therefore cannot drift apart in silence, and neither can two rows collapse onto the same obligations.

Three obligations make the policy enforceable on the agent-led path, which has no ledger to enforce it. A `complex` run whose design stage produces no usable design **stops**: absence, a failed design sub-agent, and an artifact that does not cover the change spec's contracts and scenarios are one outcome, and none of them licenses design-blind implementation. This is the agent-led counterpart of `harness/assurance.py`'s `DESIGN_NOT_USABLE_REASON` refusal. `## 3. Ship` binds every commit to the tree its assurance stage produced — `certified_tree` for a `trivial` run, `reviewed_tree` for a reviewed one — through the same `HEAD^{tree}` identity comparison and the same refusal to integrate on a mismatch, so the level that produces no verdict is no longer the level with no tree-identity check. And no one writes an as-built record on a `trivial` run: the certifier rejects any as-built-record surface, so a certified diff carries no shipped behaviour to record, and a change that does carry some fails certification and becomes a `simple` run where the reviewer records it. Writing one after `certified_tree` is the ordinary case of the invalidation rule, not an exception to it.

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

### Visual evidence is a capability of the agent-led review

The visual-evidence channel #361 built for the review engine survives ADR 0015's retirement of that engine as distributed guidance rather than as a flag. Three obligations, three single homes, and every other file a pointer.

`commands/build.md` → *Visual evidence for a user-facing change* is the one home for the **capture convention**, because it is where captures are produced. It states the trigger as the surface a diff touches rather than a risk judgment; that seeded state is synthetic throughout and never a copy of production data; that the capture unit is a **viewport-height slice**, one image per viewport in scroll order, and never the full page in one image at any width; that **no capture exceeds 2000 px in height**; and that a review carries **at most 12 captures**. Both numbers are stated with the measurement or cost that set them — the #361 capture that came back 1440 × 5726 px with 16 px body text reading 7 of 8 characters, and the token and latency cost of several large images — so neither reads as a magic constant. Over the cap the answer is to **narrow the set**, never to shrink or downscale the images, which would re-enter the downscale failure the slice rule exists to prevent.

Captures and their `manifest.md` land in `.evidence/<TICKET-ID>/` at the worktree root: repo-relative, so `/review` hands the reviewer a directory rather than a list, and keyed per ticket, so a stale capture from another ticket is visibly not this change's evidence. `.gitignore` ignores `.evidence/` unanchored, on the same reasoning already recorded there for `gate.log`. That line is the only thing between a rendered PNG of seeded state and the permanent history of a public repo, because `/build` runs `git add -A` twice; it also keeps captures out of the tree both `git write-tree` identity checks bind to. `.gitignore` is not a `registry.yaml` entry, so `/update-guidance` cannot install the line into a consuming repo — the *Where* paragraph closes that gap in prose instead, telling a repo whose `.gitignore` lacks the rule to add it **before** capturing anything. The ordering is the whole of that rule: adding the line afterwards is the sequence that publishes the captures.

`commands/review.md` → *Run the reviewer* is the one home for the **handoff**, supplying the capture directory and its manifest. `skills/review-discipline/SKILL.md` → *Reviewer obligations* → `Report:` is the one home for the **consulted / not-consulted line**: the report states whether visual evidence was consulted, naming the directory it read, or `not consulted` with exactly one of three reasons — `not a user-facing change`, `not supplied`, or `not readable by this reviewer`. The third is not decoration: an engine with no image-returning read tool would otherwise have to claim `consulted` or pick a false reason. A report silent on visual evidence is incomplete, and a `not consulted` carrying no reason is that same silence wearing a label. `agents/reviewer.md` and `commands/review.md` step 5 render that contract; `commands/start.md` step 6 points at the capture convention. None of them restates a number or a reason, and guards assert that they do not.

Every obligation is guarded as a **pair** on the pattern already established for `/build`'s stage obligations — a presence assertion that dies when the rule is deleted or re-worded past its bound keyword, and an inversion sweep that fires when a release is *appended* while the rule survives — with separate exclusive killers. Both numbers and the reason set are asserted **by value**, parsed out of the prose that states them rather than compared against a restated constant, and so are the operator-visible verdict tokens themselves. The ignore rule is proven behaviourally in a hermetic repo whose `.gitignore` is copied from the real one, because this checkout's `.git/info/exclude` carries local rules that would make a live-tree assertion pass regardless of the committed fix.

#### Scenario: a builder captures evidence for a user-facing change

- GIVEN a diff touching a user-facing surface
- WHEN the build loop finishes implementation
- THEN `.evidence/<TICKET-ID>/` holds viewport-height slices at the reference widths plus a `manifest.md`, no capture taller than 2000 px, none a full-page image, and at most twelve
- AND `git status --porcelain` and `git add -A` both pass over every one of them, so no capture reaches the committed tree

#### Scenario: a reviewer reports on a change with no rendered surface

- GIVEN a diff touching only tests and guidance prose
- WHEN the reviewer writes its report
- THEN the report carries `not consulted — not a user-facing change`, one of exactly three permitted reasons
- AND silence, or a bare `not consulted`, fails the report contract rather than reading as an answer

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
- `commands/build.md` → `## Assurance` is a rendering of `harness/assurance.py`'s level-to-stages mapping for the agent-led path, derived and checked against it rather than restating it, and carries the agent-led stop, ship-binding, and as-built-record-owner obligations for which the harness path has ledger enforcement.
- `skills/code-quality/SKILL.md` and `skills/review-discipline/SKILL.md` are the always-loaded cores for their domains and directly declare every conditional checklist trigger.
- `commands/build.md` → *Visual evidence for a user-facing change* is the one home for the capture convention — trigger, location, slice rule, height ceiling, and capture cap. `commands/review.md` → *Run the reviewer* owns the handoff of that directory; `skills/review-discipline/SKILL.md` → *Reviewer obligations* → `Report:` owns the consulted / not-consulted line and its closed three-reason set. `commands/start.md`, `agents/reviewer.md`, and `commands/review.md` step 5 are renderings that point rather than restate.
- `agents/reviewer.md` and `agents/steward.md` define role boundaries and route domain method to skills and commands.

## Known limitations

- UTF-8 `bytes / 4` is a stable context-budget heuristic, not an exact tokenizer count.
- Conditional guidance supports a hot root plus one reference level. A workflow that needs a deeper conditional tree must first change the topology contract and its guard.
- The assurance rubric is advisory prose an agent follows, so it is a quality control rather than a security boundary. The enforcing boundaries stay the repo's `assurance.trivial_certify` allowlist and the runtime fail-safe rewrite to `simple`; an applied label records that a choice was made, never that the choice was right.
- The guards over the rubric read prose, so they are bounded by sentence segmentation and by how tightly each polarity token is anchored to the verb it governs. They catch a rule deleted, negated, or excepted; a permission whose negation sits one or two words before the inference verb, and an uncertainty routed to a level the choice verb does not immediately name, are outside their reach.
- `harness/cli/promote.py`'s escalation files through `Tracker.create_issue`, which takes no labels, so a promotion escalation is filed without an assurance level and resolves to `simple`.
- The guards over `/build`'s stage obligations read polarity per occurrence, anchoring each negation to the verb it governs across a gap of at most two words that may contain no blocking verb. Measured escapes, recorded at their size rather than papered over: an **outer negation over a well-formed inner prohibition** (*"There is no rule that a mismatch must not be integrated"*, *"A thin design is not a reason the run cannot proceed"*) is spelled correctly in its inner clause and grants in its matrix clause, which no token-window anchor reaches; closing it needs clause structure, and a double-negation heuristic is not available because the rules' own sentences carry two and three negation tokens. A design-stage exception worded with `implement` rather than a continuation verb is likewise uncovered, because widening the continuation vocabulary would make the rule's own sentence an offender.
- The derived `## Assurance` table check reads *is there an un-negated unit naming this obligation*, so a **release clause appended to a row cell** — *"The reviewer sub-agent is optional"* — leaves the derived stages unchanged while the prose releases the obligation. The direction is deliberate: the `trivial` cell states both obligation nouns under a `never`, and an obligation appended with the `never` intact is the drift that must fail. The release direction is not covered.
- The `## 3. Ship` inversion sweeps recognise an enumerated release and mismatch vocabulary, unlike the design sweep, which flags any continuation verb no negation governs and so fails closed. An appended grant outside that vocabulary (*"the `certified_tree` check is a formality"*, *"integration proceeds even when the trees differ"*) escapes, and the permissive as-built-record sweep requires the literal noun `as-built record`, so a grant spelled *"record what shipped"* escapes too. Deleting or replacing a rule is caught in every case; appending a contradiction in fresh vocabulary is not.

- The visual-evidence inversion sweeps are **blacklists of release vocabulary**, so like every sweep here they fail open on a grant worded outside that vocabulary. Measured at review, one wording at a time against the real documents rather than assumed: the full-page sweep caught six of ten independently written permissions and missed *"one image of the entire page is preferable to slices"*, *"a short page may be captured whole"*, and *"prefer a single full-page image where the surface fits"* — all three release in an adjective or a comparative rather than a verb the release arm names. The report-line sweep is the weaker of the two and caught **none** of six (*"at the reviewer's judgment"*, *"recommended but not mandatory"*, *"where it adds value"*, *"skip … for a docs-only diff"*, *"encouraged"*, *"nothing requires …"*). The paraphrase tuples that guard both sweeps are drawn from the same vocabulary the sweeps recognise, so they measure coverage of themselves rather than robustness; they are a floor against a single-wording check, not evidence of paraphrase completeness. Widening the alternation was considered and declined at review: a blacklist has no completion condition, and each widening risks flagging the rule it protects. The presence halves, which are value-asserted, are what actually hold a deleted or re-worded rule.
- Nothing authenticates that a capture depicts the reviewed SHA, and `consulted` records only that the reviewer looked. The guidance states the capture convention; it adds no refusal for a user-facing change whose builder produced nothing, so a missing capture set is a Stage-1 finding a reviewer makes rather than a mechanism.

## Decisions

### Decision: The capture convention lands in `/build`, not in `ux-design`

*Decided 2026-08-15 (#434), reversing `specs/proposals/visual-evidence-for-review.md`.*

**Context.** The proposal's change 2 of 2 (#362) placed the build-loop rendering guidance "in the `/build` and `/harness run` implement step **and** in the `ux-design` skill", on the reasoning that `ux-design` is not gated on the `design_system` layer and so applies wherever there is a surface. ADR 0015 then retired `/harness run`, leaving one agent-led path.

**Decision.** The capture convention has exactly one home, `commands/build.md` → *Visual evidence for a user-facing change*, and `ux-design` is not touched. `commands/start.md`, `commands/review.md`, and `agents/reviewer.md` carry pointers to it.

**Alternatives.**

- *Also state the convention in `ux-design`* — the proposal's plan. It puts the slice rule, the location, and both numbers in two files with nothing deriving one from the other, which is the drift the single-home rule exists to prevent; the repo has already paid for that shape.
- *Move the convention into `ux-design` alone* — separates the rule from the step that produces the captures, so a builder reading `/build` would have to know to open a skill to learn where its output goes.

**Consequences.** The convention lives where the captures are made, and reaches a `ux-design` reader through `/build` and `/start` rather than through a second copy. A repo that wants the rule without `/build` does not get it — accepted, because no such repo exists today and the pointer is one line to add when one does. Guards assert that no number and no reason phrase appears outside its home.

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
