---
layer: 00-brand
kind: readme
status: active
owner: sluengen
last_updated: 2026-07-29
---

# 00 · Brand

Who the harness is: what it stands for, and the bounded set of visual
decisions this system governs.

**The harness is an evidence layer for agent-driven development** — a
deterministic verify gate and a versioned body of guidance an agent works
against while it drives a ticket end to end. It has no product UI and no
end-users; it is infrastructure other repos self-host. `docs/index.html` — the
page this design system captures — is the harness's **one** external-facing
artifact: a single, self-contained landing page explaining the operating model
(the Four Loops), the gate, and the guidance catalog. There is no app behind it to theme, no
tenant to re-skin, and no second screen.

## The rules this layer holds

1. **The page states what is, not what is aspirational.** It is a record of
   an operating model that runs today — the loop cadences, the verbs, the
   guidance — not a pitch. A claim the page can't back with something real
   (a command, a file, a test) doesn't belong on it (the precedent
   `tests/unit/test_landing_page.py` already enforces for two prior stale
   claims).

2. **One skin, no re-skinning mechanism.** Unlike a product this design
   system might otherwise serve, there is no branding resolver, no per-tenant
   override, and no build-time variant. The token substrate (layer 03) exists
   to give the page's existing palette names and structure, not to make it
   swappable.

3. **The palette carries meaning, not decoration.** Each loop (Build,
   Product, Quality, Strategy) owns one hue, used consistently everywhere
   that loop appears — the hero diagram's rings, the loop cards, the spec
   flow, the verb cards. A new surface introducing a fifth "brand" hue
   unrelated to a loop is a finding.

4. **Self-contained is a brand constraint, not just a build detail.** The
   page must render standalone with no external resource requests — pinned
   by `tests/unit/test_landing_page.py::test_no_external_resource_requests`
   and restated as a law in layer 02. It is listed here too because it
   shapes what the brand *can* do: no web fonts, no CDN icons, no remote
   images — everything inline.

## Where the detail lives

There is no separate `decisions/` folder yet for this layer — the palette's
values are captured as tokens in layer 03, and the rationale for each hue
(one per loop, chosen for contrast against the hero's dark gradient and for
mutual distinction) lives in the page's own prose and SVG rather than a
standalone brand decision record. A future brand decision (e.g. adding a
fifth surface, changing a loop's hue) should get its own file here rather
than be folded into a token-only change.

## Review checklist

Held against any change to `docs/index.html`:

- [ ] Every claim on the page is checkable against something real — a
      command, a file path, a test — not aspirational.
- [ ] A loop's hue is used consistently for that loop everywhere it appears.
- [ ] No new external resource request is introduced (fonts, scripts,
      images, iframes) — `test_no_external_resource_requests` must still
      pass.
- [ ] A named skill/agent/command resolves in `registry.yaml`
      (`test_named_guidance_resolves_in_registry`).
