---
feature: guidance-system
status: implemented
last_updated: 2026-08-16
tickets: ["#401", "#407", "#354", "#288", "#434", "#435", "#436", "#437"]
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
- THEN the derived stages no longer equal the stages the row is expected to require and the suite fails
- AND the expected side is stated independently of the prose, so a misreading of the table fails rather than passes

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

The `code-quality` core keeps scope, structure, production-real test inputs, measuring tests, fresh evidence, and gate ordering. It directly links the untrusted-fetch checklist and the specialized verification checklist, each with an explicit activation trigger. The `review-discipline` core keeps the two review stages, general quality bar, severity, finding shape, reviewer obligations, final-evidence ordering, and review-cycle stop policy. It directly links the diff-shape checklist and the craft reference, and names the shapes that activate each.

Conditional references are one level deep. The topology guard discovers the reference directories, requires the exact registered set, checks matching version stamps, and rejects nested conditional references. Ticket content cannot choose a reference.

The routing half of this behaviour went with the runtime. A `/harness` router selected one of four registered workflow bodies for `run`, `routine build`, `routine quality` and `ingest`; #435 deleted all five documents, so the conditional references left are the untrusted-fetch and specialized-verification checklists under `code-quality`, and the diff-shape checklist and the craft reference under `review-discipline`, each reached from its core by an explicit trigger.

#### Scenario: a conditional checklist is activated

- GIVEN an agent has loaded the `code-quality` core and reaches an untrusted fetch
- WHEN it resolves the trigger the core states
- THEN it reads that one checklist completely
- AND it does not load the diff-shape checklist, which belongs to a different core

### The craft reference under `review-discipline`

`skills/review-discipline/references/craft.md` is the conditional reference `review-discipline` links alongside the diff-shape checklist. It carries forty-three named patterns in six families — vacuity, prose predicates and text guards, deletion/retirement/re-homing, mutation discipline, the ticket and its criteria, and unmeasured claims. Each entry is a name, the rule in one line, and the falsifying example where a fully green suite shipped the defect; the example is the load-bearing half, and the file says so.

Mutation discipline covers a surviving mutation from both sides. A survivor has four readings, and the inert one — the mutation changed nothing — voids the rest, so an *inert* survivor is unproven rather than evidence of a weak guard, and the entry that says so is pointed at from the ambiguity entry by name. Where the subject is prose there is no observable to declare, so liveness is built into the experiment instead: a **paired splice** puts a form the predicate is known to catch and the form under test at the same location in the same file, and the known form must die first. Both are stated tool-agnostically, so they carry into a repo with no mutation instrument of its own.

Four diff shapes are the activation trigger both roots state — a guard, a prose predicate, a mutation table, a deletion pass. `skills/review-discipline/SKILL.md` Stage 2 states it for the reviewer, and `commands/build.md` states it twice, at the implementation brief (read it before writing the test) and at the review brief. *The ticket and its criteria* and *Unmeasured claims* are not gated on those shapes, and the file's preamble now names them rather than locating them: a ticket's grounding and a claim nothing measures are read at different moments in the loop.

The file is distilled rather than transplanted. It states every pattern generally and carries no provenance — no ticket ids, no cites to app-only paths, no nesting of its sibling reference — and those three constraints are already-live sweeps that pick it up as a registered prose member rather than new machinery. It restates nothing its core owns: the finding 2×2, final-evidence ordering, criteria currency, the diff-shape structural checks, and `code-quality`'s fresh-evidence rule stay where they are, and the preamble names each of those homes.

Its guard derives the family and pattern sets from the file rather than listing them. The family set is pinned as an **equality**, so an unrecorded new family is as loud as a lost one; fourteen named patterns are pinned by **membership**, so a rename surfaces as a missing name instead of shrinking a set behind a count that still passes; and two floors sit just under their measured values — forty-three patterns and a 357-character shortest body. The non-vacuity assertion is a test of its own rather than a line inside the body sweep, because that sweep iterates the derived pattern set and would pass over an empty one.

