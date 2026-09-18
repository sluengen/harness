---
layer: 00-brand
kind: readme
status: scaffold
last_updated: 2026-09-18
---

# 00 · Brand

Who this product is: what it stands for, and the bounded set of visual decisions
this system governs. **Write this tier first.** Every layer below it resolves an
ambiguity that only an answer here can settle, and a token palette chosen before
anyone has written down what the product is for is a palette nobody can argue
with.

Scaffold — this file states what belongs here and is otherwise empty.

## What to write

**One paragraph, in a sentence a designer or an agent can act on.** What the
product is, who it is for, and what its surface is: an app with many screens, a
single page, an embedded widget, a CLI with a web console. That last part bounds
everything else — a system for one self-contained page and a system for a
multi-tenant app disagree about almost every rule below.

Then the rules this layer holds. They are the constraints a reviewer can hold a
change to, not aspirations. The ones most systems need:

1. **What the surface may claim.** Whether copy is a record of what exists or a
   pitch, and what backs a claim when it is challenged.
2. **Whether the brand is swappable.** A per-tenant override, a build-time
   variant and a branding resolver are all mechanisms with a cost; a system that
   will never need one should say so, because the token layer is shaped
   differently in each case.
3. **What the palette means.** Give each hue a *domain* — a kind of thing it
   marks — and use it consistently wherever that domain appears. A hue
   introduced for decoration, unrelated to any domain, is then a finding rather
   than a matter of taste. Record the mapping as a table; layer 03 carries the
   values, this layer carries what they are *for*.
4. **What the surface may depend on.** External fonts, CDN icons, remote images,
   analytics: each is a brand constraint as much as a build detail, and a rule
   here is cheaper than discovering the answer per change.

## Where the detail lives

Palette values are tokens in layer 03 — this tier carries the rationale, not the
hex. A consequential brand decision (adding a surface, changing what a hue
means, dropping a constraint in rule 4) gets its own file in this directory
rather than being folded into a token-only change, so that the change which
alters the *meaning* is reviewable separately from the one that alters values.

## Review checklist

Held against any change to the product's surface:

- [ ] Every claim the surface makes is checkable against something real — a
      command, a file path, a test — to whatever standard rule 1 sets.
- [ ] A hue is used consistently for its domain everywhere it appears, per the
      table in rule 3.
- [ ] No dependency rule 4 forbids is introduced.
- [ ] Anything this system says it enforces mechanically still does, and the
      counts and inventories the surface prints were re-derived rather than
      carried over.
