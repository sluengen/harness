---
name: design-system
description: "Use when standing up or working in a repo's design system — the eight-tier structure (`00-brand` … `07-flows`), the three-tier token model, and the builder that resolves tokens into a page's generated `:root` region. This skill's `assets/` are what `/harness:hydrate` copies into the repo's `paths.design_system` when `layers.design_system` is on. Not for the discipline of *using* a system that already exists — the seeded `.claude/rules/design-system.md` carries that, and loads on its own whenever a UI file is opened."
model: inherit
---
# Design system

The structure and the token mechanism a repo with `layers.design_system` on
receives from the plugin. Its counterpart is `.claude/rules/design-system.md`,
seeded by `/harness:hydrate` step 5: that rule is the discipline for *using* a
design system, this skill is the system itself.

## The assets, and where they go

**Destination: `paths.design_system`, as `harness.yaml` declares it.**
`/harness:hydrate` step 11 copies this skill's `assets/` there **file by file,
each one only where its own destination path is absent.** That is the
workflow's root rule rather than an exception to it — a file that does not exist
has no repo-owned bytes to lose, and one that does is never rewritten. Copied
bytes are the repo's from that moment: no later hydration rewrites one, which is
what keeps this inside ADR 0022 point 1, whose permitted pattern is exactly a
generator copied out once and owned thereafter by the consumer.

**Per file, not per directory, and the distinction is load-bearing.** Step 5
runs earlier in the same layer-on run and seeds `AGENTS.md` — the Codex twin of
the path-scoped rule — *into this very directory*. A copy that asked whether the
destination **directory** was absent would therefore find it present in every
ordinary run, copy nothing, and leave the consumer an `AGENTS.md` and no tiers
while the run reported success. Asking per file is what makes the two steps
compose.

**`AGENTS.md` needs no special case, and is still step 5's.** Step 5 writes it
first, so the per-file rule finds it present and skips it. Nothing here may copy
it ahead of step 5: this skill's copy of that file is the harness's own, carrying
this repo's preamble, while step 5 writes the consumer's from
`templates/rules/design-system.md`.

**A repo that already owns a design system keeps every file of it** and receives
only the ones it lacks. Where its layout differs from these eight tiers, that
means it receives tiers it has no use for beside its own — visible in the run's
report, owned by the repo, and removable. The alternative, skipping the whole
copy on any pre-existing directory, is the failure two paragraphs up.

| Asset | What it is |
|---|---|
| `00-brand` … `07-flows` | The eight tiers. The zero-padded prefix *is* the dependency order. |
| `03-tokens/tokens.json` | The token source of truth — primitive → semantic → component. |
| `03-tokens/_naming.md`, `how-it-works.md` | The naming scheme, and how a token reaches a page. |
| `04-primitives` … `07-flows` `_template.md` | The per-entry scaffold each tier's first real entry copies. |
| `build_design_tokens.py` | The token builder. **A reference implementation — see below.** |

## The eight tiers

A layer may consume lower-numbered layers only; **nothing reaches downward**. A
token that references a component, or a primitive that defines its own page
chrome, is in the wrong layer — that is the diagnostic, not a style preference.

`00-brand` who the product is · `01-voice` how it sounds · `02-principles`
interaction, density and accessibility laws · `03-tokens` the atomic named
decisions · `04-primitives` single-responsibility elements · `05-patterns`
compositions of primitives · `06-archetypes` page-level chrome contracts ·
`07-flows` multi-screen sequences.

Tiers `04`–`07` ship as scaffolds. Each states its purpose and why it is empty
rather than being omitted — a tier fills in when its precondition arrives (a real
component boundary, a second page), and an empty tier that says so is worth more
than a missing one.

## `build_design_tokens.py` is a reference implementation, not a turnkey tool

**Read this before running it against your page.** The builder resolves
`tokens.json`'s *semantic* tier to literal values and writes them into a
marker-delimited region inside a page's `:root` block. The mechanism is
portable. **Two things in it are not, and both are the copying repo's to edit:**

- **`SEMANTIC_TO_CSS_VAR`** maps each semantic token path to the CSS custom
  property name *the harness's own `docs/index.html`* binds to — `--build`,
  `--ink`, `--product-soft`. Your page's variables are not those. Rewrite the map
  for your page before the first run.
- **`PAGE_DEFAULT`** points at `docs/index.html` beneath the repo root. Point it
  at your page, or pass `--page` every time.

Run unedited against another repo's page, it writes that page's `:root` region
full of variable names nothing in the page consumes. That failure is quiet — the
region is syntactically fine and the old hand-authored declarations are gone —
which is why this warning is here rather than in a comment.

**What it resolves without configuration:** its token source. The builder reads
`03-tokens/tokens.json` **beside itself**, so it works wherever the design
directory sits — nested under `skills/` as it is in the harness, or a repo-root
`design/` as it is in most consumers. Nothing to set.

**`--check` certifies two things**, and the second is the one worth having:

1. The generated region matches what a build would write — ordinary drift.
2. **The page *outside* that region carries no hex literal that byte-equals a
   resolved token value.** Those are hand copies a region-only check cannot see,
   and a token revalue rewrites the region and leaves every copy silently stale.
   Added at #466 after an assessment measured **21 such copies of 12 distinct
   values** in a single page.

Wire `--check` into the repo's gate; it names the literal, its line, and the
`var(--…)` that replaces it.

## The three-tier token model

- **primitive** — a raw value named by what it *is*. The palette; nothing
  consumes it directly and it does not become a public CSS variable.
- **semantic** — an alias named by what a value is *for*. This is the contract,
  and the only tier the builder emits.
- **component** — an optional per-component narrowing of a semantic value. Empty
  is a legitimate state, and the harness's own capture leaves it so.

`{dotted.path}` in a value is a reference; the builder follows it to a literal.