Three assertions pair those derivations rather than extending either. The ambiguity entry must name the inert entry by its exact heading, so the pointer fails loudly on a rename instead of dangling; the three survivor entries must sit under `Mutation discipline`; and the ordinal entry must sit under `Unmeasured claims`. The family set and the pattern set are each derived alone and neither knows a heading's *home*, so a pattern migrating between existing families leaves the set, the order, the count and every required name unchanged. Only the entries whose family was argued on their ticket are pinned to a home — those three, plus *An ordinal reference into an enumeration is invalidated by a correct insertion*; a hand-written family for all forty-odd would be a second copy of the file's structure. The two family assertions are separate tests, so each has its own killer. None of the three reads the entries for agreement, and the guard's own docstring records that a link to an entry that contradicts it passes.

*Unmeasured claims* also carries the structural edit the file had been missing. *A control goes inert when the change deletes what it names* covers deletion and *A deletion pass that moves a definition must move its killer* covers relocation; *An ordinal reference into an enumeration is invalidated by a correct insertion* covers insertion, where the edit, the text it edits, and the sentence it breaks are each correct alone and the defect exists only between them. Its rule is that a reference names its referent, never its index. It sits beside *A forward reference becomes a lie the day its dependency ships* on the boundary that a forward reference was never true, while an ordinal reference was true until a later correct edit invalidated it.

Adding it applied it. A sweep of the file for references identifying a member of an enumeration by position found five: the preamble locating two families as "the last two", "satisfies the first shape", "the second assertion", and "the first reading … the other three" in the ambiguity entry were rewritten to name their referents; "the twin of the false-kill entry below" was kept, because it names its referent and `below` is only a locator. The same class had already gone stale in this record — it described the craft reference as "the third conditional reference" when four exist, an error that shipped with the reference itself and survived one later change to the same paragraph. That is fixed here.

What none of this proves, measured rather than assumed. No guard reads ordinals, and the ticket declined to add one: any predicate that could catch the class is a pinned count, which the file's own *Floors decay into decoration* says rots on the next insertion. The class is caught by a reader, and the entry exists to make the reader look. Nor is the entry pinned to a position within its family — the ticket settled its family and said nothing about its neighbour, so a neighbour pin would guard a decision nobody made. The pattern floor is slack by design and was measured at that slack: removing two entries takes the file from forty-three to forty-one and stays green, so the floor catches a family-sized loss and not an entry-sized one. The preamble's naming of the two ungated families is unguarded prose — measured by a paired splice, where a short-bodied heading spliced into the same block died on the body floor while rewriting the preamble to name the wrong two families changed nothing red. And the two entries cross-reference each other by different means: *A survivor is ambiguous* names *An inert mutation reports a survivor it never earned* by exact heading, which is pinned and was confirmed still load-bearing after the sweep rewrote the sentence carrying it, while the inert entry points back with a description rather than a heading, which nothing checks.

#### Scenario: the ordinal entry is re-homed to another existing family

- GIVEN a later change moves the `Unmeasured claims` family heading past the ordinal entry
- WHEN the gate runs
- THEN the ordinal family-home assertion fails, naming the family the entry landed in
- AND the family equality, the membership pin, the body floor and the pattern floor all stay green, and the survivor-family assertion stays green too, because it is a separate test with its own killer

#### Scenario: the reference is trimmed back to its rule statements

- GIVEN a later change strips the falsifying examples out of the patterns
- WHEN the gate runs
- THEN the body floor fails, naming each pattern that fell under it
- AND a pattern renamed rather than removed fails the membership pin, instead of passing behind a count the floor still clears

#### Scenario: a survivor entry is re-homed to another existing family

- GIVEN a later change moves a family heading past one of the three survivor entries
- WHEN the gate runs
- THEN the family-home assertion fails, naming the entry that left `Mutation discipline`
- AND the family equality, the membership pin and the pattern floor all stay green, because the set, the order and the count did not move

### Two rules are enforced by hooks rather than by prose

`scripts/verify.sh` writes a **gate marker** on green: a file named after the git **tree object** of the working tree it verified, at `<git-common-dir>/harness/gate/<tree-oid>.json`. `scripts/gate_marker.py` is its only writer, and the whole decision predicate is `exists(path)` plus its mtime — no reader parses the body, because anyone who can write the file can write valid JSON, so parsing would buy nothing.

