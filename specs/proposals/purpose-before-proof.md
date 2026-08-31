---
proposal: purpose-before-proof
status: accepted         # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-08-31
related: [borrow-from-ponytail, plugin-shaped-guidance, ADR-0017, ADR-0019]
---

# Proposal: Purpose before proof

> Make requirements, checks, code, and prose earn their cost before Harness asks anyone to build or verify them.

## Problem / motivation

Harness already says to build the smallest correct thing. It does not apply that discipline early enough.

- The spine and ADR 0016 say a predicate cannot verify what prose means. `spec-authoring` and `review-discipline` still say every acceptance criterion needs a test, while `specs/architecture-principles.md` says every enforced invariant must fail the gate. The broader rules reward prose predicates that the narrower decision rejects.
- `engineering` asks whether code needs to exist, but Stage 1 review first demands literal spec compliance. A builder may renegotiate a bad criterion after discovering the problem, yet the workflow gives no equally clear pre-build path for challenging one. Waste is easiest to prevent before RED.
- New guards must cite an occurrence or a recorded risk, and `process-economy` can remove unearned checks later. Those controls sit after the choice to create the check.
- Writing guidance is loaded for proposals and architecture work, but not for ordinary builder and reviewer handoffs. The prose standard therefore misses much of the prose people read.

The recent growth shows the cost. On `origin/dev` at 2026-08-31, `git ls-files 'tests/unit/*.py'` finds 45 modules and 21,171 lines. ADR 0017 recorded 24 modules and about 10,600 lines after the 2026-08-18 cull. ADR 0017 did not preserve its exact command, so this is a directional comparison rather than a formal delta, but the assurance surface has plainly regrown. The Node-floor WIP is the failure in miniature: a three-line `engines.node` declaration attracted roughly 300 lines that statically inventory Node APIs instead of declaring the supported floor and exercising the helper on supported Node versions.

The external references confirm the useful ideas and the trap:

