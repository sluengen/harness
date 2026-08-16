---
feature: guidance-system
status: implemented
last_updated: 2026-08-16
tickets: ["#401", "#407", "#354", "#288", "#434", "#435", "#436", "#437", "#438", "#439", "#444", "#445"]
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

`skills/review-discipline/references/craft.md` is the conditional reference `review-discipline` links alongside the diff-shape checklist. It carries forty-five named patterns in six families — vacuity, prose predicates and text guards, deletion/retirement/re-homing, mutation discipline, the ticket and its criteria, and unmeasured claims. Each entry is a name, the rule in one line, and the falsifying example where a fully green suite shipped the defect; the example is the load-bearing half, and the file says so.

Mutation discipline covers a surviving mutation from both sides. A survivor has four readings, and the inert one — the mutation changed nothing — voids the rest, so an *inert* survivor is unproven rather than evidence of a weak guard, and the entry that says so is pointed at from the ambiguity entry by name. Where the subject is prose there is no observable to declare, so liveness is built into the experiment instead: a **paired splice** puts a form the predicate is known to catch and the form under test at the same location in the same file, and the known form must die first. Both are stated tool-agnostically, so they carry into a repo with no mutation instrument of its own.

Four diff shapes are the activation trigger both roots state — a guard, a prose predicate, a mutation table, a deletion pass. `skills/review-discipline/SKILL.md` Stage 2 states it for the reviewer, and `commands/build.md` states it twice, at the implementation brief (read it before writing the test) and at the review brief. *The ticket and its criteria* and *Unmeasured claims* are not gated on those shapes, and the file's preamble now names them rather than locating them: a ticket's grounding and a claim nothing measures are read at different moments in the loop.

The file is distilled rather than transplanted. It states every pattern generally and carries no provenance — no ticket ids, no cites to app-only paths, no nesting of its sibling reference — and those three constraints are already-live sweeps that pick it up as a registered prose member rather than new machinery. It restates nothing its core owns: the finding 2×2, final-evidence ordering, criteria currency, the diff-shape structural checks, and `code-quality`'s fresh-evidence rule stay where they are, and the preamble names each of those homes.

Its guard derives the family and pattern sets from the file rather than listing them. The family set is pinned as an **equality**, so an unrecorded new family is as loud as a lost one; seventeen named patterns are pinned by **membership**, so a rename surfaces as a missing name instead of shrinking a set behind a count that still passes; and two floors sit just under their measured values — forty-five patterns and a 357-character shortest body. The non-vacuity assertion is a test of its own rather than a line inside the body sweep, because that sweep iterates the derived pattern set and would pass over an empty one.

Nine assertions pair those derivations rather than extending either. Four are links on an exact heading, so a pointer fails loudly on a rename instead of dangling: *A survivor is ambiguous* must name *An inert mutation reports a survivor it never earned*, *A paired delimiter can be counterfeited by prose that mentions it* must name *The text unit is part of the predicate*, and the two constant-predicate entries must name each other in **both** directions. Four are family homes: the three survivor entries under `Mutation discipline`, the ordinal entry under `Unmeasured claims`, the counterfeited-delimiter entry under `Prose predicates and text guards`, and the frame-mismatch entry under `Vacuity`. The ninth is adjacency, and it is the only assertion here that reads two patterns' relation to each other rather than to a family: the frame-mismatch entry must be the entry immediately after the constant-true entry, pinned by that entry's **name** rather than by a position. The family set and the pattern set are each derived alone and neither knows a heading's *home*, so a pattern migrating between existing families leaves the set, the order, the count and every required name unchanged. Only the entries whose family was argued on their ticket are pinned to a home — the three survivor entries, the ordinal entry, the counterfeited-delimiter entry, and the frame-mismatch entry; a hand-written family for all forty-odd would be a second copy of the file's structure. Each family assertion is a separate test, so each has its own killer. No link reads the two entries it joins for agreement, and the guard's own docstring records that a link to an entry that contradicts it passes.

*Unmeasured claims* also carries the structural edit the file had been missing. *A control goes inert when the change deletes what it names* covers deletion and *A deletion pass that moves a definition must move its killer* covers relocation; *An ordinal reference into an enumeration is invalidated by a correct insertion* covers insertion, where the edit, the text it edits, and the sentence it breaks are each correct alone and the defect exists only between them. Its rule is that a reference names its referent, never its index. It sits beside *A forward reference becomes a lie the day its dependency ships* on the boundary that a forward reference was never true, while an ordinal reference was true until a later correct edit invalidated it.

Adding it applied it. A sweep of the file for references identifying a member of an enumeration by position found five: the preamble locating two families as "the last two", "satisfies the first shape", "the second assertion", and "the first reading … the other three" in the ambiguity entry were rewritten to name their referents; "the twin of the false-kill entry below" was kept, because it names its referent and `below` is only a locator. The same class had already gone stale in this record — it described the craft reference as "the third conditional reference" when four exist, an error that shipped with the reference itself and survived one later change to the same paragraph. That is fixed here.

