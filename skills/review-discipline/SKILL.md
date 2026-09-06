---
name: review-discipline
description: Use when reviewing any artifact — code, a spec, or a design — for spec compliance then quality, or doing a self-check before handing work off. Two stages (does it meet the requirements, then is it well-built), the blocking/size 2×2 that routes every finding, the four-part finding format, and the verdicts a review may return. Load before approving or handing off work. Not for deciding what to build or how to build it — those are the spine's lifecycle and `engineering`.
model: inherit
---
# Review discipline

How to review any artifact — code, spec, design, copy — for spec compliance and quality: by the reviewer before merge, by the developer as a self-check, or ad hoc. The standards are the ones the builder built to, since structure, scope and verification come from `engineering`, so the bar cannot drift between the two sides.

## The mandate

A review answers four questions and no others: is it correct; does it meet the criteria as they stand on the ticket now; does it cheat (the four categories below, the one thing a review is uniquely able to see); and is every test-file diff justified, one item per file naming the property that moved. Silence on a test file is not a pass.

**A review does not hunt for improvements.** A reviewer prompted to find gaps reports some even when the work is sound, and each enlarges the diff and spends a cycle. The 2×2 still routes one the review *trips over*; going looking is out of scope.

Pre-existing problems in untouched files are not findings; prose predating the branch is the tree's baseline, not this diff's regression — three consecutive tickets spent most of their review budget on that mistake. What the diff *makes* false is in scope.

### The four cheat categories

How a green result gets manufactured. Check each against the diff by name.

| Category | What it looks like |
|---|---|
| Modified tests | A test changed so the implementation passes it. Over 79% of measured cheating is this one — hence law 7 and the test-lock hook. |
| Overloaded comparisons | An assertion widened until it cannot fail: equality relaxed to membership, a bound to truthiness, an exception swallowed by the assertion meant to catch it. |
| Hidden state | A value smuggled past the interface under test — a global, a cached module, a fixture the code mutates, an env var the test sets and the code reads. |
| Special-cased inputs | The implementation recognising the test's own data: a branch on a sentinel, a fixture literal in the source, a table keyed by the test cases. |

## Two stages, in order

Stage 1 passes before Stage 2 begins: quality is irrelevant if the artifact does not do what was asked.

### Stage 1 — spec compliance

Does the output meet the requirements?

1. Read the requirements before the artifact — the criteria *and* the design.
2. Mark each criterion met, partial or missing, and confirm it names what it protects and uses ADR 0019's evidence.
3. Check the design was specified and followed; one shipped with no design invented its contract mid-build.
4. Check scope, and check intent: a technically compliant solution that misses the point fails.
5. For executable behaviour, verify the tests fail first and exercise the named contract. Do not demand a test for prose, a runtime floor, configuration or a generated artifact when the matrix names a smaller adequate form.
6. Review against the criteria *as they stand on the ticket now*. A criterion changed only in a commit body is a **FAIL** even when the engineering call is right: the ticket is the canonical record, so a Done ticket whose current criteria the diff did not meet is false.

If Stage 1 fails, stop, report what is missing, and issue a FAIL.

### Stage 2 — quality

For code, correctness first: logic errors, edge cases, off-by-one, null handling, error messages.

Then over-engineering — complexity the change *adds* that a simpler form replaces. Tag each finding with the cut and say what replaces it: `stdlib:` hand-rolled what the standard library ships; `native:` doing what the platform does; `yagni:` an abstraction with one caller; `shrink:` the same logic in fewer lines; `delete:` dead code. This lens is complexity only — do not relabel a real bug as over-engineering, and never flag the minimum smoke test as bloat.

Two conditional references. When the change adds a type predicate, deletes or ports a public surface, repeats a helper, or introduces placeholder, synchronization, fetch/refetch or watchlist changes: [`references/diff-shape-checks.md`](references/diff-shape-checks.md). When it adds or edits a guard, a mutation table, or a deletion pass: [`references/craft.md`](references/craft.md), the defect classes that read as green.

For specs and designs: completeness, evidence fit, clarity enough that an implementer could build it without asking, and consistency with recorded decisions.

For frontend code: design-system adoption, accessibility, and every state handled — empty, loading, error, 0 / 1 / many / missing. The repo's `.claude/rules/design-system.md` is the standard and loads on the paths the diff touches.

## Findings — the 2×2

Two axes decide everything about a finding, each a binary.

*Blocking* means shipping it would ship a defect: a security hole, data loss, a crash, a spec violation, a logic bug, a missing test for a criterion. Everything else does not block, and there are no severity grades beyond this.