Two Claude Code hooks read that one artifact from opposite sides of one equality. `hooks/gate-evidence-guard.js` (`Stop`) blocks the end of a turn whose message claims the work is finished when no fresh marker covers the worktree's current tree. `hooks/push-target-guard.js` (`PreToolUse: Bash`) denies a `git push` whose **target** is a protected branch unless a fresh marker covers the tree of the commit being pushed. `commands/build.md` already makes those the same object — its ship step refuses to integrate unless `HEAD^{tree}` equals the tree the gate ran over — so one marker authorises both, and **no slash command is exempt**: `/ship`, `/routine` and `/promote` are authorised because they push a gated tree, which is the only authorisation a hook can actually check. `/assess` and `/update-guidance` were the two sanctioned flows that pushed without one, and each gained a gate-before-push sentence rather than an exemption.

The tree is computed against a **temporary index** in both the writer and the Stop hook, so measuring never stages the session's work; `git add -A` honours `.gitignore`, so the gate's own log and the venv are excluded exactly as they are excluded from a commit. The marker lives in the git common directory rather than the working tree: a marker inside the tree would be swept up by the very `git add -A` that computes the tree, moving the oid away from the one just recorded — a silent, permanent fail-closed wedge in any consuming repo that skipped a `.gitignore` line. The git directory cannot be tracked by construction, is shared by every linked worktree, and needs no install step anywhere.

Prose is the Stop hook's **trigger** and never its **evidence**. The completion-claim pattern set is a narrowing filter whose only failure direction is a false negative, and the trigger text is the payload's top-level `last_assistant_message` — not the transcript, which at Stop time does not yet contain the turn being stopped. That was measured live rather than modelled: an early build read the transcript, passed every unit test, and could not fire in production even once. The transcript read survives as a fallback for a host that sends no such field.

The push guard reuses `hooks/git-push-guard.js`'s hardened lexer rather than growing a second one, `require`d lazily inside the fail-open path. The two guards decide on different predicates — that one on a push's *form*, this one on its *target* — and only pure parsing functions cross between them, so the force guard's verdicts are unchanged.

Four evasions of the target predicate were found at review, each a path where the guard approved what it exists to refuse, and all four were fixed in the same change. A bare `git push` resolved its target through `rev-parse --abbrev-ref @{upstream}`, whose `origin/dev` no branch-name reduction can safely shorten — `feature/x` must not become `x` — so the commonest spelling of a push was compared against the protected set as the string `origin/dev` and always passed; it now resolves `--symbolic-full-name`. A relative `git -C .` was resolved against the hook process's own working directory instead of the directory the command runs in, so a marker belonging to an entirely different repository could authorise the push; a relative operand now composes with the `cd` the way git composes it, and stays unknowable — hence denied — when the `cd` is. A shell **parameter** expansion in the target slot (`HEAD:$T`) read statically as a branch nobody protects while the shell handed git whatever the variable held; an expansion is now as unreadable as a command substitution. And `--mirror` was decided on whether a protected branch existed locally, which is that flag's polarity inverted: `--mirror` makes the remote match this clone, so a protected branch the clone does *not* hold is one `--mirror` **deletes**. `--mirror` is refused outright; `--all` keeps the local-branch condition, because it moves only the branches this repo has.

#### Scenario: one more file is edited after a green gate

- GIVEN a task branch whose current tree a gate marker covers
- WHEN a file is edited and the turn's message claims the work is finished
- THEN the Stop hook blocks, naming the tree and the marker path it looked for
- AND the block clears only by running the repo's verify command over the new tree, because a marker from before the edit is not evidence about it

#### Scenario: a push to the integration branch carries no gate evidence