What none of this proves, measured rather than assumed. No guard reads ordinals, and the ticket declined to add one: any predicate that could catch the class is a pinned count, which the file's own *Floors decay into decoration* says rots on the next insertion. The class is caught by a reader, and the entry exists to make the reader look. Nor is *this* entry pinned to a position within its family — its ticket settled the family and said nothing about a neighbour, so a neighbour pin would guard a decision nobody made. (A later pair whose ticket *did* ask for adjacency is pinned, by name; that is recorded below.) The pattern floor is slack by design and was measured at that slack: removing two entries takes the file from forty-five to forty-three and stays green, so the floor catches a family-sized loss and not an entry-sized one. The preamble's naming of the two ungated families is unguarded prose — measured by a paired splice, where a short-bodied heading spliced into the same block died on the body floor while rewriting the preamble to name the wrong two families changed nothing red. And the two entries cross-reference each other by different means: *A survivor is ambiguous* names *An inert mutation reports a survivor it never earned* by exact heading, which is pinned and was confirmed still load-bearing after the sweep rewrote the sentence carrying it, while the inert entry points back with a description rather than a heading, which nothing checks.

*Prose predicates and text guards* now carries the counterfeit case its text-unit entry does not cover. *The text unit is part of the predicate* is a splitter reading **too much** as one unit, remedied by choosing the unit and pinning it; *A paired delimiter can be counterfeited by prose that mentions it* is the corpus silently **shrinking before any unit is chosen** — a guard that strips or scopes the region between paired delimiters opens one on a *mention* of the delimiter in ordinary prose, so the swept text simply gets shorter and the sweep reports zero offenders over text it never opened. Its falsifying example is the three-splice measurement that surfaced it: a shape the predicate was known to catch died at one offset, the shape under test survived at that same offset, and the same shape died earlier in the same file, leaving one reading — the region between the two deaths was invisible. The remedy is to anchor the opener to line start with indent tolerance, and the entry keeps the language constraint that Python's `re` needs each lookbehind branch fixed-width. It generalises past code fences to every paired delimiter a text guard strips or scopes, and names documentation *about* a syntax as the structurally most exposed corpus, because prose there reliably carries that syntax's delimiters as its subject matter. The alternative home — folded into the text-unit entry as a cross-referenced paragraph — was rejected on the ground that the mechanisms differ and so do the remedies, and the remedy is the half a reviewer acts on. The two entries are neighbours rather than parent and instance, and the entry says that a guard can carry both defects at once and that each remedy leaves the other standing.

*Vacuity* now names both directions an assertion becomes constant, which is the deadliest direction of all — an assertion that passes for every input. *`all()` over a possibly-empty iterable is constant-true* is constancy from an **empty subject**, remedied by asserting the subject is non-empty. *A comparison whose operands live in different frames is constant* is constancy from an **operand-frame mismatch**, remedied by resolving both operands to a common frame before comparing. Its falsifying example is a measurement rather than an illustration: a floor written to prove a fixture's symlink pointed *outside* a repository asserted `not link.readlink().is_relative_to(link.parent)`, but `readlink()` returns the target as written and a relative path is never `is_relative_to` an absolute one, so the assertion held for every relative target however far inside it pointed — and a fixture mutated to link at a relative in-repo path survived the entire suite, including the floor whose sole job was to catch that. Comparing the resolved operands makes that mutation the assertion's exclusive killer, and the entry carries that proof shape. The class is stated as the shape rather than as the API pair, with naive-versus-aware datetimes and raw-versus-normalised strings named in one sentence and given no example of their own.

Two competing readings were argued and rejected on the ticket, and the reasons are recorded here so neither is re-proposed. Folding the class into the constant-true entry fails for the reason the counterfeited-delimiter fold failed: the mechanism differs, the remedy differs, and the remedy is the half a reviewer acts on — asserting non-emptiness does nothing for a frame mismatch. Reading it as an instance of *A green mutation table certifies only what its author thought to mutate* fails because that entry names why such a defect is **missed** while this one names what the defect **is**; being missed by a table is true of every entry in the file, so it decides nothing.

The pair is cross-referenced in **both** directions, each sentence naming the other's exact heading and each direction pinned by its own test. That is a deliberate departure from the precedent two paragraphs above, where the survivor pair's forward link is a heading and its back-pointer is a description nothing checks. A cross-reference asked for in both directions is two links, not a link and a gesture; the cost is one more test function, and what it buys is that deleting either sentence goes red on its own assertion rather than on one a surviving half keeps green. Both directions were measured to have exclusive killers.

Adjacency is pinned too, and it was not until review. The change spec asked for the entry in the constant-true entry's family **and adjacent to it**, and the family grouping only derives the first half. Measured at review by an interposed entry: a synthetic pattern spliced between the two left the family set, the membership tuple, both links, both floors and every family pin green while the pair stopped being neighbours, so each entry's `above`/`below` locator for the other went stale with nothing red — the shape the file's own *An ordinal reference into an enumeration is invalidated by a correct insertion* names. The assertion added in response pins the neighbour by **name**, which the ordinal entry's own rule permits: a name-pinned neighbour goes red only on an insertion between the two, which is the event it detects, where a pinned index would rot on any insertion above it. The same pin was declined for the ordinal entry, and that remains right — there the ticket said nothing about a neighbour, so a pin would have guarded a decision nobody made. Order is part of the claim, because one entry says *below* and the other says *above*, so a swap leaves two sentences naming the right heading and pointing the wrong way.

The header now states the file's own admission rule: additions are held for an operator call — the `input` hold label, assigned — never self-filed. The bar the file sets, *a defect class that reads as green*, is a standing incentive for any agent to grow the file, and every entry taxes the context of every future reader; the operator is the budget-holder for that tax. Its guard reads the **header** — the prose above the first family heading — rather than the file, because the rule governs whether to add an entry at all and so has to reach a reader before they are inside a family reading entries. It narrows twice: to the one header paragraph naming `self-filed`, then to the one sentence of that paragraph which does. The paragraph alone was not narrow enough, measured at review by an independent mutation: the paragraph's closing sentence names the operator again for an unrelated reason, so a rule rewritten to hold additions for somebody else left the paragraph-scoped assertion green. The sentence unit is what makes the terms co-occur *in the rule*, and its own control is the same substitution made in the paragraph's other sentence, which survives. Nothing in the tree can prove the rule was *obeyed* — that is a property of how a change was filed — and the guard's docstring says so.

