---
name: authoring
description: "Use when writing anything a downstream agent or person will read and act on — a proposal, a change spec or ticket body, a design hand-off, an as-built or reference spec, a decision record, a review report, a commit body, a handoff. Covers the shape of the artefact and the prose it is written in: what each spec type must contain, how to ground it in current reality, how to choose its assurance lane, and how to state it plainly. Not for code, structured data, or deciding whether the work should happen — that is the spine's lifecycle."
model: inherit
---
# Authoring

How to write anything a downstream agent reads and acts on, so it is actionable and complete. Most of that is specs, in two families: lifecycle specs that flow with a task, and reference specs documenting a standing part of the system. The spine (`AGENTS.md`) owns the lifecycle; this is the craft.

The same discipline governs artefacts that are not specs — a ticket body is a prompt, a hand-off is a brief, an as-built record is a report. Load [`references/prose.md`](references/prose.md) immediately before writing any substantial prose.

## Lifecycle specs — three moments in a task's life

| Spec | Answers | Lives in | When |
|---|---|---|---|
| Proposal | "Should we do this, and how big is it?" | `specs/proposals/<slug>.md` | Before it is confirmed work — needs a decision, carries real unknowns, or is too large for one change |
| Change | "What exactly will this one piece of work do?" | The tracker issue | While the work is in flight |
| Feature | "What does the product do today?" | `specs/features/<feature>.md` | Permanent, as-built record |

A proposal is decided and broken into change specs; each is built, and its delivered behaviour recorded into the feature spec. Small, clear work skips the proposal.

## Reference specs — standing documentation

Some specs are not tied to a task. They document a stable part of the system, are updated when it changes, and meet the same bar as any spec. Two recognised types, with paths in `harness.yaml`: an infrastructure spec for the operational reality — domains, hosting, services, deployment — and an architecture-principles spec for how the system is built here, extending `engineering`.

## What every spec shares

- *Actionable.* A reader can act without asking: a decider can decide a proposal, an implementer can build a change spec test-first.
- *Design, not just acceptance.* State how it works, not only what the user can do. Criteria check the outcome; the design says how it is produced. A spec with criteria and no design pushes the hard decisions onto the implementer mid-build, where they are made fastest and worst.
- *Scaled to size.* A one-line fix is one line. Depth earns its place, and no TBD stands in for a decision.

## Decisions live in the spec they govern

A consequential decision is recorded in the spec it governs — a Decision block in the feature spec, or the architecture-principles spec when it is cross-cutting — and superseded in place rather than in a second file. A repo that declares `paths.decisions` in `harness.yaml` keeps standalone records there instead, and that declaration is the only switch. Recording it is not the whole obligation: name the roles the decision binds and confirm each one's own entry document reaches the record, because a rule filed where only one role reads it is invisible to the others it governs. Load [`references/decisions.md`](references/decisions.md) when you are writing or superseding one; `architecture` decides whether a choice rises to a decision at all.

## Proposal spec

For an idea that is not yet confirmed work. Sections, per `templates/proposal.md`: Problem, Options (approaches with trade-offs, not one blessed answer dressed as inevitable), Recommendation, Not doing (the capabilities cut, why each is out, and what would reopen it), Open decisions (what, and by whom), Breakdown (the change specs this would spawn, ordered by dependency and foundations first, each declaring whether it is separable or a sequential step), Risks. The outcome is explicit — accepted, rejected, or split. It does not sit half-decided.

*Not doing binds the tickets it spawns.* Nothing named there enters a spawned ticket without amending the proposal first, which is the mirror of the no-silent-descoping rule: a builder may not quietly shrink a criterion, and may not quietly widen one either. Options records the alternatives considered and Not doing records the capabilities cut. Those are different sets, and the second is the one that leaks, because a boundary reconstructed one ticket at a time is a boundary widened.

