# ADR 0019 — Purpose precedes proof

- **Status:** Accepted
- **Date:** 2026-08-31
- **Source:** accepted proposal [`purpose-before-proof`](../proposals/purpose-before-proof.md)

## Context

Harness asks for the smallest correct implementation, but its lifecycle has rewarded proof before purpose. The spine and ADR 0016 assign prose meaning to review, while `spec-authoring` and `review-discipline` say every criterion needs a test and the architecture principles say every enforced invariant must fail the gate. A prose or configuration requirement can therefore attract more verification machinery than the subject it protects.

The assurance surface has regrown since ADR 0017's cull. On `origin/dev` at 2026-08-31, `git ls-files 'tests/unit/*.py'` found 45 modules and 21,171 lines, compared with ADR 0017's dated record of 24 modules and about 10,600 lines. The earlier record did not preserve its exact command, so the comparison is directional. The Node-floor WIP showed the decision failure directly: a three-line Node runtime declaration attracted roughly 300 lines that statically inferred compatibility from source APIs.

## Decision

**A requirement, check, implementation, dependency, or paragraph must protect a named user outcome, system contract, recorded risk, or necessary decision before Harness spends work proving it.** The lifecycle looks for an existing native enforcement point and then chooses the cheapest evidence that can fail for the claimed reason.

Evidence follows its subject:

| Subject | Evidence |
|---|---|
| Executable behaviour or invariant | A failing test first, followed by the smallest passing implementation |
| Runtime or compatibility floor | One declaration plus functional execution on every environment the repo claims to support |
| Configuration or generated artifact | The platform validator, producer check, or one end-to-end smoke check |
| Prose or guidance | Direct review or use in a representative scenario; no predicate over meaning |
| Unobserved risk | A recorded decision naming the risk and why a preventive guard earns its maintenance cost |

A builder or designer may challenge a criterion before implementation. They provide evidence and a smaller replacement, then amend the tracker issue with the owner's decision. They never descope silently. Executable behaviour and invariants retain strict RED; this decision changes what deserves a test, not the test-first standard for code.

Prose quality remains human judgment. `writing-quality` is loaded just in time for substantial handoffs, reports, specs, and decisions. Harness adds no prose scorer, semantic predicate, banned-word test, or checked-in editing evaluation suite.

This is a reasoning rule, not a required form. Agents record rejected or amended criteria, non-obvious guards, and deliberate trade-offs. Routine choices create no new section, score, ratio, or report.

## Alternatives rejected

- **Hard budgets and guards.** Test-to-product ratios, prose limits, and diff ceilings turn proxies into targets and create new proof machinery.
- **Install external minimalism and writing skills.** Harness already absorbed the useful Ponytail and Stop Slop ideas. Parallel skills duplicate guidance and leave the lifecycle contradiction intact.
- **Periodic audits only.** `process-economy` can remove waste, but only after the repo has paid to build and maintain it.

## Consequences

- Specs and reviewers reject valueless or duplicative evidence before implementation rather than rewarding literal compliance.
- Code paths, regressions, security boundaries, money paths, parsers, loops, and other executable contracts keep test-first protection.
- Compatibility claims may require a real version matrix. If the repo cannot run a claimed version, it narrows the claim instead of maintaining a static source oracle.
- Reviewers carry semantic prose judgment openly. Automated checks remain limited to executable behaviour, structure, negative space, asset integrity, and other mechanically decidable properties.
- The accepted proposal's first two work items update the installed guidance. Its third work item runs one bounded Harness audit; further audits use the existing assessment cadence.