#### Scenario: the counterfeited-delimiter entry is folded back into its neighbour

- GIVEN a later change deletes the entry and moves its material into *The text unit is part of the predicate*
- WHEN the gate runs
- THEN the membership pin, the delimiter link and the delimiter family-home assertion all fail, each naming the entry
- AND the pattern floor stays green, because forty-four still clears a floor of forty-three — the floor catches a family-sized loss, not an entry-sized one

#### Scenario: the admission rule is rewritten to hold additions for someone else

- GIVEN a later change replaces the operator in the admission sentence with another actor
- WHEN the gate runs
- THEN the header assertion fails, naming the term the rule no longer carries
- AND the same substitution made in the paragraph's closing sentence leaves it green, because the assertion reads the rule's sentence rather than its paragraph

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

#### Scenario: the back half of the constant-predicate cross-reference is degraded to a description

- GIVEN a later change rewrites *`all()` over a possibly-empty iterable is constant-true*'s sibling sentence to describe its neighbour rather than name it
- WHEN the gate runs
- THEN the back-link assertion fails on its own, naming the heading the entry no longer carries
- AND the forward link, the membership pin, the family home, the adjacency pin and both floors stay green, because a pair asked for in both directions has a separate killer per direction

#### Scenario: an entry is inserted between the constant-predicate pair

- GIVEN a later change adds a pattern between the two constant-predicate entries, correctly named, correctly familied, and long enough to clear the body floor
- WHEN the gate runs
- THEN the adjacency assertion fails, naming the entry that now follows the constant-true entry
- AND every other assertion in the module stays green, and the pattern floor rises rather than falls — which is why adjacency needed an assertion of its own rather than a reading of the family grouping

### `/ship`'s base-drift rule names the monotonic-field collision

`commands/ship.md` § *2. Integrate* holds the base-drift rule: the base moving ahead is normal concurrency, so the reconciliation pulls, merges, re-gates and re-binds the review rather than halting. It now also names the trap inside that reconciliation. A monotonic field both sides advanced independently — a version number, a migration ordinal, a sequence id — converges on identical text, so the merge raises no conflict marker and the merged tree is a third state shipping under a value each side already claimed. Identical text is not agreement, so a same-valued monotonic field is a collision to detect rather than an agreement to accept, and the reconciliation advances past both sides.

The craft reference was assessed as the home for this class and rejected, with the reason recorded so it is not re-proposed: it fails the audience test, not the reality test. That reference makes a reviewer of a *branch diff* look at what reads green, and this defect exists in no branch diff — only between two trees at merge time — so the actor who can catch it is whoever executes a reconciliation, and the rule belongs where that actor reads. Phrasing it generically settles the second objection for free: the rule names the field class, never a file that carries one in this repo.

Its guard is a module of its own, because nothing read that paragraph before — the only other module over `commands/ship.md` reads the `reviewed_sha` identity check in a different section. It derives the section, then the paragraph inside it, then the rule's own sentences, and each derivation has a test asserting it resolved, so a renamed heading fails by name instead of leaving every assertion below scanning an empty string. The sentence unit gets its own killer too: the split must cover the paragraph without dropping or duplicating text, and the selection must be strictly shorter than the paragraph, which is what separates *selected the rule* from *selected everything*. The rule is picked out by the term it is about, so the artifact sweep stays off the paragraph's pre-existing prose, which this change did not write.

Four assertions then read the rule, each with its own killer. Every occurrence of the rule's obligation phrases must fall inside that paragraph, so a second copy pasted elsewhere dies there and nowhere else — the containment half alone could not have an exclusive killer, since the rule is derived from the paragraph. The rule must state its obligation and not only the hazard. It must name the field class through several instances rather than one, pinned by membership so a fourth costs nothing to add. And it must name no artifact filename, backed by a control that splices two filename shapes into the **real rule text** and asserts the *difference* the splice makes rather than an absolute token set — both weaker forms were measured and both died to the same edit as the assertion they back, which is the shape where two assertions hide each other.

#### Scenario: the collision rule is quoted into a second section

- GIVEN a later change repeats the rule's obligation phrases under *Preconditions*
- WHEN the gate runs
- THEN the positional assertion fails, naming each phrase found outside the base-drift paragraph
- AND the obligation, field-class and artifact assertions stay green, because the rule is still in its paragraph

#### Scenario: the rule is illustrated with the file that surfaced the class

- GIVEN a later change names a source-repo version file inside the rule
- WHEN the gate runs
- THEN the artifact assertion fails, naming the token it found
- AND its control stays green, because the control measures the difference a splice makes rather than an absolute token set

### Two rules are enforced by hooks rather than by prose

`scripts/verify.sh` writes a **gate marker** on green: a file named after the git **tree object** of the working tree it verified, at `<git-common-dir>/harness/gate/<tree-oid>.json`. `scripts/gate_marker.py` is its only writer, and the whole decision predicate is `exists(path)` plus its mtime — no reader parses the body, because anyone who can write the file can write valid JSON, so parsing would buy nothing.