*Order the breakdown by cost of being wrong, not by what ships alone.* Dependency decides the order. Where the work introduces a shape that is expensive to unpick, that shape is item 1, held for the operator, and the items building on it declare a dependency on it. It is a real change rather than a spike: it ships the shape as an executable artefact — types, schema, migration, interface — with the tests that hold it, and records the decision in the spec it governs, so the agents get something to build against and the operator gets something to hold an opinion on. Four dimensions decide whether a shape earns that position, and any one of them fires it.

| Dimension | Fires when | Does not fire when |
|---|---|---|
| **Migration** | Data already written must be transformed rather than dropped, including seed data, dev state, and any deployed instance somebody relies on | Nothing has been stored in the shape yet |
| **Blast** | Changing it fans out across call sites, the way restructuring keys touches every query | It sits behind one interface |
| **Access** | The shape decides how it can be queried, so getting it wrong surfaces as a rewrite under load rather than a bug to revert | Access patterns are unaffected |
| **Comprehension** | The operator cannot steer the work without seeing the shape first, and would otherwise reconstruct the model from a diff to hold an opinion | The shape is evident from the ticket |

Adding a column fires none of them and is ordered by dependency like anything else; restructuring tables and keys fires the first three; a new entity's primary shape usually fires access and comprehension. Three of the four are stage-independent — only migration softens before a product has users, and only partly, because seed data and dev state are still data — so this test fires regularly rather than seldom. The stage line calibrates how much gets built; it does not calibrate whether the shape gets decided.

*Declare each breakdown item separable or sequential.* An item is **separable** when it has a checkable outcome of its own, whether or not later items depend on it; an item the four-dimension test fires is separable by construction, which is what keeps a held foundation out of the item built on it. It is a **sequential step** when it is one step of a change whose interim state nothing pulls but the next step — a slice of a migration, an annotation whose only reader is the edit that follows it. A run of sequential steps files as one ticket and each separable item as its own (`tracker` → *`create`*). Describe as many slices as the work needs: the declaration decides how they file, not how finely the proposal may think. Dependency between separable items stays in the tracker's native fields.

## Change spec

A single, concrete piece of work, on the tracker issue. Sections per `templates/change.md`: Problem, Approach, Design (data model / contract / scenarios), Acceptance criteria, Out of scope. If the design rests on a cross-cutting decision, settle that in a proposal first.

Write the Design section to the depth the *decision* needs. The ticket's assurance level, not your judgement while writing, decides whether the work earns a separate design pass at build time — so a thin Design section is right on a change whose design was never the hard part, and wrong on one carrying a real decision.

A bug noticed in actual use does not start from a blank change spec: `/capture` fills the capture mode of `templates/change.md` at the moment of noticing, and `/build` extends it at build time.

### Grounding — measure it, do not recall it

Verify every fact the spec rests on that names a file, function, flag, version or decision against the code as it is *now*, and every ticket identifier it cites against the tracker (`tracker` → `open`) — a recalled fact reflects what was true when it was written. **Confirming that the mechanism a citation describes is real does not confirm that the number points at it**: #671 spent two of its three review cycles correcting citations whose story held while their identifiers did not.

**A feature-lane design artefact is bound by this section too, not the change spec alone.** A design asserts the same things a spec does: this decision is settled, this is the only caller, nothing else touches this surface. Re-derive each of its tree claims against the tree it will be built on, rather than against what the proposal assumed or an earlier decision recorded. #650's design instructed reverting a decision #649 had deliberately shipped, and nobody caught it at design time because no rule asked anyone to look.

Record it as a **Grounding** section: verified facts each anchored to a `path:line` or a measured value, any decision the ticket assumed settled that is actually open, and the open questions. The rules below separate grounding from restating the ticket.

*Use an instrument that can return the answer you are not expecting.* A comparison that follows a symlink cannot tell a copy from a link; a search matching only file paths cannot see a retired flag name. Choose the probe by what would falsify the claim, not by what would confirm it.

