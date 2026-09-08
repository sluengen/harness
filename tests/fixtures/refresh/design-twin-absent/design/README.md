# nano-ERP design system

A layered design system for a **composable business platform with its own
identity**. The structure is borrowed from the `form` design system — a one-way
dependency stack, a three-tier token model, and a lint that forbids raw values —
but the *content* is ERP-native and the *delivery* is different: the token layer
is emitted as runtime-swappable CSS custom properties, resolved per request from
the branding resolver rather than baked per build.

nano-ERP is **not** a white-label shell. It looks like itself everywhere. What a
tenant customises is the *system* — modules, terminology, optional fields,
configuration — not the skin; an org's only visual affordances are a logo and an
accent, for recognition rather than identity. A separately branded **cell** is a
different thing again: it gets its own design-system implementation, not an
override. That model, and the decisions behind the current skin, are recorded in
[`decisions/`](decisions/).

```
┌─ 00 · Brand        ─ who the platform is, and what "white-label" means here
├─ 01 · Voice        ─ how the product reads (labels, errors, empty states)
├─ 02 · Principles   ─ interaction, density, and accessibility laws
├─ 03 · Tokens       ─ the atomic decisions — colour, size, type (the source of truth)
├─ 04 · Primitives   ─ single-responsibility UI elements (as the SPA lands)
├─ 05 · Patterns     ─ reusable compositions of primitives
├─ 06 · Archetypes   ─ page-level chrome contracts
└─ 07 · Flows        ─ multi-screen sequences for a user goal
```

A layer may consume the layers above it; **nothing reaches downward**. Tokens do
not know about primitives; a primitive does not define its own page chrome.

## Three rules

1. **A layer never reaches downward.** If a token references a component, or a
   primitive hardcodes a page layout, the abstraction is in the wrong layer.

2. **Nothing is hardcoded.** The source of truth is
   [`03-tokens/tokens.json`](03-tokens/tokens.json). Components bind to **semantic**
   tokens (`var(--color-accent-default)`), never to a raw hex or pixel value. This
   is *enforced*, not asked for — [`scripts/tokens/lint.ts`](../scripts/tokens/lint.ts)
   fails `npm run verify` on any raw colour or size literal in scanned code.

3. **The theme layer is chrome only.** Tokens answer *"what does it look like"* —
   never *"what does it do or say."* Terminology, configuration, optional fields,
   and entitlement are the platform's other customisation mechanisms
   (`specs/module-audit.md` Part 4). A "theme" override that changes behaviour or
   copy is a Part-4 escalation, not a token. This boundary is recorded as **D14**
   in `specs/architecture-principles.md`, restated against
   [`decisions/brand-model.md`](decisions/brand-model.md).

## Why runtime, not build-time

`form` re-skins a single brand at build time (`as const` TS baked into the
bundle). nano-ERP resolves branding from the database per request, so the *same*
bundle must be able to render with a different accent without a rebuild. The
build therefore emits **CSS custom properties**
([`build/tokens.css`](build/tokens.css)) — the runtime-swappable form — and a
per-org stylesheet overrides only the six brandable colour variables. The same
mechanism is what lets a cell swap the token set wholesale. See
[`03-tokens/how-it-works.md`](03-tokens/how-it-works.md).

The proposal this system implements is
[`specs/proposals/tenant-theming-design-tokens.md`](../specs/proposals/tenant-theming-design-tokens.md).
It is delivered in five slices (ERP-101…105); this substrate is **ERP-101**. The
brandable-override contract (ERP-102) and runtime `/theme.css` delivery (ERP-103)
build on the outputs here.

## Build and check

| Command | Effect |
|---|---|
| `npm run tokens:build` | Regenerate `build/tokens.css` + `build/tokens.ts` from `tokens.json`. |
| `npm run tokens:check` | Fail if the committed outputs drift from the source (runs in `verify`). |
| `npm run tokens:lint` | Fail on any raw colour/size in scanned consuming code (runs in `verify`). |

The generated outputs in `build/` are **committed** (so the typed module is
importable without a build step, and the CSS is reviewable in the diff) and
**drift-checked** — the same discipline the repo applies to generated Drizzle SQL.
Never hand-edit them.

## Status

Layers **00-brand**, **03-tokens**, **04-primitives**, **05-patterns** and
**06-archetypes** are substantive: the brand and its palette since the decisions
in [`decisions/`](decisions/), tokens since ERP-101, the seven core primitives
since ERP-188, the Table/Toolbar/Utility-block patterns since ERP-189, and the
app-frame archetype since ERP-187, which is the frame every authenticated screen
renders inside. Layers **01-voice** and **02-principles** state the platform's
stance in one `README.md` each and are `status: active` — voice since ERP-213,
the interaction and density laws since ERP-215. **07-flows** is substantive since
ERP-222, which authored four shipped sequences as state machines with each state
mapped to the archetype and screen that renders it. No layer is a scaffold any
more; the page-layout proposal's breakdown
(`specs/proposals/page-layout-system.md`) is what filled them in, each entry
landing with the screen that first adopts it. Each layer carries a `README.md`;
entry files arrive with the components that need them.