Two Claude Code hooks read that one artifact from opposite sides of one equality. `hooks/gate-evidence-guard.js` (`Stop`) blocks the end of a turn whose message claims the work is finished when no fresh marker covers the current tree of any worktree the session worked in. `hooks/push-target-guard.js` (`PreToolUse: Bash`) denies a `git push` whose **target** is a protected branch unless a fresh marker covers the tree of the commit being pushed. `commands/build.md` already makes those the same object — its ship step refuses to integrate unless `HEAD^{tree}` equals the tree the gate ran over — so one marker authorises both, and **no slash command is exempt**: `/ship`, `/routine` and `/promote` are authorised because they push a gated tree, which is the only authorisation a hook can actually check. `/assess` and `/update-guidance` were the two sanctioned flows that pushed without one, and each gained a gate-before-push sentence rather than an exemption.

The tree is computed against a **temporary index** in both the writer and the Stop hook, so measuring never stages the session's work; `git add -A` honours `.gitignore`, so the gate's own log and the venv are excluded exactly as they are excluded from a commit. The marker lives in the git common directory rather than the working tree: a marker inside the tree would be swept up by the very `git add -A` that computes the tree, moving the oid away from the one just recorded — a silent, permanent fail-closed wedge in any consuming repo that skipped a `.gitignore` line. The git directory cannot be tracked by construction, is shared by every linked worktree, and needs no install step anywhere.

Prose is the Stop hook's **trigger** and never its **evidence**. The completion-claim pattern set is a narrowing filter whose only failure direction is a false negative, and the trigger text is the payload's top-level `last_assistant_message` — not the transcript, which at Stop time does not yet contain the turn being stopped. That was measured live rather than modelled: an early build read the transcript, passed every unit test, and could not fire in production even once. The transcript read survives as a fallback for a host that sends no such field.

