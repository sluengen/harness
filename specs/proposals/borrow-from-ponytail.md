<!-- guidance:template-proposal@0.1.1 -->
---
proposal: borrow-from-ponytail
status: accepted            # draft | under-decision | accepted | rejected | split
date: 2026-06-15
related: [CAL-710, CAL-711]
---

# Proposal: Borrow two ideas from ponytail into the guidance

> Fold ponytail's simplicity *decision ladder* into `engineering-principles` and its *over-engineering deletion lens* into `review-discipline` — taking the two genuinely additive ideas from the plugin into source-versioned guidance, and installing nothing.

## Problem / motivation

[ponytail](https://github.com/DietrichGebert/ponytail) is a popular Claude Code plugin (a "lazy senior dev" YAGNI persona). We evaluated it for adoption across harness-enabled repos. The conclusion was **do not install it**, for reasons that are themselves about fit, not quality:

- Its philosophy overlaps almost entirely with what `engineering-principles` and `code-quality` already enforce (simplicity over cleverness, smallest change, no premature abstraction, minimal dependencies) — so the marginal value of the persona is low.
- Its delivery model fights our process. It injects an always-on persona via a `SessionStart` hook on every session, mutates global `~/.claude` state, and — most consequentially — its rules pull *against our two iron laws*: it says "trivial one-liners need no test, YAGNI applies to tests too" (vs. our test-first law) and tells the agent to "challenge the rest of the requirement in the same breath" (vs. our spec-compliance / no-self-descoping rule). An always-on instruction that erodes test-first and invites unilateral descoping is net-negative in a harness repo.
- It would be an **un-versioned, un-stewarded parallel guidance system** — exactly what `/assess system` (guidance-coherence: MECE, lean, the universal/repo boundary) exists to prevent.

But two ideas in it are genuinely additive *beyond* what we already have, and both are small:

1. **A simplicity decision ladder.** We state the *values* (no premature abstraction, smallest change, minimal dependencies) but never give the agent the ordered *procedure* that operationalises them at the moment of writing code. Ponytail's "stop at the first rung that holds" ladder does exactly that.
2. **A named over-engineering taxonomy for review.** `review-discipline` already cites principle violations and has diff-scoped deletion lenses ("Dead surface after a deletion", "Port-time orphan"), and `/assess code` already audits duplication and dead code. What is missing is the *named vocabulary* that makes "this is over-built, here is what replaces it" a fast, repeatable call rather than a case-by-case judgement: `stdlib` / `native` / `yagni` / `shrink` / `delete`, each naming what replaces the cut.

The cost of doing nothing: we keep recommending against the plugin (correctly) but leave these two cheap, real improvements on the table, and every future evaluation of a similar plugin re-runs the same analysis from scratch. This proposal is also the durable record of *why* we did not adopt ponytail.

## Options

**Option A — Install the ponytail plugin as-is.** Adopt the marketplace plugin across harness repos. *Trade-offs:* gets the two good ideas, but at the cost of an always-on hook that erodes test-first and invites self-descoping, global state mutation, a competing `// ponytail:` comment convention against our `# size:` markers, and an un-versioned guidance surface outside the registry. Rejected — the delivery model collides with the iron laws and the distribution model.

**Option B — Take nothing; rely on the existing overlap.** Treat `engineering-principles` + `code-quality` as already sufficient. *Trade-offs:* zero cost, zero risk, but forfeits the operational ladder and the named deletion taxonomy — the two things that are *not* already present.

**Option C — Borrow the two additive ideas into source-versioned guidance; install nothing. (recommended)** Add the ladder to `engineering-principles` and the deletion lens/taxonomy to `review-discipline`, version-stamped and tested like all our guidance, referenced (not duplicated) from `/assess`. *Trade-offs:* requires two small, reviewed guidance changes and the discipline to keep them tight; in exchange we get the value with none of the plugin's delivery hazards, and the change rides our normal version/registry/CHANGELOG machinery.

## Recommendation

**Option C.** It is the path our own model prescribes: when an external tool has a good idea, fold the idea into the versioned source rather than bolt on the tool. It is justified by `engineering-principles` directly:

- **Minimal dependencies** — an always-on third-party plugin is a standing cost (supply chain, an injected persona we do not control, global state). Two owned guidance lines are not.
- **Make the right thing the easy thing** — the ladder and the taxonomy live in the skills the architect, developer, and reviewer already load, so they apply without a new tool or a new always-on hook.
- **Smallest change** — each addition is a few lines into an existing skill, not a new skill, command, or hook.

Scope guard, stated up front because it is the whole reason we rejected the plugin: **the ladder governs only *what to build*. It must never weaken test-first or license self-descoping.** The added text says so explicitly and cross-references `test-driven-development` and `review-discipline` Stage 1, so a future reader cannot mistake "build less" for "test less" or "drop an acceptance criterion."

## Open decisions

| Decision | Options | Who decides | Recorded in |
|---|---|---|---|
| **D1 — Where the deletion lens lives** | (a, rec.) Canonical in `review-discipline` as a Stage 2 lens + named taxonomy; `assessment-craft` adds a one-line reference for the repo-wide pass. (b) Duplicate the taxonomy in both. (c) Add a standalone `/simplify`-style on-demand command. | user | `review-discipline` (+ a reference line in `assessment-craft`) |
| **D2 — The `ponytail:` comment convention + debt harvester** | (a, rec.) Skip it — we already have `# size:` justification comments and change-spec scope discipline; a second deliberate-shortcut marker plus a `/ponytail-debt`-style harvester is redundant surface (MECE). (b) Adopt a marker + harvester. | user | n/a (skip) or a new change spec if adopted |
| **D3 — Source attribution in the guidance** | (a, rec.) Add no plugin name to the skills; this proposal is the record of provenance. (b) Credit ponytail inline in the skill text. | user | n/a |

D1 is the only one that changes the breakdown. D2 and D3 are confirm-or-redirect on my recommendation.

**Resolved 2026-06-15:** D1 → (a) canonical lens in `review-discipline`, one-line reference from `assessment-craft`. D2 → (a) skip the comment marker and harvester. D3 → (a) no plugin name in the skill text; this proposal is the provenance record.

## Breakdown

Each item is independently shippable as a Linear issue (team **CAL**, project **Harness v3**) with a change spec, built test-first, reviewed, and version-bumped per the source-mode rule (header ↔ `registry.yaml` parity, a `CHANGELOG.md [Unreleased]` entry, and the registry self-version sweep).

1. **[CAL-710] `engineering-principles`: add the simplicity decision ladder** (`0.2.0 → 0.3.0`, minor — additive). A short ordered procedure ("stop at the first rung that holds": does it need to exist → stdlib → native platform feature → already-installed dependency → one line → minimal code), with the explicit scope guard that it governs what to build and never overrides test-first or spec compliance. Update CHANGELOG + registry meta. Guard: the existing `test_guidance_source` parity check covers the version bump; add a focused doc test only if the ladder asserts something machine-checkable (likely not — prose principle).

2. **[CAL-711] `review-discipline`: add the over-engineering deletion lens + named taxonomy** (`0.4.0 → 0.5.0`, minor — additive), and **`assessment-craft`: a one-line reference to it** for the repo-wide `/assess code` pass (`0.2.1 → 0.2.2`, patch). A Stage 2 quality bullet cluster naming the taxonomy (`stdlib` / `native` / `yagni` / `shrink` / `delete`), each finding naming what replaces the cut, sitting alongside the existing "Dead surface" / "Port-time orphan" lenses. Update CHANGELOG + registry meta for both. (Folded under D1(a); D1(b) or (c) reshape this item.)

Both items are pure-prose guidance changes — agent-led flow, the harness drives its own tickets agent-led with Claude-subagent review (Codex when available), not `/build`.

## Risks / unknowns

- **The irony / bloat risk.** Adding guidance that says "build less" is self-refuting if the additions are bloated. Mitigation: dogfood the rule on itself — the ladder is ~6 lines, the lens is one bullet cluster; if either grows longer than what it saves a reader, cut it. The reviewer should apply the new deletion lens to the diff that introduces it.
- **MECE / duplication.** The deletion taxonomy must have one canonical home (D1(a)); naming it in both `review-discipline` and `assessment-craft` verbatim would be the exact duplication `/assess system` flags. Mitigation: canonical text in `review-discipline`, a reference from `assessment-craft`.
- **Over-strengthening YAGNI into the iron laws.** The reason we rejected the plugin is the reason to be careful here: if the ladder's wording bleeds into "skip the test" or "trim the acceptance criterion," we have imported the very defect we avoided. Mitigation: the explicit scope guard in item 1 and a reviewer instructed to check for it.
- **Unknown:** whether D1(c) (a standalone on-demand command) is wanted. My read is no — it overlaps `/review` and `/assess` and adds surface — but it is the one place a reasonable person might disagree, so it is surfaced as an option rather than closed.

---

**Lifecycle.** Ends in one explicit state: **accepted** (spawn the breakdown as CAL issues; record D1–D3 in the specs they govern), **rejected** (this file stays as the record of why), or **split**. Lives in `specs/proposals/`.
