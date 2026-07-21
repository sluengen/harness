<!-- guidance:template-proposal@0.1.2 -->
---
proposal: repo-guide-landing-page
status: accepted            # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-20
related: [four-loops.html]
---

<!--
Decided 2026-07-20 (operator):
- Page role: VISUAL COMPANION — README stays the canonical text front door; the hosted page links from it.
- Hosting: docs/index.html on main via Pages "deploy from branch", default URL sluengen.github.io/harness/ (no custom domain).
- Freshness: hand-authored + LEAN GATE GUARD (verify-gate check that page-named commands/skills/agents exist in registry.yaml).
The five breakdown items ship as three change specs (content sections merged into one build — one file, one style, one design pass):
- CAL-1200 — Build the repo-guide landing page (docs/index.html)   [breakdown items 1–3]
- CAL-1201 — Host on GitHub Pages + link from README               [breakdown item 4]
- CAL-1202 — Gate guard against repo-guide guidance drift          [breakdown item 5]
-->


# Proposal: A one-page repo guide, hosted as the harness landing page

> Grow the internal Four Loops diagram into a single self-contained page that also explains the harness (the verbs, how the agent drives them) and the guidance it distributes, and host it on GitHub Pages as the project's landing page.

## Problem / motivation

The repo went public on 2026-07-19 (CAL-1029). A newcomer's first contact is now the GitHub repo home — the rendered `README.md`. The README is thorough but text-only and long; it answers "how do I install and drive a ticket" well, but does not give a *shape-of-the-whole* view in one glance: the operating model, what the verbs are and how an agent orchestrates them, and what the distributed guidance (skills / agents / commands) actually is.

We already have a strong visual asset for one third of that story — `four-loops.html`, a self-contained styled page with a concentric-loops SVG. But it has two problems:

1. **It's stale and untracked.** It was drafted 2026-06-13 and is not committed. It still claims the as-built review is "closed by hand (find the old chat)" and that decisions live embedded with "no separate `decisions/` folder" — both now false (the `reviewer` records the feature spec on PASS via `close`; ADRs live in `specs/decisions/`). Left as-is it misinforms.
2. **It only covers the operating model.** It says nothing about the harness's own verbs, its gate/ledger invariants, or the guidance catalog — the things a public visitor most needs to understand what this project *is*.

The status quo cost: the best visual explainer of how we work is rotting on disk, invisible to the public, while the public front door is a wall of prose. Nothing forces either to stay current.

## Options

**Option A — Refresh `four-loops.html` in place, leave it a private working doc** · Fix the stale claims, commit it, but keep it an internal artifact not linked anywhere public. · Cheapest. But wastes the public-launch moment, and an uncommitted-then-committed-but-unlinked file still drifts because nothing depends on it being right.

**Option B — Grow it into a one-page repo guide and host it on GitHub Pages** *(recommended)* · Keep the Four Loops hero, then add two sections: **the harness** (verbs, gate/ledger invariants, how the agent drives them) and **the guidance** (skills / agents / commands catalog). Correct the stale content. Host as `docs/index.html` served by Pages, linked from the top of the README. · A proper landing page at launch; one artifact tells the whole story. Cost: a hand-authored HTML page duplicates facts that live canonically in `CONTEXT.md`, `commands/`, and `registry.yaml`, so it will drift unless we guard it.

**Option C — Generate the whole page from canonical sources** · A build script reads `registry.yaml` (guidance inventory + versions), `CONTEXT.md` (verbs, stack), and command headers, and emits the HTML; Pages serves the generated file. · Never drifts. But it's a real build system for one page — heavy, and the narrative/visual parts (the SVG, the prose) can't be generated anyway, so it only removes drift from the list sections.

**Option D — Fold everything into the README, drop the standalone page** · Put the visual as an embedded diagram (SVG/image) and the catalog as Markdown tables in the README; no separate hosted page. · One source, always the front door, no Pages setup. But GitHub's Markdown rendering can't carry the styled layout the visual needs, and a 400-line README is worse, not better.

## Recommendation