*Small* means cheap *and* contained — a bounded edit whose consequences end where the edit does. A two-line change in a load-bearing area is not small.

|  | Small fix | Large fix |
|---|---|---|
| Blocking | Fix now, in this branch | **FAIL** — return it to the builder |
| Non-blocking | Fix now, in this branch | Propose it — one line in the report's Proposals section, and one ledger entry |

The default posture is fix it now: three of the four cells resolve inside this branch, because fixing a small thing costs less than discussing it.

**Render both axes on every finding**, at its heading — *blocking · small* — or in a placement table. A report that reasons about blocking and never states size has not discharged the 2×2, because size is the axis deciding fix-now against propose, and "all findings are blocking" is not a placement.

There is no "small but not worth doing" cell: a stateable defect is a finding and a small one is worth its cost; anything vaguer never became a finding.

### Bugs are filed; improvements are proposed

The line is factual, not judged: *does the tree contradict its own contract today* — a red gate, a crash, a guard asserting something false, a document describing behaviour the code does not have. That is a *bug*, and any agent files it through `tracker` without asking. Everything else — a hole, a gap, a could-be-better — is an *improvement*, proposed and never filed, by every agent path including this one.

Nothing in the split is a judgement call, on purpose: a queue anything can add to grows without bound. State the consequence with the rule, so a later edit cannot keep the mechanism and lose the point — **the improvement volume an agent can file is structurally zero.**

A proposal is one line in this report's Proposals section *and* one entry appended to an improvement ledger; which ledger, and what the entry carries, is [`references/improvement-ledger.md`](references/improvement-ledger.md). Nothing else happens to it — no ticket, no queue slot. A report is read once and archived; the ledger outlives it.

**Write the entry into the report when you cannot reach the ledger**, in full — case, provenance, suggested home, which ledger — rather than noting that an append is owed. An owed append nobody performs is the improvement lost.

*The recursion cap.* A ticket filed from a review carries the `review-finding` label, marking generation one — the last. When the ticket *under review* carries it, this review fixes or drops what it can and files nothing; the Propose-it cell closes with it. A large-and-blocking finding there is still a FAIL, never a new ticket.

## Every finding has four parts

What (the specific issue), where (file:line or section), why (the rule it violates), how (a concrete fix). "Could be improved" is not a finding — be specific or say nothing.

**Report a claim's homes as one finding with a count, not one instance per cycle.** The finding is the claim and the count is its size; reporting them one at a time across cycles turns a repair into a lineage.

## The verdicts

The three are the spine's contract, not this skill's; what each obliges a review to do is here. A review ends in exactly one of them, and no command, agent or report may act on a fourth word:

- **PASS** — the criteria are met over the tree the verdict binds to, and the change is ready to integrate.
- **FAIL** — a blocking finding stands. Return it to the builder and re-review, bounded by the stop rule below.
- **DEFER** — nothing blocking stands, but the ticket cannot ship as scoped without a call this review may not make. Hold it through `tracker`, and route any out-of-scope finding by the 2×2. Not a soft PASS: nothing merges on a DEFER.

One further outcome is not a verdict. A small, contained, in-scope finding the reviewer *repairs in place* rather than returning, because the builder's context is gone and a round trip for a two-line fix is pure waiting. But a reviewer that repairs has reviewed its own work, so a repaired candidate goes to a second fresh reviewer, which may certify only if it makes no repair of its own. The repairing reviewer reports **Ready for final binding** — the intermediate state the driving command names — rather than a verdict. Certification belongs to a reviewer that changed nothing.

## Reviewer obligations

- *Run the verification yourself* — fresh run, output read (`engineering`). Do not trust the builder's claim.
- *Before certifying, load* [`references/certifying.md`](references/certifying.md) — the as-built-record gate, the twin sweep, and the ordering that makes the gate cover the tree that ships.
- *Report:* the verdict, the mandate reviewed under, one explicit item per test file with the four cheat categories checked by name, Stage 1 result per criterion, Stage 2 findings each placed on both axes with the four parts and what happened to them, a Proposals section carrying every improvement or the word `none`, the verification output, the `reviewed_tree`, and whether visual evidence was consulted. That last line reads `consulted`, naming the capture directory, or `not consulted` with one reason: not a user-facing change, not supplied, or not readable by this reviewer. Silence on it is incomplete, and a bare `not consulted` is that silence wearing a label.

## On a FAIL

A FAIL returns the blocking findings to the builder and re-reviews. How many times that may happen, and what an exhausted budget obliges, is [`references/fail-stop-rule.md`](references/fail-stop-rule.md), whose numbers come from `harness.yaml`. Load it on a FAIL.