- GIVEN a worktree whose commit no fresh marker covers
- WHEN a push to a protected branch is issued in any spelling — an explicit refspec, a bare `git push` riding its upstream, a nested `sh -c`, or one behind a `cd` or a `git -C`
- THEN the hook denies before git runs, and names the tree it wanted evidence about
- AND a push to an unprotected branch is unaffected, with no marker present at all

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
- `commands/build.md` → *Visual evidence for a user-facing change* is the one home for the capture convention — trigger, location, slice rule, height ceiling, and capture cap. `commands/review.md` → *Run the reviewer* owns the handoff of that directory; `skills/review-discipline/SKILL.md` → *Reviewer obligations* → `Report:` owns the consulted / not-consulted line and its closed three-reason set. `commands/start.md`, `agents/reviewer.md`, and `commands/review.md` step 5 are renderings that point rather than restate.
- `skills/review-discipline/references/craft.md` is the one home for the defect classes that read as green. `skills/review-discipline/SKILL.md` Stage 2 and `commands/build.md`'s implementation and review briefs are the triggers that load it; none of the three restates a pattern.
- `scripts/gate_marker.py` is the one writer of the gate marker and the reference implementation of its path, tree and freshness rules; `scripts/verify.sh` invokes it last, so `set -e` is what makes "on green" mean it. `hooks/gate-evidence-guard.js` and `hooks/push-target-guard.js` are the two readers, and `tests/unit/test_gate_marker_contract.py` pins all three by executing them rather than by comparing restated constants.
- `process/harness.md` → *Enforcement hooks* is the one home for what the hooks refuse and what clears a refusal. `BOOTSTRAP.md`'s verification checklist calls out the `Stop` block specifically, because a settings file merged by hand from an older install can drop a new event type, and a hook that never fires looks exactly like one that always allows.
- `agents/reviewer.md` and `agents/steward.md` define role boundaries and route domain method to skills and commands.

## Known limitations

- UTF-8 `bytes / 4` is a stable context-budget heuristic, not an exact tokenizer count.
- Conditional guidance supports a hot root plus one reference level. A workflow that needs a deeper conditional tree must first change the topology contract and its guard.
- The assurance rubric is advisory prose an agent follows, so it is a quality control rather than a security boundary. The one enforcing boundary left is the repo's own `assurance.trivial_certify` command — a repo-supplied script, kept by ADR 0015 — whose allowlist fails closed and upgrades anything it cannot certify to `simple`; an applied label records that a choice was made, never that the choice was right.
- The guards over the rubric read prose, so they are bounded by sentence segmentation and by how tightly each polarity token is anchored to the verb it governs. They catch a rule deleted, negated, or excepted; a permission whose negation sits one or two words before the inference verb, and an uncertainty routed to a level the choice verb does not immediately name, are outside their reach.
- The guards over `/build`'s stage obligations read polarity per occurrence, anchoring each negation to the verb it governs across a gap of at most two words that may contain no blocking verb. Measured escapes, recorded at their size rather than papered over: an **outer negation over a well-formed inner prohibition** (*"There is no rule that a mismatch must not be integrated"*, *"A thin design is not a reason the run cannot proceed"*) is spelled correctly in its inner clause and grants in its matrix clause, which no token-window anchor reaches; closing it needs clause structure, and a double-negation heuristic is not available because the rules' own sentences carry two and three negation tokens. A design-stage exception worded with `implement` rather than a continuation verb is likewise uncovered, because widening the continuation vocabulary would make the rule's own sentence an offender.
- The derived `## Assurance` table check reads *is there an un-negated unit naming this obligation*, so a **release clause appended to a row cell** — *"The reviewer sub-agent is optional"* — leaves the derived stages unchanged while the prose releases the obligation. The direction is deliberate: the `trivial` cell states both obligation nouns under a `never`, and an obligation appended with the `never` intact is the drift that must fail. The release direction is not covered.
- The `## 3. Ship` inversion sweeps recognise an enumerated release and mismatch vocabulary, unlike the design sweep, which flags any continuation verb no negation governs and so fails closed. An appended grant outside that vocabulary (*"the `certified_tree` check is a formality"*, *"integration proceeds even when the trees differ"*) escapes, and the permissive as-built-record sweep requires the literal noun `as-built record`, so a grant spelled *"record what shipped"* escapes too. Deleting or replacing a rule is caught in every case; appending a contradiction in fresh vocabulary is not.

