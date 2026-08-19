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
artifact: a single, self-contained landing page explaining what the plugin is,
how a repo adopts it, the gate, and the surface it installs. There is no app
behind it to theme, no tenant to re-skin, and no second screen.

## The rules this layer holds

1. **The page states what is, not what is aspirational.** It is a record of
   a process that runs today — the install path, the lifecycle, the gate, the
   surface — not a pitch. A claim the page can't back with something real (a
   command, a file, a test) doesn't belong on it.
   `tests/unit/test_landing_page_inventory.py` holds the inventory half of
   that rule mechanically: every command, skill, agent, and hook the page
   names must be a unit the tracked tree carries, and every unit the tree
   carries must be named. The rest of the page's prose is unguarded and rests
   on this rule alone (#482).

2. **One skin, no re-skinning mechanism.** Unlike a product this design
   system might otherwise serve, there is no branding resolver, no per-tenant
   override, and no build-time variant. The token substrate (layer 03) exists
   to give the page's existing palette names and structure, not to make it
   swappable.

3. **The palette carries meaning, not decoration.** Four hues, one per
   *domain* of the process, used consistently everywhere that domain appears:

   | Token family | Domain it marks | Where it appears |
   |---|---|---|
   | `--build` | the gate and its evidence | the gate panel, its stage list, the fast lane, the no-runtime card |
   | `--product` | the guidance surface | the spine card, the install steps, the commands and skills inventories, the ticket lane |
   | `--strategy` | roles and deciding | the agents inventory, the proposal lane, the builder-≠-recorder card |
   | `--quality` | enforcement and health | the hooks inventory, the refuses badge, the dogfood card |

   A new surface introducing a fifth "brand" hue unrelated to a domain is a
   finding. The token *names* are inherited from the retired Four Loops model
   this page presented before #482 and are deliberately not renamed — that is a
   token-source change, not a page change — so read each name as the label of
   the domain in this table, not of a loop.

4. **Self-contained is a brand constraint, not just a build detail.** The
   page must render standalone with no external resource requests. It is
   listed here too because it shapes what the brand *can* do: no web fonts,
   no CDN icons, no remote images — everything inline. This is currently a
   stated rule, not a mechanical one: the guard that pinned it went with the
   pre-v5 guard cull (ADR 0017 D5) and has not been re-established.

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
- [ ] A hue is used consistently for its domain everywhere it appears, per
      the table in rule 3.
- [ ] No new external resource request is introduced (fonts, scripts,
      images, iframes). Nothing enforces this — check it by reading the diff
      (rule 4).
- [ ] Every skill, agent, command and hook the page names carries its
      `data-unit` tag and resolves against the tracked tree
      (`tests/unit/test_landing_page_inventory.py`), and the surrounding
      counts were re-derived, not carried over.
