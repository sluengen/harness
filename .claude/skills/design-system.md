# Design System

<!-- PROJECT: Replace this opening paragraph with your project's design system setup -->
The project design system is built on a CSS framework with brand tokens defined in your frontend config. Every UI component, colour, font, and icon must go through the token layer.

This skill covers both **token enforcement** (what values to use) and **visual design craft** (how to use them well). Both are mandatory for frontend work.

---

## Colours — Token Classes Only

<!-- PROJECT: Define your colour tokens here -->
| Token | Classes | Use |
|-------|---------|-----|
| (Define project-specific colour tokens) | | |

**Hard rule:**
- Use token classes — correct
- `style={{ background: '#C4622D' }}` — never
- Arbitrary CSS framework values — never (they bypass the token layer)
- Exception: CSS pseudo-elements and SVG fills that cannot use utility classes — define as `var(--color-*)` in your stylesheet, never as a literal hex string

### Colour Proportions — The 60-30-10 Rule

Every interface follows this balance:
- **60% dominant** — background/canvas
- **30% secondary** — surfaces, cards
- **10% accent** — interactive elements, CTAs

### Colour Rules

- Maximum 3 hues + neutrals in a product UI
- Each semantic meaning (success, error, warning, info) needs background, border, text, and icon variants
- Body text contrast: minimum 4.5:1 (WCAG AA)
- Never use colour alone to convey meaning — pair with icon, text, or pattern

---

## Typography — Font Token Classes

<!-- PROJECT: Define your font tokens here -->
- (Define headline font token)
- (Define body font token)
- (Define data/mono font token)

### Typography Rules

- Maximum 4 font sizes for most interfaces (6 absolute max)
- Line height: 1.4–1.6x for body, 1.1–1.3x for headings
- As text gets larger, letter-spacing gets tighter (-0.01 to -0.04em)
- ALL CAPS always needs extra letter-spacing (+0.05 to +0.1em)
- Weight variation creates hierarchy better than style variation
- Size, weight, and colour create hierarchy — not decoration

---

## Spacing

### Named Layout Tokens

<!-- PROJECT: Define your layout tokens here -->
| Token | Size | Use |
|-------|------|-----|
| (Define project-specific layout tokens) | | |

### The 8pt Grid

All general spacing values must be multiples of 8px (4px for fine-tuning inside components). No random values.

**Key scale:** 4, 8, 12, 16, 24, 32, 48, 64, 96, 128px

**The most important spacing rule:** Internal spacing (inside a component) must be LESS than or equal to external spacing (between components). When this is violated, elements feel disconnected from their containers.

**Proximity creates meaning:**
- Related items: 8–16px apart
- Loosely related: 24–32px apart
- Different sections: 48–64px apart
- Different content areas: 64–128px apart

---

## Elevation and Shadows

Higher elevation = larger blur + more offset. Use shadows sparingly — too many and nothing is grounded.

**Hover states:** interactive elements rise one level on hover.

**Dark mode exception:** use lighter surface colours for depth instead of shadows. Add `border: 1px solid rgba(255,255,255,0.06)` for definition.

### Border Radius

<!-- PROJECT: Choose your border-radius style -->
Commit to a consistent border-radius style across the entire product.

**Rule:** Nested elements have SMALLER radius than parent. Formula: `child-radius = parent-radius - padding`.

---

## Components

### Sizing Principle

Buttons and inputs MUST share the same height scale. When a button sits next to an input, they must feel like one unit.

| Size | Height | Use |
|---|---|---|
| SM | 32px | Secondary actions, compact forms |
| MD | 36–40px | Default for most interfaces |
| LG | 44–48px | Primary CTAs, mobile touch targets |

Horizontal padding on buttons = 2x vertical padding.

### Button Hierarchy

ONE primary button per screen section. Supporting actions get secondary or tertiary treatment.

1. **Primary:** solid fill, high contrast — the main action
2. **Secondary:** outline or subtle fill — supporting actions
3. **Tertiary/Ghost:** text only or minimal background — low priority
4. **Destructive:** danger variant of primary — delete, remove, cancel

**States (ALL required):** default, hover, active/pressed, focus, disabled, loading.

**Icon placement:** leading (left) adds meaning to the label. Trailing (right) indicates behaviour. Icon-only buttons MUST have `aria-label` and tooltip.

### Inputs and Forms