*A completeness claim names the method that produced it and that method's blind spot.* "Every consumer", "the only home", "nothing else reads this" are claims about the whole call graph, so cite the enumeration — the grep, or the type followed to its readers. If it finds a second consumer, the invariant is not recorded: it *is* a finding. A scope claim without its enumeration launders an open violation into a documented invariant that later review trusts.

*Verify a negative by grepping the primitive, not by recalling the surface.* The rule above fixes the shape a claim like "nothing does X" must take; this one is the search that makes it true. Name the call, import, type, decorator or field that anything doing X would have to reach for, grep that, and read every hit. Searching the vocabulary instead finds whatever named itself after X and misses the sibling doing the same work under another name, which is how a negative claim survives review: it was checked against the code its author already knew about.

*Where the spec names a file the diff will touch, name the guards over it.* A test that mirrors or bounds that file is a fact about current reality in exactly the sense this section already requires, and a run that leaves it out spends a gate cycle discovering it.

*A stated number names the test that would falsify it.* A count of call sites, a guard-to-change ratio, a coverage figure: each is a claim about something that moves, and `templates/change.md`'s Cost line and acceptance criteria are where they cluster. Give the command or the enumeration that recomputes it, so a later reader runs the number instead of trusting it. A figure that names no test goes stale in silence the first time the thing it counted changes, and nothing in the gate is watching. Distinct from `engineering` → *Name the instrument*, which governs a figure published about what shipped code produces; this one governs a number asserted in a spec, whose subject may never have run.

*A mechanism claim names the behaviour somebody watched.* Reading a guard's source is not watching it refuse. Where the spec says a hook fires, a script writes, or a check rejects, name the run behind it — the input, the output read, and where that happened. Source read alone yields what the code appears to do, and a defect looks identical from there.

*Negative verification is per claim, not per set.* The primitive-grep rule above answers one negative, so a spec asserting several owes one search each: a set cleared in a single pass is a set where every claim but one was assumed. **A negative about what has been *decided* has no primitive to grep** — no call, import, type or field, only prose in a decision record — so read `paths.decisions` directly rather than letting the rule degrade into a keyword scan. #685 grepped `paths\.(designs|proposals|…)` to establish that nothing said where a design artefact goes; `specs/decisions/0007-design-verb.md:129-131` had said it in prose, which that grep could have matched only if the decision had gone the other way.

*A filing resting on a decision names the artefact and the commit carrying it, and whoever writes it opens that artefact.* A proposal, ADR or settled decision cited from recall is a premise nobody has checked. `/capture` and `/propose` leave Grounding empty by design, so a filing-time citation stays unverified until build, which is late: five Calibrate tickets cited a proposal accepted on a stated date that has never existed in any branch — two were correctly held, three sat in Todo for six more days, and a routine tick began building one.

Grounding scales to size: a one-line fix gets a one-line grounding. Where a sub-agent host is available, a read-only sub-agent produces the brief and the executor records it verbatim; otherwise the executor self-grounds inline.

### Acceptance criteria

Each criterion names what it protects and uses ADR 0019's evidence. The rules below decide whether one is writable at all.

**A criterion names evidence the building session can produce, or it names who produces it and when — and a criterion of the second kind does not block a PASS.** Evidence needing a credential the run has not got, a second backend, a board it cannot write, or an operator at a keyboard cannot be closed by building, so a criterion naming one holds the verdict hostage to something no work supplies. Marking it operator-supplied at filing turns a review-time discovery into a known precondition. Measured: a feature-lane ticket shipped with three criteria short of their stated evidence for exactly this reason, unnoticed until the binding.

*An evidence line names an artefact and its producer, not a class.* "Direct review" and "representative use" are categories from the matrix, not evidence. Write the read, the anchors it is read against, and where the result is recorded — *the reviewer reads the new text against `templates/change.md:41` and records the comparison in the review report*.

*File size is never a criterion.* State the structural outcome the size stands for: the engine-protocol layer lives in its own module, the verb file holds only glue, no test import changes — checkable by import structure and tests. A quantity gets no carve-out; the measuring-test rule applies with no exemption (`engineering`), and being forced to write the counting test is the tell that the number was never the requirement.

