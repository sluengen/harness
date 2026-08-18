---
proposal: visual-evidence-for-review
status: shipped
date: 2026-08-07
related: [specs/features/verb-model.md, specs/features/cli-surface.md, specs/proposals/review-probing.md]
---

# Proposal: rendered evidence as a first-class review input

***Shipped as #434 — with its placement reversed.** The channel exists, but not where this proposal put it. Change 2 of 2 placed the capture convention in the build step **and** in the `ux-design` skill; #434 reversed that to a single home in `commands/build.md` → *Visual evidence for a user-facing change*, leaving `ux-design` untouched. The reversal and its reasoning are recorded in `specs/features/guidance-system.md` → *Decision: The capture convention lands in `/build`, not in `ux-design`* — read that before treating anything below as the plan of record.*

> Give `review` a channel for screenshots the builder already captured, so a reviewer judging a user-facing surface can see it instead of inferring it from a class list.

## Problem / motivation

For a change to a user-facing surface, `review` is asked whether the result looks
right and structurally cannot look. The engine runs read-only with no browser, no
simulator, no display, and no network. It sees a diff.

That is not a hypothetical gap. In `nano-erp`, tickets ERP-186..195 shipped six
pages that satisfied every DOM assertion and rendered as a single column at every
width — the mobile arrangement at 1440px. The operator's words were that it looked
nothing like the mockups. Nothing in the loop had rendered the pages, so nothing in
the loop could have known. The remediation ticket ERP-225 then found a further
defect (a utility column collapsing two-up) that a rendered capture would have shown
immediately.

The builder *can* look. Today that evidence is discarded at handoff: the builder
renders, judges, fixes, and hands over a diff. Whatever was seen does not survive
into the record, and the reviewer starts blind. The cost of the status quo is that a
visual regression can only be caught by a human opening the app, which is the check
the loop exists to stop depending on.

The harness already solves this exact shape twice. `design` is produced by a separate
stage and passed into review as evidence, authenticated by `design_hash`, with
`design_context` recorded on the `review` event so "did the reviewer actually receive
it" is answerable later. The verification gate is the same pattern under a different
constraint: the verb cannot run the repo's toolchain, so the orchestrator runs it and
hands over `--gate-exit` / `--gate-log`, and the verb refuses to certify without them
(`no_gate_evidence`). Rendered evidence is the third member of that family and is the
one that is missing.

### What was measured before writing this

The proposal rests on the engine being able to see a PNG at all. That was spiked on
2026-08-07 rather than assumed.

Two images were placed in a workspace directory: one containing a random 8-character
token rendered as pixels with no hint in the filename, one containing four coloured
rectangles in a specific arrangement. The expected token was kept outside the mount so
nothing readable could leak it.

| Invocation | Token | Layout | Mechanism |
|---|---|---|---|
| `claude -p --permission-mode plan`, host | exact | correct | — |
| the same, inside `harness:dev` | exact | correct | `Read` returned `image` content blocks |
| `codex exec --sandbox read-only --ephemeral -`, host | exact | correct | shelled out to `magick` |

The container run is the one that matters, and its mechanism was traced with
`--output-format stream-json`: `Read` on the PNG returned a tool result of type
`image`. Plan mode permits the read and the model receives pixels. That is the
load-bearing assumption, confirmed in the real image under the real flags.

