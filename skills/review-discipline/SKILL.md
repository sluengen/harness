---
name: review-discipline
description: Use when reviewing any artifact — code, a spec, or a design — for spec compliance then quality, or doing a self-check before handoff. Two stages (does it meet the requirements, then is it well-built), the blocking/size 2×2 for findings, and the four-part finding format. Load before approving or handing off work.
---
# Code Review

How to review any artifact (code, spec, design, copy) for spec compliance and quality. Used by the **reviewer** for formal pre-merge review, the **developer** for self-check before handoff, and anyone doing an ad-hoc quality pass.

The standards the reviewer applies are not separate from the ones the builder built to: structure, scope, and verification come from `engineering`; design values come from `engineering`. This file is the *method* and the *bar*, in one place, so the two sides cannot drift.

## The mandate — what a review is for, and what it is not

A review answers four questions and no others:

1. **Is it correct?**
2. **Does it meet the stated criteria?** — as they stand on the ticket now.
3. **Does it cheat?** — the four categories below, which is the one thing a review is uniquely able to see.
4. **Is every diff to a test file justified?** — one explicit item per test file, named, with the property that moved. Silence on a test file is not a pass.

**A review does not hunt for improvements.** A reviewer prompted to find gaps
reports some even when the work is sound, and every one it reports enlarges the
diff, spends a cycle, and moves the finish line. The 2×2 below still routes an
improvement the review *trips over* — that channel is not closed, and it never
files anything — but going looking is out of scope, and a report padded with
could-be-betters is a failure of this mandate rather than thoroughness.

### The four cheat categories

Measured across agent coding studies, these are how a green result gets
manufactured. Check each against the diff by name:

- **Modified tests** — a test changed so the implementation passes it. Over 79% of measured cheating is this one directly, which is why the spine's law 7 and the test-lock hook exist and why every test-file diff owes an item.
- **Overloaded comparisons** — an assertion widened until it cannot fail: an equality relaxed to a membership, a bound relaxed to a truthiness, an exception swallowed by the assertion that was supposed to catch it.
- **Hidden state** — a value smuggled past the interface under test: a global, a cached module, a fixture mutated by the code it exercises, an environment variable the test sets and the code reads.
- **Special-cased inputs** — the implementation recognising the test's own data. A branch on a sentinel value, a literal from the fixture appearing in the source, a lookup table whose keys are the test cases.

### Review-or-repair

A finding that is **small, contained, and in scope** the reviewer repairs in
place rather than returning — the builder's context is gone, and a round trip
for a two-line fix is pure waiting. But a reviewer that repairs has reviewed its
own work, so **a repaired candidate goes to a second fresh reviewer, and that
one may certify only if it makes no repair of its own.** Repair, hand over,
repeat; certification belongs to a reviewer that changed nothing. Anything not
small, not contained, or out of scope goes back through the 2×2 unchanged.

## Two stages, in order

Stage 1 must pass before Stage 2 begins. Quality is irrelevant if the artifact does not do what was asked.

### Stage 1 — Spec compliance

One question: **does the output meet the requirements?**

1. **Read the requirements first**, before the artifact: the change spec — its acceptance criteria *and* its design.
2. **Check each requirement and its evidence.** For every criterion, mark met / partial / missing. Confirm that it names what it protects and uses ADR 0019's evidence. Verify RED then GREEN for executable behaviour and mechanically enforceable invariants, a declared runtime floor with functional execution, and direct prose judgment rather than a predicate or wording guard.
3. **Check the design was specified and followed.** For non-trivial work the change spec should state its design (data model / interface / scenarios), not just acceptance criteria (`spec-authoring`). If the design was specified, confirm the code matches it; if a non-trivial change shipped with no design at all, that is a Stage 1 gap — the contract was invented mid-build. (Trivial changes are exempt.)
4. **Check scope.** Was anything added that was not asked for? Was anything in-scope skipped? (Per `engineering` → *Scope*.)
5. **Check intent.** Does it meet the spirit, not just the letter? A technically-compliant solution that misses the point fails.
6. **For executable behaviour and mechanically enforceable invariants: verify TDD.** Tests were written to fail first (the diff and history should show it), exercise the named contract, and are meaningful rather than trivially true. Do not demand a test for prose, a runtime floor, configuration, or a generated artifact when the matrix names a smaller adequate form of evidence.
7. **Check the criteria are current, and any challenge is approved and on the ticket.** Review against the acceptance criteria *as they stand on the ticket now* — not a remembered earlier version. A builder who challenged a criterion before build must have supplied evidence and a smaller replacement, obtained the owner's approval, and amended the tracker issue (`spec-authoring`); flag that amendment in the review report. A criterion changed only in a commit body or PR description is a Stage 1 **FAIL** even when the engineering call is right: the canonical record is the ticket, so a Done ticket whose current criteria the diff did not meet is false. (A raw file-size criterion is itself a Stage 1 gap — `spec-authoring` forbids it; the structural outcome is what the spec should state.)

