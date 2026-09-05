# Visual evidence for a user-facing change

Load this when the diff touches a user-facing surface.

> Interim home. T4 moves these bytes into the repo-owned design-system rule
> (`templates/rules/design-system.md`) so they load whenever a UI file is
> opened, and deletes this file. Move them; do not copy them.

**When.** Any diff touching a user-facing surface — a screen, route, view, template, or the styles behind one. Not a judgment call about size or risk.

**Render.** Before handoff, render the changed surface with **realistic seeded state** — synthetic throughout, never production data. Capture at the repo's reference widths, at least one mid-width, and both sides of every breakpoint the change touches.

**How.** Fixed viewport, **viewport-height slices** scrolled one viewport at a time, numbered in scroll order. Never a full-page capture at any width, and no capture over 2000 px tall — a taller capture arrives at the reviewer downscaled past legibility (measured: 16 px body text at 7 of 8 characters from a 5726 px capture).

**Where.** Captures and their manifest land in `.evidence/<TICKET-ID>/` at the worktree root — git-ignored, so evidence never reaches the committed tree through `git add -A`. If the repo's `.gitignore` does not ignore `.evidence/`, add that line before capturing. Name captures `<page>-<state>-<width>w-<slice>.png`, the manifest `manifest.md`.

**How many.** At most 12 captures per review. Narrow the set to the states carrying the change; never shrink images to fit — that reintroduces the failure the slice rule prevents.

**Judge.** Compare each capture against the reference or applicable archetype and `ux-design` principles; inspect the implementation too — screenshots do not replace code review. Fix, re-render, retain only the final evidence. Revert seeded data and capture-only code before verification.
