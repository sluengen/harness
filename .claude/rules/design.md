---
paths:
  - "skills/design-system/assets/**"
  - "docs/**"
description: How the design layer and the landing page relate; loaded when either is opened.
---

# The design layer

Loaded when a file under `skills/design-system/assets/` or `docs/` is opened.

- `skills/design-system/assets/03-tokens/tokens.json` is the **source**; the generated `:root` block in
  `docs/index.html` is built from it by `build_design_tokens.py` beside it, and the gate
  fails on drift. Edit the source, never the generated block.
- A token **value** appears nowhere in `docs/index.html` outside that generated region. A
  hand-copied hex is a second copy that no longer tracks its source (ADR 0004, narrowed).
- `docs/index.html` advertises the plugin surface, and the inventory is compared against
  the tracked tree unit by unit. A unit added or renamed is a page edit in the same change,
  and the printed count on a card is the length of the list beneath it.
- The design layer is on for this repo (`layers.design_system` in `harness.yaml`). The
  tokens, primitives, states, accessibility and visual-evidence obligations are the
  repo-owned `.claude/rules/design-system.md`, which loads on the same paths as this file.

## This repo's own brand rules

**Why they are here and not under `skills/design-system/assets/`.** That directory is
`paths.design_system` *and* the tree `/harness:hydrate` copies into every consumer with
the design layer on, so anything written there about *the harness* reaches a repo it is
false about (#667). Those files are scaffolds for whoever receives them; this file is
repo-owned, ships nowhere, and loads on exactly the paths where these rules apply.
**Writing a harness-specific rule into a tier README re-opens #667** — it belongs
here.

- **The page states what is, not what is aspirational.** `docs/index.html` is a record
  of a process that runs today — the install path, the lifecycle, the gate, the
  surface — not a pitch. A claim the page cannot back with a command, a file or a test
  does not belong on it. The inventory half is held mechanically by
  `tests/unit/test_landing_page_inventory.py`; the rest of the page's prose is
  unguarded and rests on this rule alone (#482).
- **One skin, no re-skinning mechanism.** There is no branding resolver, no per-tenant
  override and no build-time variant. The token substrate exists to give the page's
  existing palette names and structure, not to make it swappable.
- **The palette carries meaning, not decoration.** Four hues, one per *domain* of the
  process, used consistently everywhere that domain appears:

  | Token family | Domain it marks | Where it appears |
  |---|---|---|
  | `--build` | the gate and its evidence | the gate panel, its stage list, the fix lane, the gated-merge card, the no-runtime card |
  | `--product` | the guidance surface | the spec-and-build card, the operating-context card, the install steps, the workflow and skill inventories, the ticket lane |
  | `--strategy` | roles and deciding | the agents inventory, the proposal lane, the independent-review card, the principles card |
  | `--quality` | enforcement and health | the hooks inventory, the refuses badge, the lanes-and-holds card, the dogfood card |

  A new surface introducing a fifth "brand" hue unrelated to a domain is a finding.
  The token *names* are inherited from the retired Four Loops model the page presented
  before #482 and are deliberately not renamed — that is a token-source change, not a
  page change — so read each name as the label of the domain in this table, not of a
  loop.
- **Self-contained is a brand constraint, not just a build detail.** The page renders
  standalone with **no external resource request at render time** — no external
  stylesheet, script, image, iframe or web font, and no CSS `url()`/`@import` pointing
  at a remote host. A navigation link (`<a href="https://…">`) is fine: a click, not a
  load-time fetch. Any pattern or primitive proposed for this page must stay renderable
  from the single committed HTML file. It is **stated, not enforced** — the guard that
  failed the gate on a violation went with the pre-v5 cull (ADR 0017 D5) and has not
  been re-established — so a change adding a remote fetch is caught by reading the diff
  or not at all.
- **Density favours a scannable reference over a marketing page.** The page packs its
  hero, principle cards, install steps, lifecycle lanes, gate panel, inventories and
  dogfood cards into one scroll: compact cards with a fixed internal rhythm (heading →
  body → chips or unit list), not generous whitespace between sections. A new section
  needing its own bespoke spacing scale to "breathe" is a finding; reuse the existing
  card rhythm.
- **Every interactive element is a plain link, or there is no interactivity at all.**
  No forms, no client-side state, no JavaScript. An addition that requires script to
  function is a brand decision, not a default some feature may raise on its own.
- **Accessibility specifics for this page.** The ink and muted text roles were chosen
  against the light card and background surfaces they pair with. Nothing communicates
  meaning by hue alone — every lane and inventory carries its name and role in text,
  and each hook's `refuses` / `advises` badge is a word, not a colour. The page carries
  no image conveying meaning; it is text, CSS and two favicon links, and a future
  diagram needs `role="img"` and a descriptive `aria-label` before it ships. The
  per-change obligations are `.claude/rules/design-system.md`.
- **Motion has no law here because the page is static** — no animation, no transition.
  One gets written the first time a change proposes one.

### Voice

**Register: plain, technical, unhurried.** The page describes an operating model to
engineers and agents; it does not sell. Sentences state a mechanism, its evidence, or
the role that carries it.

- **Name the mechanism, not the benefit.** "Ring size = cycle length" states what the
  diagram encodes; it does not call the diagram intuitive or powerful. A claim about
  how good something is, rather than what it does, is a voice violation.
- **Every section heading is a plain label** in the established small-caps eyebrow
  style, never a slogan.
- **Command names and syntax are never paraphrased.** `/build`, `/propose`,
  `/harness:hydrate` appear verbatim, in `<code>`, exactly as a user would type them.
- **Status describes the actual enforcement or advisory role.** Use the page's
  `refuses` and `advises` labels, then name the evidence or condition behind it.
- **Bold marks the one word that carries the sentence's point**, not emphasis
  generally — "Intent flows inward" is bolded on *inward*, because the direction is the
  fact being stated.
- **The fixed terms are the unit names.** Skills, agents and hooks are identified by
  `data-unit` tags, and their visible names come from the tracked tree; the inventory
  test verifies that correspondence, while reviewers check the surrounding narrative
  directly rather than pinning sentence wording.
