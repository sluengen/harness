---
name: design-system
description: "Use when standing up or working in a repo's design system — the eight-tier structure (`00-brand` … `07-flows`), the three-tier token model, and the builder that resolves tokens into a page's generated `:root` region, or into a token package where the consumer is not a page. This skill's `assets/` are what `/harness:hydrate` copies into the repo's `paths.design_system` when `layers.design_system` is on. Not for the discipline of *using* a system that already exists — the seeded `.claude/rules/design-system.md` carries that, and loads on the paths its own frontmatter names."
model: inherit
---
# Design system

The structure and the token mechanism a repo with `layers.design_system` on
receives from the plugin. Its counterpart is `.claude/rules/design-system.md`,
seeded by `/harness:hydrate` step 5: that rule is the discipline for *using* a
design system, this skill is the system itself.

## The assets, and where they go

**Destination: `paths.design_system`, as `harness.yaml` declares it.**
`/harness:hydrate` step 11 copies **the files the table below names** there, file
by file, each one only where its own destination path is absent — except the rows
that table marks `on request`, which a repo asks for rather than receives.
**The absence half of that** is the workflow's root rule rather than an exception
to it — a file that does not exist has no repo-owned bytes to lose, and one that
does is never rewritten. Copied
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

**`AGENTS.md` is in this directory and is not one of these assets.** It is the
Codex twin of the path-scoped rule, seeded by `/harness:hydrate` step 5 from
`templates/rules/design-system.md`, and it lives here because
`paths.design_system` resolves here — this repo's own twin, seeded into this
repo's own design directory, which happens to be the tree the skill ships. No row
below names it, so step 11 copies it under no circumstances: not where step 5
wrote the consumer's, and not where step 5 wrote none. The copy sitting here
carries this repo's preamble; landed in a consumer it would be that repo's
binding Codex instruction file, written about this one.

**Every shipped asset is written about the repo that receives it, never about
this one.** They are scaffolds: each tier states what belongs in it and what
fills it, and the token values are a placeholder palette a consumer replaces.
This directory is also *this* repo's own design system — `paths.design_system`
resolves here — so the temptation to write the harness's own brand, voice and
page into these files is permanent and was once acted on (#667: every tracked
asset named the harness, and the root `README.md` told a consumer it had no
end-users). This repo's own instance lives in `.claude/rules/design.md`, which
ships nowhere. **An asset that can only be true of one repo does not belong
here**, and the copy disposition is not the remedy: a mark is for an asset whose
landing does something a deletion does not undo, and surplus prose is not that
(`specs/architecture-principles.md` → *An asset table carries a copy
disposition*).

**A repo that already owns a design system keeps every file of it** and receives
only the ones it lacks. Where its layout differs from these eight tiers, that
means it receives tiers it has no use for beside its own — visible in the run's
report, owned by the repo, and removable. The alternative, skipping the whole
copy on any pre-existing directory, is the failure two paragraphs up.

| Asset | What it is | Copy |
|---|---|---|
| `00-brand` … `07-flows` | The eight tiers. The zero-padded prefix *is* the dependency order. | |
| `03-tokens/tokens.json` | The token source of truth — primitive → semantic → component. | |
| `03-tokens/_naming.md`, `how-it-works.md` | The naming scheme, and how a token reaches a page. | |
| `04-primitives` … `07-flows` `_template.md` | The per-entry scaffold each tier's first real entry copies. | |
| `README.md` | The tree's own account of itself, and what to fill in first. | |
| `build_design_tokens.py` | The token builder. **A reference implementation — see below.** | `on request` |

**These rows are the whole of what hydration copies.** A row reaches every file
at or under what it names, so the first row carries its eight tier directories
entire; a file under `assets/` that no row reaches — `AGENTS.md`, and anything a
tool leaves behind, such as the `__pycache__` this repo's own gate writes beside
the builder — is not an asset of this skill and never travels. An empty
`Copy` cell is the default and means copy-if-absent. `on request` is the only
other value, and the builder is the only row that carries it — the section below
says why. A marked asset ships with the skill, hydration reports where it would
land, and a repo that wants it copies it deliberately.

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

**That is why it is the one asset marked `on request`.** It is the only one that
*acts*: every other asset is prose or data a repo reads and deletes, while this
one rewrites a page. Landing unasked inside `paths.design_system` it also becomes
a second answer to the question the repo's own `03-tokens/how-it-works.md`
answers, and the wrong answer carries the plugin's authority. **A repo that
already builds tokens keeps its own builder and asks for nothing** — hydration
names the file and where it would go, and stops there.

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

### Where the consumer is a package, not a page

A design system that emits a **token package** for a native client has no page
and no marker region, so `PAGE_DEFAULT`, `--page` and the region mechanism have
no counterpart there. Everything else transfers unchanged — the eight tiers and
their dependency direction, the three-tier model, `{dotted.path}` resolution,
and semantic-as-the-contract.

Both certifications hold, against different operands. The first asks whether the
emitted package matches what a build of `tokens.json` would write, the package
standing in for the region. The second scans the **consuming source** rather than
one page: every file that renders UI, for raw values that byte-equal a resolved
token — hex and functional colours, and the size literals a stylesheet would have
kept in a `var(…)`. A scan that wide needs a sanctioned-exceptions list, or it is
switched off within a release.

**The plugin ships no scanner, and that is a decision rather than a gap.** A scan
is per-language and per-framework, and the exceptions list it needs is a judgment
about a tree the plugin cannot see. What ships is this description of what the
scan must certify; the scan itself is the consumer's to write in its own language
and wire into its own gate.

## The three-tier token model

- **primitive** — a raw value named by what it *is*. The palette; nothing
  consumes it directly and it does not become a public CSS variable.
- **semantic** — an alias named by what a value is *for*. This is the contract,
  and the only tier the builder emits.
- **component** — an optional per-component narrowing of a semantic value. Empty
  is a legitimate state, and the harness's own capture leaves it so.

`{dotted.path}` in a value is a reference; the builder follows it to a literal.