- The visual-evidence inversion sweeps are **blacklists of release vocabulary**, so like every sweep here they fail open on a grant worded outside that vocabulary. Measured at review, one wording at a time against the real documents rather than assumed: the full-page sweep caught six of ten independently written permissions and missed *"one image of the entire page is preferable to slices"*, *"a short page may be captured whole"*, and *"prefer a single full-page image where the surface fits"* — all three release in an adjective or a comparative rather than a verb the release arm names. The report-line sweep is the weaker of the two and caught **none** of six (*"at the reviewer's judgment"*, *"recommended but not mandatory"*, *"where it adds value"*, *"skip … for a docs-only diff"*, *"encouraged"*, *"nothing requires …"*). The paraphrase tuples that guard both sweeps are drawn from the same vocabulary the sweeps recognise, so they measure coverage of themselves rather than robustness; they are a floor against a single-wording check, not evidence of paraphrase completeness. Widening the alternation was considered and declined at review: a blacklist has no completion condition, and each widening risks flagging the rule it protects. The presence halves, which are value-asserted, are what actually hold a deleted or re-worded rule.
- The craft reference's body floor measures **length**, not the presence of a falsifying example. A long entry with nothing concrete in it passes. No tree-readable predicate separates an example from a restatement, and a keyword sweep for one would be the fail-open blacklist the reference itself warns about; the floor catches the degradation a distillation actually suffers, an entry trimmed back to its rule. Whether each entry carries a real example stays a review judgment over prose, and one entry was rewritten at review for exactly that reason.
- Both roots naming the reference is asserted as *the path appears somewhere in the file*, so `commands/build.md`'s second cite has no exclusive killer: deleting one of its two briefs survives every guard. Measured and left deliberately — a count would be the cardinality floor the reference itself warns against, and it would rot the first time a third brief is added.
- The repo-id sweep over distributed prose keys on the `PREFIX-1234` ticket shape parsed from `hooks/guidance-freshness.js`, so a GitHub-style `#1234` id in registered prose is not caught. The craft reference is clean of both shapes by measurement, not because the guard covers the second one.
- Nothing authenticates that a capture depicts the reviewed SHA, and `consulted` records only that the reviewer looked. The guidance states the capture convention; it adds no refusal for a user-facing change whose builder produced nothing, so a missing capture set is a Stage-1 finding a reviewer makes rather than a mechanism.
- The Stop hook can force **exactly one** extra turn per stop-chain, because it honours the platform's `stop_hook_active` flag. It is a nudge with a memory, not a lock: a hook that re-blocked unconditionally would wedge a session whose gate is genuinely red and which cannot fix it.
- The completion-claim trigger is a small pattern set over model prose, so a claim worded outside it escapes the nudge. The direction is deliberate — a false negative costs the nudge, a false positive costs a gate run on every ordinary turn — and it is tolerable only because the irreversible half is guarded on the command rather than on the words.
- A Claude Code session's working directory is fixed at launch, so a `/build` driven from the repo root sees a clean integration branch and the Stop hook never fires, however ungated the worktree its sub-agents are editing. Accepted for v1; the push guard covers the irreversible half. Filed as #439, which carries the two closures this design rejected and why — enumerating `git worktree list` would let one stale worktree from a finished ticket block every future session in the repo, permanently.
- The Stop hook asks whether there is anything to claim by comparing the current tree against `HEAD^{tree}` and, for committed work, `HEAD` against the branch `CONTEXT.md` names as `integration`. A repo declaring no `branches:` block gets only the first comparison, so a clean task branch carrying committed but ungated work is not blocked there. The push guard is unaffected: its fallback protected set needs no declaration.
- Both hooks read a file any process with repository write access can create, and both run in the same trust domain as the agent they check. A model with `Bash` can forge a marker, delete a real one, or edit the hook. They are evidence plumbing, not an authority: what they buy is that the default path now requires the gate to have actually run over the exact bytes, and that manufacturing the evidence is a discrete, transcript-visible act instead of a silent omission. The controls of record remain server-side branch protection and the gate output in CI. `permissions.deny` globs back the force-push guard; nothing in that block covers a push to `dev` by target, so a fail-open in the target guard has nothing behind it.
- Every hook payload and transcript fixture in the suite is a **hand-authored model of the host's contract**, and the suite is self-consistent with that model whether or not the model is right. Two things are now observed rather than assumed: the Stop payload, captured verbatim from Claude Code 2.1.220 and driven through the hook as-is, and the deny-over-allow precedence the push guard rests on, watched live refusing a command a standing `permissions.allow` entry covered. Everything else — the `PreToolUse` payload's own shape included — remains a model, and a live run is the only validation available for it.