- [Stop Slop](https://github.com/hardikpandya/stop-slop) supplies the pattern vocabulary already adapted into `writing-quality`. Its scoring and absolute style rules would add another compliance system, so they should not be imported.
- [No AI Slop](https://github.com/petergyang/no-ai-slop) adds two useful editing rules: preserve the writer's voice and make the minimum effective edit. Its separate evaluation checklist is useful for an editing product, but too much machinery for routine repo prose.
- [Ponytail](https://github.com/DietrichGebert/ponytail) supplies the simplicity ladder and deletion vocabulary already shipped through `borrow-from-ponytail`. Installing it would duplicate that guidance and reintroduce its conflicting advice to skip some tests.

Doing nothing leaves the current inversion intact: Harness proves whatever a ticket happens to demand, then asks whether the result was worth building.

## Options

**Option A — Add hard budgets and more guards.** Set limits for test-to-product ratio, prose length, dependency count, or diff size, then test those limits. This is easy to measure and easy to game. It creates the same cottage industry under a new label and turns proxies into goals.

**Option B — Install the external skills.** Run one writing skill and Ponytail alongside Harness. This imports useful editing language quickly, but duplicates guidance already present, adds competing instructions, and leaves the lifecycle contradiction untouched.

**Option C — Put purpose before proof and delete the contradictions.** Add one economy rule to the existing lifecycle: before accepting a requirement or choosing evidence, name the user or system failure it prevents, look for an existing native enforcement point, and choose the cheapest adequate proof. Apply it through `spec-authoring`, `engineering`, and Stage 1 review. Refresh `writing-quality` with the two useful No AI Slop ideas and load it only when substantial prose is being produced. Add no metric, new command, required ticket field, or prose lint.

**Option D — Rely on periodic process audits.** Use `process-economy` to delete waste after it appears. This adds no per-change work, but pays the build, test, review, and maintenance cost before correction. It treats recurrence rather than the decision that caused it.

## Recommendation

Adopt Option C, followed by one bounded Option D audit to remove recent residue.

The policy should be short:

1. **Purpose.** A requirement, guard, abstraction, dependency, or paragraph stays only when it protects a named user outcome, system contract, recorded risk, or necessary decision.
2. **Existing mechanism.** Prefer deletion, a platform declaration, the standard library, a native feature, or an existing test before adding machinery.
3. **Adequate evidence.** Use the cheapest proof that can fail for the claimed reason. More evidence needs more risk, not more enthusiasm.
4. **No silent descoping.** When a criterion fails this test, amend it on the ticket before implementation. The agent brings evidence and a smaller replacement; the owner decides.

Treat this as reasoning, with no new form. Agents record the result only when they reject or amend a criterion, add a non-obvious guard, or accept a deliberate trade-off.

### Evidence by subject

| Subject | Adequate evidence | Evidence to reject |
|---|---|---|
| Executable behaviour or invariant | A failing test first, then the smallest passing implementation | Tests of implementation details that add no failure coverage |
| Runtime or compatibility floor | Declare the floor once and run the real behaviour on each environment the repo claims to support | A second parser that inventories source APIs to infer the declaration |
| Configuration or generated artifact | The platform's validator, producer check, or one end-to-end smoke check | Repeating the producer's regression suite in every consumer |
| Prose or guidance | Apply it in review or a representative scenario; judge meaning directly | Predicates that search for words, paraphrases, scores, or sentence positions |
| Guard over a risk not yet observed | A recorded decision naming the risk and why prevention is worth the maintenance cost | A speculative check with no occurrence, decision, or owner |

The matrix narrows the test-first law to executable behaviour and invariants without weakening it. A real branch, parser, money path, security boundary, or regression still gets RED. A sentence does not get a hundred lines of code to prove that its nouns are present.

### Prose standard

Keep `writing-quality` as a human editing discipline. Add only the useful delta from No AI Slop:

- make the minimum effective edit;
- preserve the author's terminology, cadence, and useful edge;
- cut a sentence when it carries no decision, constraint, evidence, action, or necessary context;
- prefer the specific fact over generic importance.

Builders and reviewers load it just before writing a substantial handoff, review report, spec, or decision. Status updates and structured output do not pay that context cost. No prose scorer, banned-word test, style linter, or checked-in evaluation suite is added.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| **D1 — Pre-build challenge.** Allow a builder or designer to return a criterion for amendment before implementation when it has no named outcome or risk, with evidence and a smaller replacement. Recommended: yes; never silent descoping. | user | new ADR 0019 + `spec-authoring` |
| **D2 — Evidence boundary.** Replace “every criterion has a test” with the subject-based matrix above while keeping strict RED for executable behaviour and invariants. Recommended: yes. | user | spine, architecture principles, `engineering`, `review-discipline` |
| **D3 — Prose enforcement.** Keep prose quality judgment-based and load `writing-quality` just in time for substantial output; add no automated detector or score. Recommended: yes. | user | `writing-quality` + agent roles |
| **D4 — Cleanup scope.** After the guidance lands, run one bounded `process-economy` pass over checks added since ADR 0017, then decide deletions from evidence. Recommended: Harness first; change consuming repos only when the same failure is observed there. | user | assessment report and proposal ledger |

**Resolved 2026-08-31:** D1-D4 were accepted as recommended. Builders may challenge criteria before implementation but never descope them silently; evidence follows the subject matrix; prose stays judgment-based; and the cleanup starts with one bounded Harness pass.

## Breakdown

1. **Reconcile purpose, criteria, and evidence** — record ADR 0019; align the spine, architecture principles, `spec-authoring`, `engineering`, `review-discipline`, `/build`, and the developer/reviewer roles. Remove the contradictory blanket test requirements. Add no wording guard; review the guidance against the five representative subjects in the matrix.
2. **Tighten prose without adding a prose system** — add the minimum-effective-edit and voice-preservation rules to `writing-quality`, credit No AI Slop, and invoke the skill just in time from the roles and commands that produce substantial repo prose. Delete overlapping wording rather than growing the skill.
3. **Run a bounded assurance cull** — apply `process-economy` to post-ADR-0017 checks in Harness, starting with the largest new guard modules and the Node-floor example. Keep checks that can name their incident or recorded risk and survive a killing mutation; propose deletion of the rest through the existing ledger. Record the fixed measurement command so the next pass has a real baseline.

Each item ships independently. Item 1 changes the standing contract; item 2 changes prose output; item 3 removes existing residue. Consumer repos receive items 1 and 2 through the normal plugin refresh and do not gain local duplicate tests.

## Risks / unknowns

- **“Purpose” can become vague permission to skip tests.** The subject matrix and ticket-amendment path prevent that: executable contracts still require RED, and the builder cannot delete a criterion alone.
- **The challenge can become another ceremony.** No mandatory field, score, ratio, checklist artifact, or report section is added. Only a rejected or non-obvious choice leaves a record.
- **Human prose review can be inconsistent.** A semantic predicate cannot remove that judgment; it adds maintenance while testing words instead of meaning. The named editing rules give reviewers shared language.
- **A compatibility claim may require a real version matrix.** That cost is honest. If the repo cannot run the behaviour on a claimed version, it should narrow the claim instead of building a static oracle that approximates support.
- **The audit can become an industry of its own.** Bound it to post-ADR-0017 additions and one baseline pass. Further passes occur through the existing assessment cadence, not a new command or standing ticket stream.

---

**Accepted 2026-08-31.** D1-D3 are recorded in ADR 0019. The three breakdown items are filed in GitHub Todo; D4 bounds the third item to one Harness-first pass.