**Option B, with a lean drift guard borrowed from Option C.** Grow `four-loops.html` into a single self-contained `docs/index.html`, hosted on Pages, linked from the README. Keep it hand-authored (the design and narrative are the point, and `engineering-principles` favors the simplest thing that works), but add **one** cheap invariant so it can't silently rot the way the current file has: a gate-run check that every command / skill / agent the page names still exists in `registry.yaml`. That catches the worst and most likely drift — a renamed or removed piece of guidance — without standing up a generator for a single page.

This keeps the README as the canonical text front door (GitHub renders it on the repo home; it stays the install/drive reference) and makes the hosted page the visual companion it links to — separation of concerns, not duplication of the whole README.

Content scope for the page, in one screen's worth of narrative:
- **Hero — The Four Loops** (kept, corrected): the operating model, with Build as the harness-driven core.
- **The harness** (new): the three verbs (`start` / `review` / `close`) + read/ops verbs, the two invariants that make the record trustworthy (SHA-bound verdicts; append-only ledger; builder ≠ recorder), and how an agent drives them (`/harness run`, the verb loop; the Docker wrapper). This is the "how it works" the ask calls for.
- **The guidance** (new): the catalog it distributes — skills, agents, commands — each with a one-liner, sourced from `registry.yaml` so the list is honest.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Hosting mechanism + URL: `docs/index.html` on `main` via Pages *deploy-from-branch* (recommended) vs a `gh-pages` branch vs a GitHub Actions deploy; default `sluengen.github.io/harness/` vs a custom domain (CNAME, as brewspec does) | user (operator — enabling Pages is a repo-settings action) | `specs/infrastructure.md` |
| README relationship: page is a **visual companion** the README links to (recommended) vs the page's content is mirrored back into the README vs the page replaces the README as the repo's front matter | user | this proposal + `specs/infrastructure.md` |
| Freshness strategy: hand-authored + a **lean gate guard** that page-named guidance exists in `registry.yaml` (recommended) vs fully hand-authored with a manual update checklist vs generated from sources | user / architect | `specs/decisions/` (a cross-cutting doc-drift decision) if the guard is adopted |
| As-built record: is this a `specs/features/` feature spec, or a docs artifact recorded only in `specs/infrastructure.md`? | reviewer, at record time | n/a (decided at PASS) |

## Breakdown

The change specs this would spawn once accepted, each shippable on its own:

1. **Refresh + relocate the Four Loops content** — correct the stale claims (reviewer records the as-built spec on PASS; ADRs in `specs/decisions/`; verb model), move `four-loops.html` → `docs/index.html`, commit it. The page still renders standalone after this step.
2. **Add "The harness" section** — verb cards (`start` / `review` / `close` + read/ops), the gate/ledger invariants, and how the agent drives them (`/harness run`, the verb loop, the Docker wrapper), in the existing visual style.
3. **Add "The guidance" section** — the skills / agents / commands catalog with one-liners, laid out to match the spec-flow section.
4. **Wire up hosting** — enable Pages on the chosen mechanism, add `<meta>`/Open-Graph tags + a favicon for a shareable card, and link the hosted page from the top of the README. (Includes the operator step to turn Pages on.)
5. **(if the guard is adopted) Drift guard** — a `scripts/`-level check, run in the verify gate, asserting every command/skill/agent named in `docs/index.html` resolves in `registry.yaml`.

## Risks / unknowns

- **Drift is the core risk** — a marketing/overview page duplicating the verb contract and guidance list will rot; the current file is proof. The lean guard (item 5) mitigates the highest-likelihood case (renamed/removed guidance) but not prose going subtly out of date. Accepted trade-off; a full generator (Option C) is disproportionate for one page.
- **Pages exposes `docs/`** — publishing from `main`'s `docs/` folder means anything else placed there is world-readable. Low risk (the repo is already public), but the folder's purpose should be documented so nothing sensitive lands there.
- **Release cadence** — Pages served from `main` only updates on a `dev → staging → main` release, so the landing page lags `dev`. Acceptable for a landing page; worth stating so no one expects it to track `dev`.
- **Single-file weight** — the page must stay self-contained (inline CSS/SVG, no external fetches) to host cleanly and load fast; embedded raster assets (OG image, favicon) should be modest.
- **What would invalidate the recommendation** — if the user wants the content to *be* the README (Option D) rather than a companion, the hosting and drift-guard work falls away and this becomes a much smaller README-edit task.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