## Decisions

### Decision: The gate marker is the authorisation, and it lives in the git directory

*Decided 2026-08-16 (#436), implementing ADR 0015's* Enforcement moves to hooks *and amending that bullet in place.*

**Context.** ADR 0015 moved enforcement into hooks and said the Stop hook blocks a "done" claim "unless the gate ran green **this session**". No session identifier reaches `scripts/verify.sh`, and none is documented in a Bash-tool environment, so that sentence was unenforceable as written. The push half carried the harder question: `settings/harness.json` explicitly authorises `git push origin dev`, because `/ship` and `/routine` push there as the normal path — so "refuse pushes to the integration branch" cannot mean a blanket refusal, and a hook cannot see which slash command is driving.

**Decision.** One artifact answers both. The gate writes a marker named after the git **tree object** it verified, in the git common directory, and a fresh marker covering a tree **is** the authorisation — for a completion claim about that tree and for a push carrying it. There is no command-based exemption, because none is needed: every authorised push path already pushes a tree the gate covered, and an exemption a hook cannot verify is not a control.

**Alternatives.**

- *Session scope, as the ADR worded it* — unenforceable, and weaker even where it is available: a session that edits three files after its green run still satisfies it.
- *A marker under `.harness/`* — gitignored in this repo only. In a consuming repo without that rule the marker is swept into the tree it records, so the recorded oid can never match again: a silent, permanent fail-closed wedge in exactly the repos that skipped an install step.
- *A command-authorisation token* — a hook cannot authenticate the command that set it, so it authorises whoever writes it, which is the agent.
- *A second shell parser for the target guard* — `sh -c "git push origin HEAD:dev"` is a push the force guard's lexer already sees; a naive parser would refuse the plain spelling and wave the nested one through, which is an invitation rather than a gap.
- *`ask` instead of `deny`* — whether a hook's `ask` overrides an existing `permissions.allow` entry is not documented well enough to bet enforcement on, and an unattended run needs a deterministic answer. Deny-over-allow is what the force guard already relies on, and it was observed live here.
- *A purely state-based Stop trigger* — blocks every ordinary conversational turn in a task worktree, and blocks the TDD **RED** phase, where the correct report is that a test fails and the demanded gate cannot go green.
- *A path-based exemption for `/assess`* — needs the remote tip, so network calls inside a hook, and bakes repo-specific path policy into a universal one.

**Consequences.** Fail-open is three states rather than one. A hook that **could not run** opens loudly on stderr, both hooks, per #303. A hook that **ran but could not establish the facts** splits on recoverability: the push guard denies, because one gate run clears a false deny while the act it guards is irreversible; the Stop hook allows, because a Stop hook blocking on an unreadable git wedges a session with no exit. A hook that **established the facts and found no evidence** is not failing open at all — that is the decision it exists to make. The marker directory is a bounded cache, pruned by age and count; ADR 0015 retired the run ledger and this does not revive it. The contract is duplicated in three languages and therefore pinned by *execution* rather than by inspection — the path in all three, the tree in two, the freshness bound in three — because a shared `hooks/lib/` module would be invisible to three `hooks/*.js` scanners that walk the directory non-recursively, and its own load failure would disarm both enforcement hooks at once.

### Decision: The capture convention lands in `/build`, not in `ux-design`

*Decided 2026-08-15 (#434), reversing `specs/proposals/visual-evidence-for-review.md`.*

**Context.** The proposal's change 2 of 2 (#362) placed the build-loop rendering guidance in the implement step of both build paths **and** in the `ux-design` skill, on the reasoning that `ux-design` is not gated on the `design_system` layer and so applies wherever there is a surface. ADR 0015 has since retired the second of those paths, leaving one agent-led `/build`.

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

- [../architecture-principles.md](../architecture-principles.md)
- [../decisions/0015-harness-v4-thin-verification-layer.md](../decisions/0015-harness-v4-thin-verification-layer.md)
