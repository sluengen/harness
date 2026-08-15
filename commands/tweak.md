<!-- guidance:tweak@0.3.1 -->
# /tweak — capture a small upgrade, with an escape hatch to /propose

Usage: `/tweak <description>`

A small upgrade noticed in actual use has nowhere lightweight to land:
`/propose` decides the unconfirmed (a clear tweak is not unconfirmed — it is
a small, already-decided upgrade), and hand-filing a tracker issue is fiddly
and trap-laden. `/tweak` is a thin capture command: it fills the shared
`templates/adjustment.md` with `kind: tweak` and files it straight to Todo,
ready for `/start` to pick up. It is the inverse of `/propose` — `/propose`
decides, then files; `/tweak` files the already-decided.

Unlike `/bug`, a tweak carries a faint "should we?" — the as-built behaviour
is *correct*, being upgraded rather than corrected, so occasionally a tweak
is really a small proposal in disguise. That is the one axis `/tweak` checks
that `/bug` does not (`/bug` has no escape hatch: an as-built bug already
contradicts the intent, so there is nothing to decide).

## Steps

**Step 1 — gather the upgrade.** From the description (or by asking, in one
turn, if it is missing): the current, correct behaviour being upgraded (no
repro needed — nothing is broken), what tipped you off (what you were doing,
what you expected instead), and the desired behaviour — the outcome, not the
implementation.

**Step 2 — check the escape hatch.** If the tweak carries a real decision
(more than one reasonable direction) or would spawn more than one change, it
is not a tweak — stop here and point at `/propose` instead:

**Escape hatch (decided):** a clear tweak files straight to Todo; a tweak
that carries a real decision or spawns more than one change is not a tweak.
Stop and say so, then hand off:

```
This reads like more than one small upgrade — use /propose <idea> instead so
it can be decided and broken down.
```

No bespoke confirm gate otherwise — a clear tweak proceeds straight to Step 3.

**Step 3 — fill the template.** Fill `templates/adjustment.md` with:
- `kind: tweak`, `area: <surface/feature>`
- **As-built (observed)** — the current, correct behaviour being upgraded
- **Desired** — what should happen instead, one or two sentences
- **From actual use** — the situation that surfaced it
- **Acceptance criteria** — specific, testable outcomes

**Step 4 — file it.** Pass the title, the UTF-8 body file, and exactly one
assurance level — chosen per `spec-authoring` → *Choosing assurance*, never
restated here — to `tracker.create`, with any labels and mandatory initial Todo
placement. The
`tracker` skill reads `CONTEXT.md`, selects the configured provider, and owns
creation plus queue placement. If it reports a partial creation, surface the
identifier and URL and stop; never retry by creating a duplicate.

## Report

Print the filed ticket's identifier and URL, then:

```
Next: /start <TICKET>   (or /build <TICKET> to drive it unattended)
```