**Codex cannot see images.** It has no image-returning read tool; it reached the
answer only by running ImageMagick through its shell. `harness:dev` carries no
`magick`, `convert`, `identify`, `tesseract`, or PIL, and codex's sandbox does not
start in-container at all (ADR 0013, #314). Visual evidence is therefore a
claude-engine capability, and selecting codex silently removes the reviewer's ability
to see what it is being asked to judge. That interacts directly with #317 and #318,
which make the engine selectable per invocation.

## Options

**Option A — guidance only** · Require the builder to render, capture, compare, and
fix before handoff, and change no verb. · Cheapest, and it fixes the ERP-186..195
failure directly, because that failure was nobody looking rather than the reviewer
being blind. But the evidence still dies at handoff: the reviewer stays blind, no
record survives, and whether the builder actually looked is unfalsifiable. It also
puts the whole check on the party with the strongest incentive to accept its own work.

**Option B — an evidence channel plus the guidance** · Add `--screenshot-dir` to
`review`, reference the images by path in the prompt, record `visual_context` on the
`review` event, and require the build loop to produce and save the captures. · Mirrors
`--design-file` exactly, including the workspace-bounding check that already exists.
Costs one flag, one prompt section, one event field, and a manifest contract. Does not
make the evidence verifiable — a screenshot is a builder self-report, and the verb
cannot confirm it depicts the reviewed SHA.

**Option C — Option B plus a refusal** · Additionally refuse a review of a UI change
that arrives with no visual evidence, mirroring `no_gate_evidence`. · The strong form,
and the only one that makes the check load-bearing. But deciding "is this a UI change"
from changed paths is fragile, and a label is a human input the loop cannot verify. A
refusal that misfires on non-UI work is worse than the gap it closes.

## Recommendation

Choose **Option B**, and hold Option C until there are runs to decide it on.

B is the smallest change that closes the actual loop. The guidance half is what makes
someone look; the channel half is what stops the looking from being thrown away. Each
is weak without the other — guidance alone leaves no record, and a channel alone has
nothing to carry.

Option C is the right eventual destination, and it should not be designed away. But its
scoping question is genuinely unresolved, and the harness's own precedent argues for
sequencing: `no_gate_evidence` refuses on a signal the caller states explicitly, whereas
"this diff touches UI" would have to be inferred. Ship the channel, gather the evidence
of how often it is used and on what, then decide the refusal on that rather than on a
guess. This is the same staged shape `engine-activity-aware-timeouts` chose for its
thresholds, and for the same reason: set a policy after a local distribution exists.

The engine asymmetry is stated rather than papered over. Under `--engine codex` the
reviewer cannot see the images, so the verb must not silently accept them and imply it
did. The minimum is to record the degradation on the event; refusing the combination
outright is cleaner and is put to the operator below.

### Two details worth encoding in the guidance

**The reference width set needs a mid width.** ERP-225's protocol named 1440 / 834 /
390. The utility-column defect rendered correctly at 1440 and broke at 1280 and 1366 —
the two commonest laptop widths — because a container query crossed its threshold
between the named tiers. Three widths at the extremes cannot catch a threshold in the
middle. Add roughly 1280 as standard, and more generally capture at the widths
immediately either side of every breakpoint the change touches.

**Rendered evidence supplements analysis; it does not replace it.** A visual pass at
three widths on ERP-225 passed the utility-column defect, and reading the compiled CSS
caught it. If the guidance does not say this plainly it will license the inverse of the
failure it is fixing — a builder who captured screenshots and therefore stopped reading.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Ship the evidence channel and guidance now (Option B), deferring the `no_visual_evidence` refusal until runs exist to scope it. | user | this proposal |
| Under `--engine codex`, refuse a review that supplies screenshots, or accept it and record the degradation on the event. | user | accepted change spec; `verb-model.md` as-built record |
| Where the reference width set lives — a per-repo `CONTEXT.md` field, or left to each repo's own design guidance. | user | accepted change spec; `CONTEXT.md` |
| Whether the manifest is required for the channel to be accepted, or optional evidence the reviewer may use. | user | accepted change spec |

None of these is cross-cutting enough for an ADR. The engine asymmetry is the closest,
and it belongs in the engine-selection work (#317/#318) rather than in a standalone
decision record.

### Resolved 2026-08-07

The operator accepted **Option B**: ship the evidence channel and the guidance now, and
defer the `no_visual_evidence` refusal until there are runs to scope it on.

The operator also decided the codex case: **`review` refuses the combination of
`--engine codex` and supplied screenshots.** Codex has no image-returning read tool and
the verb image carries no ImageMagick, OCR, or PIL, so it cannot see them; accepting the
flags would produce a pass that reads as though the reviewer looked. The refusal is
honest and surfaces the constraint at the point of engine selection. It costs one
refusal reason and is carried into change 1 below.

The remaining two rows — where the reference width set lives, and whether the manifest is
required or optional — stay open and are resolved in the change specs.

## Breakdown

Accepted 2026-08-07; filed as **#361** and **#362**, both Todo.

1. **The visual-evidence channel on `review`** (#361) — accept `--screenshot-dir` (workspace-bounded
   through the existing `design_file_outside_workspace` check), reference the images by
   absolute path in the prompt rather than inlining them, define the manifest contract
   (page × width × reference frame, plus the deviations the builder is knowingly
   accepting), record `visual_context` on the `review` event alongside `design_context`,
   and handle the codex case per the decision above. Includes a measuring test that the
   engine received image content, not merely a path.
2. **The build-loop guidance for rendered evidence** (#362) — render with realistic seeded state,
   capture at the repo's reference widths and either side of every breakpoint touched,
   compare against the reference or the archetype's rules, fix and re-capture, and save
   the final captures into the workspace for handoff. Lands in the `/build` and
   `/harness run` implement step and in the `ux-design` skill, which is not gated on the
   `design_system` layer and so applies wherever there is a surface. States explicitly
   that captures supplement code reading.

Item 1 is shippable without item 2 and vice versa, but neither delivers the outcome
alone. Ship them adjacently.

## Risks / unknowns

- **The evidence is a self-report the verb cannot authenticate.** `design_hash` proves
  the design file was not swapped between stages; no equivalent proves a PNG depicts the
  reviewed SHA. The manifest should name the SHA it was captured at, but a builder who
  captures the wrong thing produces evidence that looks correct. This channel raises the
  floor; it does not close the hole, and the change spec must say so rather than imply
  authentication it does not have.
- **A manifest written by the builder is the builder's own account of what is
  deliberate.** Without it the reviewer cannot distinguish an intended deviation from an
  unnoticed one, which is why it is worth having — but it is also the field most likely
  to be filled in to match whatever shipped.
- **Token and latency cost.** Several full-page screenshots at several widths is a large
  input. Review already runs against a 720-second per-subprocess ceiling and, unattended,
  a 110-minute wall clock. The change spec needs a bound on how many images are passed,
  and a measuring test for the added duration rather than an assumption that it is small.
- **The capability is claude-only and could regress silently.** A future CLI change that
  stops returning image content blocks would degrade the reviewer to reading paths with
  no signal. The `visual_context` field is what makes that detectable after the fact; a
  test that asserts image content was received is what makes it detectable at build time.
- **Guidance that mandates capture invites capture as a substitute for reading.** The
  ERP-225 evidence is explicit that the visual pass missed a defect the code reading
  caught. If usage shows builders trading one for the other, the guidance is wrong and
  should be corrected rather than defended.
- **What would invalidate the recommendation:** if the spiked `Read`-returns-image
  behaviour does not hold for realistic full-page screenshots — large dimensions, heavy
  downscaling — the channel delivers much less than the spike suggests. The first change
  should re-run the spike against a real capture from a real repo before the flag is
  considered done.

---

**Lifecycle.** This proposal is under decision. If accepted, create its two tracker
issues; if rejected, retain this file as the decision record; if split, replace it with
smaller proposals.
