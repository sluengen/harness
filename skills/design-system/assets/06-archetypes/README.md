---
layer: 06-archetypes
kind: readme
status: scaffold
last_updated: 2026-07-29
---

# 06 · Archetypes

Page-level chrome contracts — the regions a kind of page owns, and how each
behaves across widths.

An archetype names the regions a *kind* of page owns — its shell, its
breakpoints, its section ordering, where a title and its actions sit — and
what each of those does as the viewport narrows. A screen then fills that
contract rather than redefining it, which is what keeps two pages of the same
kind from drifting apart one change at a time.

**Write the first one when a second page of the same kind appears.** Chrome
extracted from a single instance is a description of that instance: there is
nothing to contrast it against, so nothing in it can be told from an accident.
Until then the shell belongs in prose — layer 00 for what the surface may do,
layer 02 for density and interaction.

> Scaffold. An archetype documents a contract *shared by more than one page*.
> This layer fills in when this repo's surface has two.