- Every input needs a visible label (NEVER placeholder-only labels)
- Top-aligned labels = fastest form completion, best for mobile
- Label-to-input gap: 4–6px
- Between form fields: 16–24px (MUST exceed label-to-input gap)
- Error messages: danger colour, with icon, replace helper text
- Heights match button heights in the same size class

### Cards

- Consistent padding across all cards in the same view (16–24px)
- Gap between cards > padding inside cards (the internal <= external rule)
- Single clear purpose per card
- Actions at bottom or in header, never scattered through the card

### Tables and Data Display

- Left-align text columns, right-align number columns
- Sortable headers with clear directional indicators
- Sticky headers for scrollable tables
- Row hover state for scannability
- Zebra striping OR subtle borders, never both

### Navigation

- Top nav height: 48–64px
- Sidebar: 240–280px expanded, 64–72px collapsed
- Active state must be immediately obvious (background + weight or colour)
- Icons: 20–24px with consistent stroke weight across the entire set

### Modals and Overlays

- Max width: 480px (forms), 640px (content), 960px (complex)
- Padding: 24–32px
- Close button: top-right, always visible
- Actions: bottom-right, primary action on the right
- Focus trap: Tab cycles within modal only
- Escape key closes the modal

---

## Layout and Composition

### Grid System
- 12-column grid (divides evenly by 2, 3, 4, 6)
- Gutter width: 16–32px (from the spacing scale)

### Alignment
- Left-align text (centred text is harder to scan)
- Align elements to a shared left edge wherever possible
- Optical alignment sometimes matters more than mathematical alignment

### Whitespace
- Whitespace creates grouping, hierarchy, and breathing room
- More whitespace around an element = more importance
- Prefer whitespace over visible dividers to separate sections

### Responsive Design

Design mobile-first, then add complexity for larger screens. Responsive means the experience is GOOD at every size, not just that it fits.

- **Mobile:** single column, bottom nav, full-width buttons, no hover states
- **Tablet:** two columns where appropriate, adaptive density
- **Desktop:** multi-column, sidebar nav, hover states, higher information density

Touch targets: minimum 44x44px.

---

## Dark Mode

Dark mode is first-class, not an afterthought.

- Don't invert colours — dark mode needs its own considered palette
- Desaturate primary colours (saturated colours vibrate on dark backgrounds)
- Elevation = lighter surfaces (opposite of light mode shadows)
- Background hierarchy: darkest furthest back, lighter surfaces forward
- Text: off-white, never pure white
- Borders: semi-transparent white `rgba(255,255,255,0.1)`, not solid grays

---

## Surface Textures

### Dot Grid

A subtle dot grid pattern that adds visual texture to large, otherwise flat surfaces. Defined as CSS utility classes using CSS variables from `:root`.

| Class | Dot gap | Opacity | Use |
|-------|---------|---------|-----|
| `dot-grid` | 24px | 18% | Default — main content areas, empty states, large canvas backgrounds |
| `dot-grid-dense` | 16px | 18% | Smaller panels where 24px feels sparse |
| `dot-grid-faded` | 24px | 10% | Areas with more content where the default is too prominent |

**When to use:**
- Main content scroll areas on desktop where the background is visually expansive
- Empty states — the grid gives the surface structure even when there's no content
- Behind modal overlays as the page backdrop

**When NOT to use:**
- Sidebar, topbar, or detail panels — these are UI chrome, not canvas
- Card interiors — cards are foreground surfaces and should remain solid
- Mobile — at narrow widths the grid adds noise without benefit
- On top of other patterns (glassmorphism, gradients) — one texture per surface

---

## Animation and Motion

Motion communicates — it is not decoration. Every animation must answer: where did this come from, what changed, did my action work, or what should I look at?

### Timing
- Micro-interactions (button, toggle): 100–150ms
- Tooltips, popovers: 150–200ms
- Panels, expands: 200–300ms
- Modals: 250–300ms enter, 200ms exit
- Closing is always faster than opening

### Easing
- **Ease-out** for entering elements (fast start, gentle landing)
- **Ease-in** for leaving elements (slow start, fast exit)
- **Ease-in-out** for repositioning
- NEVER linear easing except for progress bars and shimmer loops

### Performance
- Animate ONLY `transform` and `opacity` (GPU-accelerated)
- Never animate `width`, `height`, `top`, `left` (causes layout reflow)
- Respect `prefers-reduced-motion: reduce`

### Polish Techniques

