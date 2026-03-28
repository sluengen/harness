# Code Review

This skill defines how to review any artifact — code, specs, designs, copy — for quality and spec compliance. It applies to:

- The **reviewer agent** performing formal pipeline reviews
- The **orchestrator** doing ad-hoc quality checks outside the pipeline
- **Dev agents** self-checking work before handoff
- The `/self-review` command at pipeline checkpoints

## Two-Stage Review

Every review follows two stages in order. Stage 1 must pass before Stage 2 starts.

### Stage 1: Spec Compliance

Does the artifact do what was asked? One question: **does the output match the input requirements?**

1. **Read the requirements first.** Before looking at the artifact, read the input that defined what it should be — the product spec, design doc, task description, or acceptance criteria.
2. **Check each requirement.** For every acceptance criterion or stated requirement, verify it is addressed. Note which are met, which are partially met, and which are missing.
3. **Check scope.** Was anything added that wasn't asked for? Was anything in-scope skipped?
4. **Check intent.** Does the output match the spirit of the requirements, not just the letter? A technically compliant implementation that misses the point is a failure.

For code specifically:
5. **Verify TDD compliance.** Tests exist for every acceptance criterion. Tests cover edge cases. Tests are meaningful (not `assert True`).

**If Stage 1 fails, stop.** Quality is irrelevant if the artifact doesn't meet requirements. Report what's missing and issue a FAIL.

### Stage 2: Quality

Is the artifact well-made? This stage only runs after Stage 1 passes.

**For code:**

- **Correctness** — Logic errors, edge cases, off-by-one, None/null handling, error messages
- **Security** — Input validation, parameterized queries, no dangerous functions, no secrets in code, path sanitization
- **Performance** — Efficient queries, no unnecessary full-table scans, handles large inputs gracefully

**For specs and designs:**

- **Completeness** — All sections filled, no TBD placeholders, no unresolved questions
- **Testability** — Every acceptance criterion can be verified by a test (not subjective like "feels fast")
- **Clarity** — An agent could implement this without asking clarifying questions
- **Consistency** — No contradictions between sections or with existing specs/ADRs

**For frontend code (in addition to the above):**

- **Design system** — Token classes only (no hardcoded hex), shared primitives from `components/ui/`, icons from `components/icons/`, font tokens for typography
- **Accessibility** — Semantic HTML, alt text, keyboard navigation, ARIA labels, visible focus indicators, colour contrast

## Severity Levels

| Severity | Definition | Action |
|----------|-----------|--------|
| **Critical** | Security vulnerability, data loss risk, spec violation, crash | Must fix — blocks approval |
| **High** | Logic bug, missing validation, missing test for an AC | Should fix — blocks approval |
| **Medium** | Code style, minor inefficiency, incomplete error handling | Fix soon — does not block |
| **Low** | Suggestion, alternative approach, minor improvement | Nice to have — informational |

Critical and High findings block approval. Medium and Low are noted but do not block.

## How to Report Findings

Every finding must include:
1. **What** — the specific issue
2. **Where** — file path and line number (for code) or section reference (for docs)
3. **Why** — which requirement, security rule, or quality standard it violates
4. **How** — a suggested fix (not just "this is wrong")

Vague findings like "could be improved" or "doesn't feel right" are not findings. Be specific or don't report it.

## Applying This Skill in Different Contexts

**Reviewer agent (formal pipeline review):**
- Full two-stage review with report output
- Run tests independently — do not trust the dev agent's claim
- Write findings to `reviews/` as structured YAML

**Orchestrator (ad-hoc review):**
- Use Stage 1 only for quick spec-compliance checks between pipeline stages
- Use both stages for deeper quality checks when something looks off
- No formal report needed — summarise findings in conversation

**Dev agent (self-check before handoff):**
- Run Stage 1 against your own work: does every AC have a test? Does every test have an implementation?
- Run the verification-before-completion skill (fresh test run, lint check)
- If you find Stage 1 gaps, fix them before handing off — don't rely on the reviewer to catch them

**/self-review command:**
- Uses Stage 1 + Stage 2 with the weighted scorecard from `.claude/review-scorecard.yaml`
- Scores each dimension, calculates weighted score, compares against threshold
- Writes structured result to `reviews/`