**If Stage 1 fails, stop.** Report what is missing. Issue a FAIL. Do not review quality.

### Stage 2 — Quality

Only after Stage 1 passes.

**For code:**
- **Correctness** — logic errors, edge cases, off-by-one, null handling, error messages.
- **Diff-shape checks** — when the change adds a type predicate; deletes or ports a public surface; repeats a helper; introduces placeholder, synchronization, fetch/refetch, watchlist, or CONTEXT/as-built-record changes, load [`skills/review-discipline/references/diff-shape-checks.md`](references/diff-shape-checks.md) and apply only the matching checks.
- **Craft — defect classes that read as green** — when the change adds or edits a mechanically decidable guard, mutation table, or deletion pass, load [`skills/review-discipline/references/craft.md`](references/craft.md) and check the diff against the matching family. Do not add a prose predicate or wording guard; prose meaning is reviewed directly.
- **Over-engineering** — complexity the change *adds* that a simpler form replaces. Tag each finding with the cut it names, and in the finding name *what replaces it* so the fix is concrete, not a vibe:
  - `stdlib:` hand-rolled what the standard library already ships — name the function that replaces it.
  - `native:` a dependency, or a block of code, doing what the language or platform already does — name the built-in feature.
  - `yagni:` an abstraction with one implementation, a config nobody sets, a layer with one caller — inline it until a second caller exists.
  - `shrink:` the same logic in fewer lines — show the shorter form.
  - `delete:` dead code, a speculative feature, or unused flexibility — replaced by nothing.

  This lens is **complexity only** — correctness, security, and performance stay in their own lenses above; do not relabel a real bug as over-engineering. The single minimum smoke test, or an `assert`-based self-check, is **never** flagged as bloat: the smallest thing that proves the change works is not over-engineering. As with Structure, pre-existing complexity in files this change does not touch is not a finding.

**For specs and designs:**
- **Completeness** — no TBDs, no unresolved questions.
- **Evidence fit** — every criterion names what it protects and uses ADR 0019's evidence suited to its subject. Prose is reviewed or used directly, not scored or reduced to a wording predicate.
- **Clarity** — an implementer could build it without asking. (And it reads cleanly: `writing-quality`.)
- **Consistency** — no contradiction with existing specs or recorded decisions.

**For frontend code, additionally:** design-system adoption and accessibility (`design-system`), and that the surface handles all its states — empty, loading, error, and edge cases (0 / 1 / many / missing), not just the happy path (`ux-design`).

## Findings — the 2×2 (ADR 0015)

Two axes decide everything about a finding, each a plain binary:

- **Blocking or not.** A finding blocks when shipping it would ship a defect: a security hole, data loss, a crash, a spec violation, a logic bug, a missing test for an acceptance criterion. Everything else — inefficiency, incomplete error handling, structural drift, an improvement — does not block. There are no severity grades beyond this; "Critical/High/Medium/Low" is retired vocabulary.
- **Small or large.** Small means cheap **and** contained — a bounded edit whose consequences end where the edit does. A two-line change in a load-bearing area with a wide blast radius is not small. Large is anything that would blow out the diff and the review in flight, or stall the queue behind work the ticket never promised.

|  | Small fix | Large fix |
|---|---|---|
| **Blocking** | Fix now, in this branch | **FAIL** — the ticket cannot ship as scoped; *On a FAIL* below, and a human re-scopes if the budget cannot absorb it |
| **Non-blocking** | Fix now, in this branch | **Propose it** — one line in the report's **Proposals** section carrying the case for it, and one entry in the proposals ledger. This review does not file it and does not queue it |

The default posture is **fix it now — do the job right the first time**. Three of the four cells resolve inside this branch; the builder already has the context, and fixing a small thing costs less than discussing it. Size is the only legitimate reason not to, and blocking is the only thing the **retired** severity scale was ever needed for.