These details separate good from great:
- **Staggered animations:** multiple elements appear with 50–80ms stagger
- **Coloured shadows:** tint shadows with the element's background colour
- **Border light effect:** dark themes + 1px `rgba(255,255,255,0.06)` border
- **Micro-gradients on buttons:** top 2% lighter, bottom 2% darker
- **Backdrop blur:** `backdrop-filter: blur(12px)` on sticky nav bars
- **Inner shadows for inputs:** `inset` shadows create a recessed feel
- **Nested border-radius:** children always have smaller radius than parent
- **Consistent icon style:** same stroke weight, corner radius, optical size

---

## Shared Component Primitives

Before writing inline styles for a button, input, card, modal, or badge — check the shared UI components directory. If the component exists, use it. If it doesn't exist yet, create it there. Never inline-style common UI patterns on a screen.

## Icons

All SVG icons live in a shared icons module as named exports. Never define an inline `<svg>` on a screen or component — add it to the icons file and import it.

Icons must share consistent stroke weight (1.5px or 2px), corner treatment, and optical size across the entire set.

## CSS Variables — For Pseudo-Elements Only

When utility classes cannot reach a style (scrollbar tracks, `::before`/`::after`, SVG strokes), use CSS variables defined in your stylesheet referencing brand tokens. Never use literal hex values.

---

## Accessibility — WCAG 2.2

- **Semantic HTML**: `<nav>`, `<main>`, `<section>`, `<header>`, `<footer>` — not div-soup. Every screen should have at least one landmark element.
- **Alt text**: Every `<img>` gets meaningful alt text. Decorative images use `alt=""`.
- **Keyboard navigation**: All interactive elements reachable via Tab. Modals close on Escape. Tab order must be logical.
- **ARIA labels**: Icon-only buttons and controls without visible text need `aria-label`.
- **Visible focus indicators**: Never suppress `outline` without a replacement.
- **Colour contrast**: Token system handles most cases. Verify opacity/overlay combos meet WCAG AA (4.5:1 text, 3:1 large text, 3:1 UI components).
- **Touch targets**: Minimum 44x44px, comfortable at 48x48px. Space between targets: at least 8px.
- **Reduced motion**: Respect `prefers-reduced-motion` — remove non-essential animation.
- **Colour independence**: Never use colour alone to convey meaning — pair with icon, text, pattern, or position.

---

## Never

- **NEVER** use hardcoded hex values — everything through token classes or CSS variables
- **NEVER** use arbitrary CSS framework values — they bypass the token layer
- **NEVER** use random spacing values — everything on the 8pt grid
- **NEVER** use internal spacing greater than external spacing on components
- **NEVER** animate `width`, `height`, `top`, `left` — use `transform` only
- **NEVER** use linear easing except for progress bars and shimmer loops
- **NEVER** make border-radius on children larger than their parent
- **NEVER** skip dark mode consideration — build it in, not bolt it on
- **NEVER** inline SVGs on screens — add to the icons library and import

---

## Reviewer Checklist

When reviewing frontend tasks, check every item below. A single violation is a **High** severity finding unless noted otherwise.

| Check | How | Severity |
|-------|-----|----------|
| No hardcoded hex | Grep for `#[0-9a-fA-F]{3,6}` in frontend files | High |
| Shared primitives used | Buttons/inputs/cards from shared UI components | High |
| Icons from library | No inline `<svg>` on screens | Medium |
| Font tokens used | Font token classes — no inline `fontFamily` | High |
| CSS vars for pseudo-elements | `var(--color-*)`, not literal hex | High |
| Spacing on 8pt grid | No arbitrary pixel values outside the scale | Medium |
| Internal <= external spacing | Component padding does not exceed gap between components | Medium |
| Button/input height parity | Buttons and inputs share the same height in the same context | Medium |
| Semantic HTML | Screens use landmark elements | Medium |
| Alt text | Every `<img>` has meaningful alt | Medium |
| Keyboard nav | All interactive elements operable via keyboard; focus trap = High | High |
| ARIA labels | Icon-only buttons have `aria-label` | Medium |
| Focus indicators | Visible on `:focus-visible` | Medium |
| Colour contrast | Custom opacity/overlay meets WCAG AA | Medium |
| Touch targets | Interactive elements at least 44x44px on mobile | Medium |
| Reduced motion | Animations respect `prefers-reduced-motion` | Medium |
| Animation performance | Only `transform` and `opacity` animated | Medium |

---

## Attribution

Visual design craft sections adapted from [ui-designer skill](https://github.com/anthropics/claude-code).
