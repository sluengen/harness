<!-- guidance:bug@0.3.1 -->
# /bug — capture a bug straight to Todo

Usage: `/bug <description>`

A bug noticed in actual use has nowhere lightweight to land: `/propose`
decides the unconfirmed (a bug is not unconfirmed — something is broken and
should be fixed), and hand-filing a tracker issue is fiddly and trap-laden.
`/bug` is a thin capture command: it fills the shared
`templates/adjustment.md` with `kind: bug` and files it straight to Todo,
ready for `/start` to pick up. It is the inverse of `/propose` — `/propose`
decides, then files; `/bug` files the already-decided.

A bug has **no escape hatch**. The as-built behaviour already contradicts the
intent, so there is nothing to decide — the fix direction is "make it match."
(Contrast `/tweak`, whose "should we?" axis can escalate to `/propose`.)

## Steps

**Step 1 — gather the observed behaviour.** From the description (or by
asking, in one turn, if it is missing): what actually happens today, and a
repro — the steps or input that trigger it. Also capture what tipped you off
(what you were doing, what you expected instead) and the desired behaviour —
the outcome, not the implementation.

**Step 2 — fill the template.** Fill `templates/adjustment.md` with:
- `kind: bug`, `area: <surface/feature>`
- **As-built (observed)** — the wrong behaviour, plus the repro
- **Desired** — what should happen instead, one or two sentences
- **From actual use** — the situation that surfaced it
- **Acceptance criteria** — specific, testable outcomes

**Step 3 — file it.** Pass the title, the UTF-8 body file, and exactly one
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