There is deliberately no "small but not worth doing" case. The finding bar above already filters it: a specific, stateable defect or improvement is a finding, and a small one is always worth its own cost; anything vaguer ("could be improved") never became a finding in the first place. A rule with a subjective override attached is not a rule.

**Bugs are filed; improvements are proposed.** The line between the two is **factual, not judged**, and the question is *does the tree contradict its own contract today* — a red gate, a crash, a guard asserting something false, a document describing behaviour the code does not have. That is a **bug**: any agent files it through `tracker`, any time, without asking, carrying exactly one assurance level chosen per `spec-authoring` → *Choosing assurance*. Everything else — a hole, a gap, a could-be-better, and every finding landing in the cell above — is an **improvement**, and an improvement is *proposed*, never filed, by every agent path including this one. Nothing in the split is a judgment call on purpose: a queue anything can add to whenever it thinks something could be better grows without bound, and hardening one filing path at a time never reaches the grant underneath.

**The proposal channel — the report states it, the ledger keeps it.** A proposal is one line in the **Proposals** section of this review's report *and* one entry appended to the repo's proposals ledger, whose find-or-create-by-label recipe is [`references/proposals-ledger.md`](references/proposals-ledger.md) and is not restated here. The entry carries three things: the one-line **case**, a **provenance** link to the ticket or session that raised it, and the **suggested home** — the file or surface a fix would land in. Nothing else happens to it here — no ticket, no queue slot, no second surfacing. A report is read once and archived, which is why the report alone was never the channel: the ledger is the part that outlives it. `/digest` surfaces new entries; `/assess` decides them at the drain.

**A report-borne proposal is not a proposal spec.** The two share a word and nothing else. A **proposal spec** is `specs/proposals/<slug>.md` — options, a recommendation, a breakdown, an explicit outcome (`spec-authoring`). A proposal here is a one-line candidate waiting for a yes or a no. Promotion can produce either artifact: a ticket, where the work is small and now confirmed, or a `/propose` pass, where the answer turns out to carry a decision. Name which one you mean whenever both could be read into the sentence.

State the consequence with the rule, so a later edit cannot keep the mechanism and lose the point: **the improvement volume an agent can file is structurally zero.** The queue holds what an operator decided and what the tree's own contradictions produced, and nothing else has a way in.

**The recursion cap** (ADR 0015), because a queue that grows under review is a failed review process: a ticket filed from a review carries the `review-finding` label — that label marks generation one, and generation one is the last. When the ticket **under review** carries `review-finding`, this review fixes or drops everything it can and files nothing at all — the **Propose it** cell closes with it. A large-and-blocking finding on such a ticket is still a FAIL/hold, never a new ticket. One generation of follow-up, never a lineage.

## Every finding has four parts

1. **What** — the specific issue.
2. **Where** — file:line (code) or section (docs).
3. **Why** — the requirement, principle, or rule it violates.
4. **How** — a concrete suggested fix.

"Could be improved" or "doesn't feel right" is not a finding. Be specific or say nothing.

## The verdict vocabulary

A review ends in exactly one verdict, and these are the only ones a review may return:

- **PASS** — the criteria are met over the tree the verdict binds to, and the change is ready to integrate.
- **FAIL** — a blocking finding stands. Return it to the builder and re-review, bounded by *On a FAIL* below.
- **DEFER** — nothing blocking stands against the tree, but the ticket **cannot ship as scoped** without a call this review may not make for itself. Hold it through `tracker` — comment the reason, `input` label, assigned to the operator — and route any out-of-scope finding by the 2×2 above. It is not a soft PASS: nothing merges on a DEFER.

Every entry point reads this list. No command, agent or report may act on a word this section does not name — an unlisted verdict is a branch no reviewer following this skill can ever reach.

## Reviewer obligations

