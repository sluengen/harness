# ADR 0004 — The repo-guide landing page is kept honest by a lean gate guard, not a generator

- **Status:** Accepted
- **Date:** 2026-07-22 (#169)
- **Source:** #169 (this decision, ported from CAL-1202); proposal [`repo-guide-landing-page.md`](../proposals/repo-guide-landing-page.md) (accepted 2026-07-20), which recorded this as an open decision to be settled in `specs/decisions/` if the guard was adopted.

## Context

The public landing page `docs/index.html` (CAL-1200) is hand-authored. It re-states facts that live canonically elsewhere — the guidance catalog (skills / agents / commands) whose source of truth is `registry.yaml`. A hand-authored copy of a canonical list **drifts**: the pre-relocation `four-loops.html` sat stale on disk for weeks, still naming things that had changed, because nothing forced it to stay current. The highest-likelihood, highest-cost drift is a **renamed or removed piece of guidance the page still names** — a public page confidently pointing at a `/command`, skill, or agent that no longer exists.

The proposal weighed three freshness strategies:

- **Fully hand-authored + a manual update checklist** — nothing enforces the checklist; this is the status quo that already failed.
- **Generate the page from canonical sources** (proposal Option C) — a build script reads `registry.yaml` and emits the HTML. Never drifts, but it is a real build system for a single page, and the parts that actually carry the page's value (the SVG, the narrative prose) cannot be generated anyway — so it removes drift only from the list sections while adding standing machinery.
- **Hand-authored + a lean gate guard** (recommended) — keep the page hand-authored, but add one cheap invariant the verify gate enforces: every piece of guidance the page names still resolves in `registry.yaml`.

## Decision

**A lean gate guard, not a generator.**

`scripts/check_landing_page_guidance.py`, wired into `scripts/verify.sh`, parses `docs/index.html` for every named `/command`, skill, and agent and fails the gate when any does not resolve in `registry.yaml`.

- **The machine-readable reference is the `data-guidance="<id>"` attribute** each named piece of guidance on the page carries (the convention CAL-1200 established, so the check keys on a deliberate reference rather than brittle prose-scanning). "Every named piece of guidance" is exactly the set of those attributes.
- **The guard is one-directional: page → registry.** It answers "does everything the page names still exist?" It does **not** enforce completeness (registry → page) — the page is a curated narrative, not an exhaustive index, so a new registry entry is not obligated to appear on the page. It does not generate anything.
- **A page that names no guidance fails too** (exit 2), so a broken or restructured page cannot pass the guard vacuously — the silent-rot failure mode the guard exists to catch.
- **Stdlib only.** The registry is read with a line regex (PyYAML is not a declared dependency), mirroring the existing `test_landing_page.py` / `test_guidance_footprint` pattern where each layer parses `registry.yaml` independently and self-contained.

## Why the guard, not the generator

- **It catches the drift that actually hurt.** The recorded failure was a stale page naming things that had changed. A guard that fails the gate the moment a page-named id stops resolving prevents exactly that, at the cost of a ~90-line stdlib script.
- **`engineering-principles` favors the simplest thing that works.** A generator is standing machinery whose upside (the list can never drift) is bounded to the list sections, while the page's real content — the concentric-loops SVG, the narrative — is hand-authored regardless. The guard buys the drift protection that matters without the machinery.
- **The guard is layered under the artifact tests, not duplicated with them.** `test_landing_page.py` pins the page *as built* (structure, self-containment, no stale claims) as unit tests. This guard is a first-class **gate step** — a dependency-light check that treats the published page as a deploy artifact and runs alongside ruff/mypy, with a gate-level failure message an operator reads directly. Same resolve-against-registry idea, distinct role: one asserts the page was built right, the other guards the published artifact against future drift.

## Consequences

- **A renamed or removed piece of guidance fails the gate** until the page is updated — the page can no longer silently point at guidance that does not exist. Renaming a command/skill/agent now includes updating its `data-guidance` reference on the page, surfaced immediately by a red gate rather than weeks later by a human diffing by hand.
- **Prose can still go subtly out of date** — the guard checks identity (does the named id resolve), not accuracy (is the one-liner still true). This residual drift is the accepted trade-off the proposal named; a full generator would not fix it either (the prose is not generated).
- **Completeness is deliberately unguarded.** Adding a new skill without mentioning it on the page does not fail the gate — the page stays a curated view, and its editor decides what to feature.