**Which directories the Stop hook asks about** is a second question, answered separately (#439). The hook evaluates the payload's `cwd` first and by the rules above, unchanged; only if that yields no verdict does it derive further candidates, so an ordinary turn never reads the transcript twice and a session inside its own build worktree behaves exactly as it did. A derived candidate must survive an intersection: the transcript's host-written **top-level `cwd`** own-property, taken per physical line through `JSON.parse` and only when it is a non-empty string, must resolve inside a worktree that `git worktree list --porcelain` reports for the anchor repository — the payload `cwd`'s repository, or `CLAUDE_PROJECT_DIR` when the session's shell has wandered out of a checkout. Mapping a directory to its worktree is **longest-prefix**, not first-match, because this repo nests its worktrees at `<root>/.worktrees/<id>` inside the root worktree's own path and a first match would send every one of them to the root, which is skipped as protected; that spelling would install the guard and leave it inert in its own default layout, with a green suite. Admission then drops a candidate that is bare, prunable, `detached` (the shape `scripts/verify.sh`'s own gate worktree takes), on a branch `CONTEXT.md` declares, already evaluated as the payload `cwd`, or already yielded. Candidates are ordered most-recently-visited first and bounded by two ceilings on work rather than a window on the file — 32 distinct `cwd` values read, 4 tree computations spent — because a tail-only window narrows silently as a session grows and a hook that quietly stopped firing looks exactly like one that allows.

The transcript is a **selector, never a source of paths**. Every string that reaches `spawnSync`, the tree computation, or the injected `reason` is one git printed; the transcript value is a set-membership key and is then discarded. That bounds the mechanism from both sides: it can only move the checked set within the closed set of this repository's own worktrees, between "none" — which is what shipped in #436 — and "all of them", which is the design #436 rejected as permanently annoying rather than as unsafe. Every new path fails open, so the only new refusal is that some worktree in the intersection holds work no fresh marker covers.

The push guard reuses `hooks/git-push-guard.js`'s hardened lexer rather than growing a second one, `require`d lazily inside the fail-open path. The two guards decide on different predicates — that one on a push's *form*, this one on its *target* — and only pure parsing functions cross between them, so the force guard's verdicts are unchanged.

Four evasions of the target predicate were found at review, each a path where the guard approved what it exists to refuse, and all four were fixed in the same change. A bare `git push` resolved its target through `rev-parse --abbrev-ref @{upstream}`, whose `origin/dev` no branch-name reduction can safely shorten — `feature/x` must not become `x` — so the commonest spelling of a push was compared against the protected set as the string `origin/dev` and always passed; it now resolves `--symbolic-full-name`. A relative `git -C .` was resolved against the hook process's own working directory instead of the directory the command runs in, so a marker belonging to an entirely different repository could authorise the push; a relative operand now composes with the `cd` the way git composes it, and stays unknowable — hence denied — when the `cd` is. A shell **parameter** expansion in the target slot (`HEAD:$T`) read statically as a branch nobody protects while the shell handed git whatever the variable held; an expansion is now as unreadable as a command substitution. And `--mirror` was decided on whether a protected branch existed locally, which is that flag's polarity inverted: `--mirror` makes the remote match this clone, so a protected branch the clone does *not* hold is one `--mirror` **deletes**. `--mirror` is refused outright; `--all` keeps the local-branch condition, because it moves only the branches this repo has.

#### Scenario: one more file is edited after a green gate

- GIVEN a task branch whose current tree a gate marker covers
- WHEN a file is edited and the turn's message claims the work is finished
- THEN the Stop hook blocks, naming the tree and the marker path it looked for
- AND the block clears only by running the repo's verify command over the new tree, because a marker from before the edit is not evidence about it

#### Scenario: a build driven from the repo root leaves its worktree ungated

- GIVEN a session whose shell sits at the repo root, on the integration branch, clean and at the tip, and whose transcript records it having worked in `.worktrees/<id>`
- AND that worktree holds work no fresh marker covers
- WHEN the turn's message claims the work is finished
- THEN the Stop hook blocks, naming that worktree, its tree, and the marker path it looked for, and saying the directory is one the session worked in rather than the one it is in
- AND a worktree of the same repository the transcript never names is not checked, however ungated it is
- AND the block still comes at most once per stop-chain, so a second ungated worktree is not a second refusal

#### Scenario: a push to the integration branch carries no gate evidence

- GIVEN a worktree whose commit no fresh marker covers
- WHEN a push to a protected branch is issued in any spelling — an explicit refspec, a bare `git push` riding its upstream, a nested `sh -c`, or one behind a `cd` or a `git -C`
- THEN the hook denies before git runs, and names the tree it wanted evidence about
- AND a push to an unprotected branch is unaffected, with no marker present at all

### Roles and distribution

Reviewer and steward agent bodies contain role, authority, supplied inputs, output expectations, and skill routing. Review method, assessment lenses, and repo-runtime engine history stay in their owning skills, commands, specs, and decisions.

Every conditional reference is a normal versioned registry entry. The generator creates adapters only for top-level commands, and skill-directory exposure includes their reference directories. Generated agent TOML preserves the concise source role body.

### Registered prose names no repo facts

`hooks/guidance-freshness.js` owns the leak detector, and `tests/unit/test_distributed_prose_no_repo_ids.py` parses it out of the hook rather than restating it, so the hook's per-edit warning and the standing sweep over the committed tree cannot drift apart. Two shapes are recognised. `PREFIX-1234` is scanned over the whole file, less a small allowlist of standards that share its shape (`RFC`, `ADR`, `AC`). `#1234` — a GitHub issue reference — is scanned over the file with fenced code removed, and carries no allowlist, because `#` prefixes nothing that is a standard's name.

They are two constants rather than one alternation because only the `#` branch needs the fence strip: inside a fence `#` is live syntax and an all-digit hex colour is shaped exactly like an issue reference, while `CAL-42` is a repo fact in a code block as much as in a sentence. What keeps the `#` branch off ordinary punctuation is a pair of boundaries — a word character or `&` before, a word character or hyphen after — which is what excludes a hex colour, a heading anchor and an HTML entity; each excluded character has its own control, and the hex colour is asserted both synthetically and against the real shipped line, because the real one sits inside a fence and would otherwise be excluded by the strip rather than by the boundary under test.

A fence delimiter counts only at the start of a line, indent allowed. Prose that *mentions* a fence mid-sentence would otherwise open one and the strip would swallow every line up to the next real fence — the failure is silent, since the swept text merely gets shorter and the sweep reports no offenders over prose it never read. Both patterns use explicit character classes rather than `\w`/`\d` so the JS engine and the Python `re` that reuses the body agree character for character; `g` is the only flag permitted, because a flag changes what a pattern means and is the one part of the literal that does not cross over.

#### Scenario: a GitHub issue id reaches a registered prose file

- GIVEN a registered universal prose file gains a bare `#1234` outside a fenced block
- WHEN the gate runs
- THEN the standing sweep fails, naming the file and the id
- AND the hook warns on the edit that introduced it, through its own matcher rather than the guard's

### Distributed source answers to a size ceiling

`tests/unit/test_source_file_size_justification.py` enforces `code-quality` Part C over the tracked tree: a file past its tree's ceiling carries a `size: <reason>` comment or the guard fails. Two sets decide what it looks at, and since #444 both are derived rather than listed. The **trees** are the top-level directories git tracks a source file under. The **languages** are every suffix git tracks, each classified as source — mapped to the line-comment prefix its marker takes, `#` for `.py` and `.sh`, `//` for `.js` — or as non-source. An unclassified suffix fails; classifying a new one as source then forces its tree into the ceiling table. Two separate reds, neither of them silent.

The tree derivation used to run over `git ls-files "*.py"`, so the check written to prove no tree is a blind spot could not report a tree holding no Python. `hooks/` was that tree. It answers to the 500-line hard limit like `scripts/` and `templates/` — a hook is ordinary logic, not the case enumeration Part B's raised ceiling exists for — and the three hooks past that limit record a `// size:` decision naming what keeps each one whole: #436 declined a shared `hooks/lib/`, so `node <path>` must resolve a hook with no module beside it.

A file with no suffix is classified per file by shebang against the file itself rather than exempted, because `bin/harness` was such a script until #435. That branch answers `#`, the comment every extensionless script this repo has tracked would take; a `node` shebang would be asked for a marker it cannot write and reported, never skipped. `git ls-files` lists symlinks and the 21 tracked ones resolve to directories, so the shebang read asks `is_file` first.

The reason must sit on the marker's own line, and that bound is load-bearing rather than tidy. The pattern runs over the whole file, so a whitespace class crossing the newline lets the following line's first character stand in for the reason — which every real file supplies, making an empty `# size:` unfailable everywhere except in a single-line sample. Found at review by mutating a shipped hook's marker down to a bare `// size:` and watching the guard stay green over 723 lines; fixed in branch, with whole-file controls in both languages.

#### Scenario: a tracked tree holds no Python

- GIVEN a top-level directory git tracks a source file under in a language other than Python
- WHEN the gate runs
- THEN the tree derivation reports that directory, and the blind-spot check fails until it has a ceiling
- AND a file past that ceiling fails until it records a `size:` decision in its own comment syntax

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
- `tests/unit/test_source_file_size_justification.py` is the one home for the repo's size-ceiling enforcement — the tree set, the language classification, and the marker's per-language form — and its classifier is a single function every synthetic control and both derivations route through. `templates/size-guard.md` is a separate artifact: the reference walker shipped to consuming repos, carrying its own globs/limit/exemption contract for an adopting repo to edit, derived from nothing here.

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
- The repo-id sweep now covers the GitHub `#1234` shape as well as `PREFIX-1234`, and the two live leaks it found were rewritten. What it still does not decide is *meaning*: `#` followed by digits is treated as an issue reference wherever it appears in unfenced prose, so an ordinary English "step #1" and an all-digit hex colour outside a fence both read as leaks. Both have a cheap workaround — reword, or fence the sample — and the alternative, a numeric floor or a keyword whitelist, would be the fail-open blacklist the craft reference warns against.
- The craft reference's prose is swept for repo *ticket ids* and for *app-only path cites*, and for repo facts in no other form. Re-measured at review by a paired splice into the frame-mismatch entry at one location: a bare GitHub-shaped id inserted there dies on the repo-id sweep, and a path under `scripts/ specs/ tests/` inserted at that same location dies on the app-cite sweep — so both sweeps demonstrably read the entry. That corrects the claim recorded when the counterfeited-delimiter entry shipped, which said a source-repo file path spliced into this file survives every guard. It survives only where the app-cite detector deliberately ignores it — a registered file, a consumer convention directory, a template placeholder — and not where it names an app-only path. What stays unmechanised is a repo fact named with no path in it at all, and that remains a reading judgment. `/ship`'s collision rule is the one place an artifact predicate is mechanised, and it reads only that rule.
- The adjacency pin reads the two constant-predicate entries' *order within their family*, never the words that depend on it. An entry that stops saying `above` or `below` still passes, and so does a pair that is adjacent for some other reason. Like the link assertions beside it, it makes a rename and an insertion loud; whether the two sentences still locate each other correctly is a reading judgment.
- That artifact predicate keys on a bounded extension list, which is a blacklist and has no completion condition. Its module says so, and the escape is wider than "a fact named without an extension": measured at review, a token carrying an extension the list does not hold — `index.html`, and likewise a `.css` or `.svg` token — is invisible to it. It catches the shape the assessment actually rejected, and its control proves it catches that shape rather than nothing; whether a sentence names a source-repo fact in plain words with no filename in it stays a reading judgment.
- The collision rule's sentences are selected out of the base-drift paragraph by the term the rule is about, so the selection is elastic under a reword. Measured: renaming that term in the sentence carrying the field-class list narrowed the selection to the other sentence, and only the field-class assertion went red — the obligation and artifact assertions were then reading one sentence where they had read two, with nothing to say so. The direction is toward scanning less rather than more, and the paragraph's pre-existing prose carries no artifact token today, so nothing is currently hidden behind it. The strict-shortness assertion bounds the opposite direction, and only at the whole paragraph.
- Fenced code is exempt from the `#` branch by design, so an issue id written inside a code block is not caught. That is the deliberate price of not flagging every hex value and shell comment in the corpus; the `PREFIX-1234` branch has no such exemption and still scans fences.
- The two engines are pinned to agree by explicit character classes and a `g`-only flag rule, and were measured identical over sixty adversarial inputs. One pre-existing divergence remains on the untouched `PREFIX-1234` branch: JS `\b` is ASCII-only where Python's is Unicode-aware, so an id abutting a non-ASCII letter (`ÉCAL-42`) warns in the hook and not in the sweep.
- Nothing authenticates that a capture depicts the reviewed SHA, and `consulted` records only that the reviewer looked. The guidance states the capture convention; it adds no refusal for a user-facing change whose builder produced nothing, so a missing capture set is a Stage-1 finding a reviewer makes rather than a mechanism.
- The Stop hook can force **exactly one** extra turn per stop-chain, because it honours the platform's `stop_hook_active` flag. It is a nudge with a memory, not a lock: a hook that re-blocked unconditionally would wedge a session whose gate is genuinely red and which cannot fix it.
- The completion-claim trigger is a small pattern set over model prose, so a claim worded outside it escapes the nudge. The direction is deliberate — a false negative costs the nudge, a false positive costs a gate run on every ordinary turn — and it is tolerable only because the irreversible half is guarded on the command rather than on the words.
- The Stop hook's scope is the worktrees this session's transcript records it working in, intersected with `git worktree list` for the same repository (#439). What that closes is the shape it was filed for: a `/build` driven from the repo root, sitting clean on the integration branch, now blocks on the ungated worktree it drove. The entry this replaces said a session's working directory is fixed at launch; that was wrong, and the correct mechanism is what bounds the remaining gaps. The payload `cwd` tracks the **main** session's shell across Bash calls, so it moves; what never propagates back is a **sub-agent's** `cd`. So a worktree only ever entered from a sub-agent's shell is invisible to the payload `cwd` and reaches the hook only if the orchestrator itself also ran a Bash call there — and the sub-agent transcripts, reachable at `dirname(transcript_path)/<session_id>/subagents/agent-*.jsonl`, do not help, because every entry in one records the sub-agent's launch directory.
- What else remains, each direction stated at its size. A missing, rotated or compacted transcript yields no derived candidates and the hook degrades silently to checking the payload `cwd` alone, which is #436's behaviour and is indistinguishable from a hook with nothing to report. The scan is anchored on the repository of the payload `cwd`, falling back to `CLAUDE_PROJECT_DIR` only when that directory is not a checkout at all, so a session whose last Bash call left it inside an *unrelated* git repository gets that repository's worktrees and never its own. `stop_hook_active` still caps the chain at one block, so with two ungated worktrees the model is told about one. Neither ceiling is pinned from above by any test, and `MAX_DERIVED_CHECKED = 4` sits **at** rather than above the largest same-repo non-detached worktree set measured in a real session: re-reading eight of this repo's own transcripts at review found one session naming ten distinct directories, of which four were unambiguously task worktrees and a fifth was a directory whose detached status can no longer be recovered. So a turn that worked in five live worktrees may never reach the fifth; the ordering makes that the oldest-visited, which is the least likely to hold the current work. `MAX_DISTINCT_CWDS = 32` has real headroom against the same measurement's maximum of ten. The value 4 is a policy choice rather than a measured bound, and no test pins it — lowering it to 1 leaves the suite green, because the budget test measures that a skipped candidate does not *spend* the budget, not what the budget is. Pinning the number would be the cardinality floor this repo's craft reference warns against.
- The hook now spends real work in directories the session is not in: `currentTree` runs `git read-tree`/`add -A`/`write-tree` against an isolated `GIT_INDEX_FILE` in up to four other worktrees on every completion-claiming turn, writing loose objects into the shared object database. It never touches another worktree's real index, and the objects are gc-able. The cost is measured only at one derived worktree, against a 3 MB transcript and the wired 15 s timeout read from `settings/harness.json`; the four-worktree shape is bounded by argument rather than by a test, and a timeout is a fail-open.
- The injected `reason` now names a worktree path. It is the string `git worktree list` printed, never the transcript value that selected it, and it is whitespace-collapsed and truncated to 200 characters — but a worktree path is chosen by whoever created the worktree, which in an unattended run is the agent. That is self-injection inside one trust domain, a channel rather than a closed door, and the sanitiser itself has no test that exercises it, because every path the tests drive through it is already benign.
- Enumerating `git worktree list` as a *source* of candidates is still rejected, and the reason is unchanged and current. Every non-root worktree of this repo sits on an unprotected branch — that held when the design measured it and again when review re-measured it, and four of the ones standing at review were abandoned `promote/*` worktrees from a verb this repo retired in #435, which is precisely the "stale worktree from a finished ticket" the rejection names. Enumerating would refuse every stop in the repository until someone deleted them. The command returns only as a membership filter, which is what removes the permanence: a finished ticket's worktree has to appear in *this* session's transcript to be reached at all.
- Four of the candidate-admission conditions have no exclusive killer, measured at review by an independent mutation table and recorded rather than acted on, because each is a survivor whose first reading is *the edit changed nothing on any reachable input*. `bare` and `prunable` are unreachable in the shipped order: `worktreesOf` already drops a worktree whose path does not resolve, which is every worktree git would call prunable for the ordinary reason. The already-evaluated-as-`cwd` and already-yielded conditions are subsumed — on every input the tests reach, the protected-branch filter or the payload candidate's own verdict gets there first, and their only distinct observable is one wasted tree computation out of four. Containment is a path-component boundary rather than a string prefix, which is right, but no fixture builds a sibling directory whose name merely extends a worktree's (`.worktrees/439-notes` beside `.worktrees/439`), so dropping the separator survives the suite; the failure it would cause is bounded — a block naming a real ungated worktree of the same repository, costing one gate run.
- The size guard's language set is derived from the tracked suffixes rather than fixed to `*.py`, and `hooks/` answers to the hard limit (#444). What remains is stated at its size. A source file at the repository **root** answers to no tree, because the derivation drops a path with no directory component; the 2026-08-01 assessment measured that gap, found no instance, and declined to file it, and this change left it where it found it. The two classification literals are held only by the completeness check, which reports a suffix nobody was asked about — so *misclassifying* a source suffix as non-source is a one-line silent unguarding it cannot see, and only the disjointness check stands between the two sets. The block comment form `/* size: */`, which the rule's own prose names for CSS, is deliberately not accepted: no tracked language has a block as its only comment form, and one arriving would land its suffix in the unclassified set and go red before it could be over-limit and unseen. And `templates/size-guard.md`, the walker shipped to consuming repos, still keys on `# size:` alone — a separate consumer contract, out of this change's scope.
- The Stop hook asks whether there is anything to claim by comparing the current tree against `HEAD^{tree}` and, for committed work, `HEAD` against the branch `CONTEXT.md` names as `integration`. A repo declaring no `branches:` block gets only the first comparison, so a clean task branch carrying committed but ungated work is not blocked there. The push guard is unaffected: its fallback protected set needs no declaration.
- Both hooks read a file any process with repository write access can create, and both run in the same trust domain as the agent they check. A model with `Bash` can forge a marker, delete a real one, or edit the hook. They are evidence plumbing, not an authority: what they buy is that the default path now requires the gate to have actually run over the exact bytes, and that manufacturing the evidence is a discrete, transcript-visible act instead of a silent omission. The controls of record remain server-side branch protection and the gate output in CI. `permissions.deny` globs back the force-push guard; nothing in that block covers a push to `dev` by target, so a fail-open in the target guard has nothing behind it.
- Every hook payload and transcript fixture in the suite is a **hand-authored model of the host's contract**, and the suite is self-consistent with that model whether or not the model is right. Three things are now observed rather than assumed: the Stop payload, captured verbatim from Claude Code 2.1.220 and driven through the hook as-is; the deny-over-allow precedence the push guard rests on, watched live refusing a command a standing `permissions.allow` entry covered; and, since #439, the transcript entry's envelope — one verbatim host-written JSONL line with its path redacted, from which every scope fixture is built by rebinding `cwd`, establishing that `cwd` is a top-level sibling of `type` and `sessionId` rather than something nested under `message`. Two live headless runs recorded on #439 validate the model end to end, and the same reading of eight real `/build` transcripts confirms the shape independently. Everything else — the `PreToolUse` payload's own shape included — remains a model, and a live run is the only validation available for it.

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
- *Enumerate `git worktree list` and block on any task worktree holding ungated work* — one stale worktree from a finished ticket would refuse every stop in the repository, permanently, with no way to clear it. **Still rejected as a source of candidates** (annotated 2026-08-16, #439, which measured seven of this repo's eight worktrees on unprotected branches and would therefore have refused every stop). #439 reinstates the same command as a **membership filter** over a transcript-derived selector; that is a different mechanism with a different failure mode, and it does not overturn this rejection.

**Consequences.** Fail-open is three states rather than one. A hook that **could not run** opens loudly on stderr, both hooks, per #303. A hook that **ran but could not establish the facts** splits on recoverability: the push guard denies, because one gate run clears a false deny while the act it guards is irreversible; the Stop hook allows, because a Stop hook blocking on an unreadable git wedges a session with no exit. A hook that **established the facts and found no evidence** is not failing open at all — that is the decision it exists to make. The marker directory is a bounded cache, pruned by age and count; ADR 0015 retired the run ledger and this does not revive it. The contract is duplicated in three languages and therefore pinned by *execution* rather than by inspection — the path in all three, the tree in two, the freshness bound in three — because a shared `hooks/lib/` module would be invisible to three `hooks/*.js` scanners that walk the directory non-recursively, and its own load failure would disarm both enforcement hooks at once.

### Decision: The Stop hook's scope is this session's transcript cwds intersected with this repository's worktrees

*Decided 2026-08-16 (#439), narrowing the Stop-hook half of *The gate marker is the authorisation, and it lives in the git directory*. The marker contract, its home, and the push guard are untouched.*

**Context.** *The gate marker is the authorisation, and it lives in the git directory* shipped a Stop hook that asked its question of exactly one directory, the payload's `cwd`, and recorded the gap as "a session's working directory is fixed at launch". That grounding was wrong in a way that mattered. Two probes against a real headless session established that the payload `cwd` tracks the **main** session's shell and moves with its `cd`, while a **sub-agent's** `cd` never propagates back. A `/build` orchestrator alternates — the tracker from the repo root, `git add -A` and `git write-tree` from the worktree — so whether the hook was pointed at the ungated work at the moment of the claim was decided by which command happened to run last. The guard was not absent; it was unreliable in exactly the direction it exists to catch.

**Decision.** The hook evaluates the payload `cwd` first and by its existing rules, then derives further candidates from the intersection of this session's transcript `cwd` values with `git worktree list --porcelain` for the anchor repository. The transcript is a **selector, never a source of paths**: every string reaching `spawnSync`, the tree computation or the injected `reason` is one git printed, and the transcript value is a set-membership key that is then discarded. That answers "trigger or evidence" mechanically rather than rhetorically — the selector can only move the checked set within a closed set whose two endpoints are both known and neither unsafe, "check none" (what shipped in #436) and "check every worktree of this repo" (the design #436 rejected). Every new path fails open.

**Alternatives.**

- *`/build` writes a session-to-worktree pointer the hook reads* — exact and non-heuristic, and rejected on the decisive ground that it makes enforcement depend on the agent remembering to cooperate. `/build` is model-followed prose, so a run that forgets the line is silently unguarded, which is circular for a guard whose purpose is catching the agent that forgot. It also covers only `/build` and needs an install step.
- *Parse `cd <path>` out of Bash `command` text* — model-authored argv as evidence, unbounded by shell expansion, and it would let a model name any directory on the filesystem. This is the thing *prose may be the trigger, never the evidence* forbade.
- *Read the sub-agent transcripts* at `dirname(transcript_path)/<session_id>/subagents/agent-*.jsonl` — mechanically derivable and measured to be useless: every entry records the sub-agent's launch directory.
- *Use the per-entry `gitBranch` field as the scope signal* — measured to disagree with `cwd` in a real run, so not load-bearing.
- *A tail-only transcript window instead of ceilings on work* — narrows silently as sessions grow, and a hook that quietly stopped firing looks exactly like one that allows. Ceilings count distinct values and tree computations instead.
- *First-match rather than longest-prefix worktree mapping* — this repo nests its worktrees inside the root worktree's path, so first match sends every one to the root, the root is skipped as protected, and the change ships dead with a green suite. Measured: mutating longest-prefix to first-match kills sixteen of the seventeen scope tests.

**Consequences.** A `/build` driven from the repo root is now covered for the worktrees its orchestrator actually entered, and a worktree only ever entered from a sub-agent's shell still is not. The hook spends up to four extra tree computations in directories it is not in, each isolated by `GIT_INDEX_FILE` and each writing gc-able loose objects into the shared object database. The injected reason gains a worktree path, which is git's string but a name the agent chose when it created the worktree — self-injection inside one trust domain, collapsed and truncated rather than closed off. The transcript read is per physical line through `JSON.parse`, top-level own-property only, so untrusted tool output cannot present a `cwd` key: JSON escapes newlines, so nested content never gets a physical line of its own. Reading the transcript with a byte regex instead is the degradation that would break this, and it is the one a test kills exclusively.

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