- **Run the verification yourself.** Do not trust the builder's claim that tests pass. Fresh run, read the output (`engineering` → *Verification*).
- **Record reality on PASS — the as-built-record gate.** The trigger is a **documented-behaviour change, in any lane** (a screen, route, endpoint, CLI command, or any behaviour the as-built record documents — matched from the changed paths the same way the *Architecture watchlist* reads `git diff --name-only`), and the review must either fold the matching **as-built-record** update into this change or record an **explicit deferral naming the reason**. The feature lane always reaches it, because a feature changes documented behaviour by definition; the fix lane never should, and a fix whose diff does reach it is not a fix — upgrade the lane rather than writing the record under it (D7). The record states no bare count: a figure names the commit it was measured at, or a guard derives it, or the record restates the invariant the number was evidence for. A shipped behaviour change to such a surface with **neither** a record update **nor** a recorded deferral is a **FAIL** — the canonical record silently rots otherwise, a drift no later per-change reviewer catches because no future change re-touches the gap. The as-built record is `specs/features/<feature>.md` where the `feature_specs` layer is on, otherwise the design doc / `SPEC.md`; the same gate applies to it. Recording reality is the reviewer's job, not the builder's, written from what the diff actually does. When a surface's as-built record does not exist yet, the first ticket touching that surface creates it; a surface is not permitted to accumulate more than one shipped ticket without one — the record is where a gap between tickets becomes visible, and it cannot do that job retroactively (the spine (`AGENTS.md`)).
- **Sweep for twins — whatever is derived from, or is a copy of, what changed.** A mechanism in this tree often has a **twin**: a template shipped to consuming repos, a byte-identical mirror of a canonical document, a hook and the guard that measures it, a rule and the reference that renders its shape. When the diff changes such a mechanism, the twin is updated in the **same branch**, or the review records an explicit deferral naming the reason. Derive the question from the changed paths — what else in this tree is generated from, restates, or measures the thing that moved — rather than waiting to be told a twin exists. A stale twin ships green by construction: every guard over the original still passes, and the copy the next reader reaches is the one describing the behaviour that was retired.
- **Close the candidate before you certify it — the final-evidence ordering rule.** The tree you verify and the tree your verdict covers are the tree that merges. So the as-built-record update goes **into the candidate first**: draft it from the diff, commit it onto the branch, and only then run the verify gate and decide. Nothing lands after that — a later commit, documentation included, is uncertified tree content and voids the pass. Order it the other way and the record edit is never gate-checked, which matters because a record is delivered tree content that a link, generated-doc, or drift guard can reject. Two consequences worth stating: on a **FAIL** there is nothing settled to record, so no record work is done — it is drafted fresh from the *next* diff; and when the certifying gate goes red **because of your own record edit**, you wrote it, so you fix it and re-run (bounded — two attempts, then FAIL carrying the gate output), never the implementation, which would make you the builder. A **deferral** is ordering-neutral: it lands in the report and the ticket, not the tree. **The verdict binds to a tree, not a commit.** The spine's contract states that equality once and this is the ordering that delivers it: report the `reviewed_tree`, git's tree object for the certified candidate (`git write-tree` prints it over a staged tree), and the flow that ships integrates only while the tree at HEAD still equals it, or carries a merge git alone made from it — the spine's *binding* states both acceptance paths and this ordering is what delivers the first. That is the object the gate's own evidence is named after, so an amend rewriting no bytes voids nothing. A report may also name the commit sha for a human reader; the shipping equality is tree to tree.
- **Report:** a one-line verdict, the **mandate** it was reviewed under, **one explicit item per test file in the diff** — the file, the property that moved, and why the change to it is justified, with the four cheat categories checked by name — Stage 1 result per criterion, Stage 2 findings each placed in the 2×2 (blocking or not, small or large) with the four parts and what happened to it (fixed / proposed / filed / FAIL), a **Proposals** section carrying every improvement this review proposes — one line each with its case, or the word `none`, never an omitted section, and each one also appended to the proposals ledger — the verification output, the `reviewed_tree` the verdict binds to, **whether visual evidence was consulted**, and a final PASS / FAIL / DEFER. The visual-evidence line reads `consulted`, naming the capture directory it read, or `not consulted` with exactly one reason: **not a user-facing change**, **not supplied**, or **not readable by this reviewer** (an engine with no image-returning read tool). A report that says nothing about visual evidence is incomplete, and a `not consulted` with no reason is that same silence wearing a label — neither is an answer.

## On a FAIL — the review→fix stop rule

A FAIL returns the blocking findings to the builder and re-reviews. How many times that may happen, and what an exhausted budget obliges, is one policy owned by [`skills/review-discipline/references/fail-stop-rule.md`](references/fail-stop-rule.md) — load it on a FAIL and follow it there. Its numbers live in `harness.yaml` → `loop:`.