*Nor is a file list.* Name the outcome and the surface it must be reachable from, never the files a fix is expected to touch — a list is a guess at the implementation made before the grounding runs, and #640's AC-2 named two files that must each carry a pointer when one of them says in its own body that none of the method is restated there.

A builder who finds a criterion wrong does not descope it silently: give the evidence and a smaller replacement, get the owner's approval, amend the tracker issue before implementing. A rationale confined to a commit body leaves the ticket false.

*The same obligation binds whoever amends someone else's ticket.* A scope change filed as a comment — the right channel, since a second ticket on the same surface is the twin the spine's *Filing* rule refuses — **edits the acceptance criteria, and leaves the comment carrying the rationale**. The criteria are what a reviewer certifies against; a comment is not, so an amendment that never reaches them cannot be certified either way, however carefully the thread is read. Filing it in both places costs the filer one edit, once. Leaving it in the comment alone charges every later run for the reconciliation, and #636 shipped a review against the narrow scope before anyone noticed.

### Three conditional sections

A change spec may owe a **Watchlist trigger**, a **Lifecycle sweep**, or an **Instrument replacement** section, each present only when its trigger fires. Load [`references/conditional-sections.md`](references/conditional-sections.md) while writing the spec to decide which apply.

## Feature spec

The canonical as-built record of what the product does today, plus the Decision blocks that shaped it. Written by the **reviewer** on PASS, from the diff — never by the builder. It answers "how does X work, and why is it that way?", grouped by user-visible behaviour.

Three things it must not do. It must not enumerate a set the code owns — a class family, a command surface, a reason vocabulary: name the module that owns it, or pair the list with a guard that derives the set and fails when the two disagree. And it must not state a present-tense quantity on its own: the figure names the commit it was measured at, or a guard derives it, or the record restates the invariant the number was evidence for. A prose list with no derivation goes stale at the commit adding the next member, and a count with no anchor falsifies silently. Nor may it cite a line number within its own file: every ticket appends a section here, so an insertion anywhere above a citation moves it, and the sentence that is now wrong is one nobody edited — cite the section heading — the record already gives each ticket its own — or a string `git grep` will find. Measured at #636: one citation moved twice in a single session, corrected by two different authors, the second time in a merge commit the verdict no longer covered.

## Choosing assurance

Every ticket carries exactly one `assurance:<level>` label, chosen at filing, and this is the one home for *how that choice is made*. What each level obliges a run to pay for is the spine's contract and `/build`'s. The lane is chosen by blast radius:

| Level | Lane | Choose it when |
|---|---|---|
| `trivial` | Fix | The diff is describable in one sentence, touches no protected area, and adds tests without editing any. |
| `simple` | Change | The default: one checkable outcome, bounded decisions, no contract change. |
| `complex` | Feature | The work changes a contract, reaches a protected area, or carries a consequential decision its proposal did not settle — the spine's three, and no fourth. |

Two rules carry the weight.

*Uncertain is `simple`*, always: guessing high costs one design pass, guessing low costs the independent read that would have caught the guess.

*Never infer `trivial` from a ticket calling the work minor, a short description, or a small estimated diff.* All three are properties of a ticket's text, written by whoever filed it and influenceable by anyone who can open an issue; what earns the fix lane is the diff. A ticket cannot argue its way down, and a run may only raise a lane, never lower it, so a diff that outgrows its lane becomes a change or a feature mid-run with the reason recorded. Reaching a protected area is the exception: that stops and holds whatever the lane says, and raising the label is what the operator does when releasing the hold, not a substitute for it.

## Quality bar

A spec is ready when its type is right, its design is specified to the depth the work needs, its decisions are recorded in place, each criterion names what it protects and has producible evidence, and no unresolved decision is presented as settled. The reviewer checks it against this bar (`review-discipline`).
