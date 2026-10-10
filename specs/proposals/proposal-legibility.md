---
proposal: proposal-legibility
status: under-decision   # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-10-10
related: []
---

# Proposals a newcomer can decide from

*This file is written in the template it proposes (Appendix A, at the end), as a test of that template.*

## In brief

**So what.** A proposal is an agent's case for a change, written before anything is built. Proposal pages are hard to decide from unless you were in the conversation that made them. They open on how the change works, leave terms undefined, and show hand-drawn app screens. This gives every proposal an opening a newcomer can decide from in two minutes, and makes app screens real screenshots of today's app and of the built change.

**What you get.** Every proposal, file and page, in this order:

```
Title + status
In brief         so what · what you get · what changes · what we need
Settled already  each question beside its answer
Why
Options
Recommendation
  └ Visuals      Captured / Spike capture / Sketch
Not doing
Open decisions
Breakdown · Risks
For the builder  folded away on the page
```

**What changes.**

| Today | After |
|---|---|
| Opens on the problem, written for insiders | Opens with so what, what changes, what we need |
| Answers appear without their questions | Each answer sits beside its question |
| Hand-drawn app screens | The built change, screenshotted, shown first in the brief |
| No check that a newcomer can follow it | A fresh agent must state its point from the page alone |

**What we need from you.** Approve as written. The operator has answered four questions, listed under *Settled already*: an agent checks each page reads clearly first; where the app can't be screenshotted, the screens are taken before any screen work starts; the "after" screen is built for real and screenshotted, never drawn; and a visual change shows those screens here, in the brief.

## Settled already

| Question | Answer | Who, when |
|---|---|---|
| Is there a standard template for the proposal file? | Yes: `templates/proposal.md`. There is no template for the page. `/propose` asks for "a shareable rendering" and says nothing about what goes on it. | Found in the tree by this run, 10 Oct |
| Does the page open with a summary? | Yes. It opens with an executive summary that gives the "so what" of the change. | Operator, in the request, 10 Oct |
| What may an app screen show? | Only today's app plus the proposed change. Nothing guessed or restyled. | Operator, in the request, 10 Oct |
| How is the template tested? | This proposal is written in it, file and page both. | Operator, in the request, 10 Oct |
| Does the cold-read check run on every proposal? | Yes. | Operator, 10 Oct |
| What does a run do on a host that can't capture a screen the proposal changes? | It drafts everything it can. Then either it hands off to a session that can capture, or, once accepted, the first ticket is held for the operator to capture and lock in the screens before any screen work starts. | Operator, 10 Oct |
| For a visual change, what does the brief show? | The target state: screens of the recommended change, in the brief itself, so the reader sees what they are getting. Options, alternatives and analysis follow further down. | Operator, 10 Oct |
| How is the "after" screen made? | The way Calibrate does it: the change is built on a throwaway branch from the app's own components, and that branch and today's app are screenshotted the same way. The operator's answer was "edit the capture (whatever Calibrate currently does)", and Calibrate builds rather than edits, so building is recorded. | Operator, 10 Oct; reading confirmed against Calibrate's *Screen Hierarchy Captures* page |

## Why

The person deciding is often not the person who asked. A team member, Barry, reports that proposal pages confuse him: they carry a lot of filler, and they often assume the reader was in the conversation. Three published pages show the pattern.

- **The page opens on the mechanism.** *Takt Landing Windows* (7 Oct) opens by saying it will run the unattended loop on a fixed cadence and give each tick, and the operator, its own window on the integration branch. That sentence gives no effect. The effect only appears in the Problem section: in 16 days, landings on the shared branch fell within 30 minutes of each other 93 times, and when the branch moves under a run, that run re-runs a 20–25 minute test suite.
- **Terms go undefined.** The same page uses *takt*, *pitch*, *parked*, *attended reserve*, *P0, P2* and *CAL-2129* without explaining any of them. They are quoted here as the example, and none of them matters to this decision.
- **Answers appear without their questions.** *Screen Hierarchy Revamp* (6 Oct) has a "Decided" panel that begins "Your answers of 6 Oct are built into the mocks below". It then lists twelve answers, including "Coffee hero before any brews: *empty*", to questions the page never shows.
- **Agent-facing detail comes first.** *ticket-granularity.md* opens its body with a *Grounding* section of file and line citations, ahead of the problem. That material is for the builder. The decider has to read through it to reach the problem.

The template doesn't prevent any of this. Its only summary is one sentence, "what is being proposed and why it is worth a decision", and every section after it is written for the agents who will file and build the work. The page is a free restyle of the file, so its quality depends on the session that made it.

**App screens are redrawn instead of captured.** *Screen Hierarchy Revamp* draws nine phone screens in hand-written HTML and CSS. Its source labels the coffee artwork as "art stand-ins" and a country map as an "approximate outline … for the mock only". The same day, a separate page, *Screen Hierarchy Captures*, built those screens on a throwaway branch from the app's own components and screenshotted them beside today's screens on the iOS simulator: about 60 images. It lists what the hand-drawn version got wrong. The mock invented fields a brewer doesn't record ("Brand, Model, Material"), drew a chip selection style the app's chip doesn't have, and couldn't show that the Passport toggle snaps instead of sliding. Calibrate, the coffee app those screens belong to, has twelve `.mockup.html` files in `specs/proposals/`. It also already has two documented ways to screenshot its own app, both in its `design/AGENTS.md` → *Visual evidence*. **Route A** uses Expo Web and Playwright and runs on any host, including a cloud container. **Route B** uses the iOS simulator and needs a Mac. Calibrate's rules point only builds at them. The captures page was one session's own initiative, and no rule asks a proposal for it. Route A doesn't render the iOS 26 glass material or native tab bars, so a cloud session can capture most screens but not chrome changes. This is the case the operator raised: launching on a Mac avoids it, but only if the run says early that it needs one.

If nothing changes, every decision costs a second round: the reader asks what the page meant, or decides against a screen that isn't the app.

## Options

**For the page's structure**

- **A. A writing rule only.** Add "write for a reader who was not there" to the prose guidance. This costs a paragraph. `authoring` → `references/prose.md` already bans filler and the pages above were still written, so instruction alone is the approach that is failing.
- **B. One template with a reader's opening, plus a page contract** *(recommended)*. The proposal file opens with *In brief* and *Settled already*, and builder material moves to the end. The page renders the file's sections in the same order and adds nothing the file doesn't say. A cold-read check runs before hand-over. This costs three new sections and one step in `/propose`. It replaces the one-line summary, and only one document exists.
- **C. Two documents: a reader's brief and the agents' spec.** Each could be written for its own reader, but two copies drift. That is the second copy the repo's waste principle refuses.
- **D. A shipped HTML page skeleton.** Every page would look the same. But a page showing app screens should look like the app, as Calibrate's pages deliberately do. The host already supplies page design guidance, and an HTML file would need upkeep against host changes. The structure is the part that confuses readers, not the styling.

**For app screens**

- **V1. Capture first, label everything** *(recommended)*. A screen that exists is shown from a capture taken by the repo's own screenshot route. The "after" is the change built on a throwaway branch and captured the same way. Every screen carries one of three labels: *Captured*, *Spike capture* or *Sketch, not the app*. A host that can't capture says so at the start of the run.
- **V2. No screens in proposals.** This removes guessed screens, and also removes what a picture is for.
- **V3. UI proposals must run on a Mac.** This is the operator's choice per session and the harness can't enforce it. Route A covers most screens from the cloud anyway.

## Recommendation

**B and V1.** Both put the fix in the template and the command, which every proposal passes through, instead of in a rule that a session has to remember. The template's full text is in Appendix A. The parts that change:

1. **In brief** (250 words at most, table included; images don't count) is the first section of the file and the top of the page. It has three labelled parts: *So what*, *What changes* (a before-and-after table, as seen by the person affected) and *What we need from you* (the decision asked, the options and the recommendation). A proposal that changes what someone sees adds a fourth, *What you get*, straight after *So what*: the target-state screens of the recommended change. Its words must make sense to someone new to the subject, with no term that needs looking up, and no ticket number, principle number or file path doing work that a plain phrase could do.
2. **Settled already** lists each question answered while the proposal was drafted, as question, answer and who and when. A reader who missed the exchange sees both halves.
3. **Visuals** is required when the proposal changes something a user sees. It is governed by V1 and holds what the brief has no room for: before-and-after pairs, each alternative's screens, and the analysis behind them.
4. **For the builder** sits at the end and holds the grounding: anchors, file paths, ticket numbers and tree facts. The decider may skip it, and the agents who file the tickets start there.
5. **The page contract.** The page renders the file's sections in the file's order and adds nothing the file doesn't say. *In brief*, with its target-state screens, sits above the fold. *For the builder* is collapsed or left as a link to the file. Before hand-over, the author gives a fresh agent the page and nothing else, and asks it for the so-what, the change and the decision asked. If the answer differs from the brief, the author fixes the page.

**For screens:** a screen that exists starts from a capture taken through the repo's own visual-evidence route. That route is the *Visual evidence* section of the repo's `.claude/rules/design-system.md`, which the harness seeds. The "after" is the change built on a throwaway branch from the app's own components and captured through the same route, as Calibrate did for *Screen Hierarchy Captures*. The branch is never merged. Each capture names the commit or bundle it came from. A sketch is labelled *Sketch, not the app* and never stands in for a screen that exists.

`/propose` checks at the start whether the proposal touches a user-facing surface and whether this host can take the capture it needs. If it can't, the run says so before drafting and drafts everything it can, with *Capture owed: {screen}, needs {route}* where each screen would be. Then one of two things happens. The run hands off to a session that can capture, naming the screens and the route. Or, if the proposal is accepted with captures still owed, `/propose` step 4 files a first ticket held for the operator (the `operator` hold) to capture and lock in the screens, and every ticket that changes a screen depends on it.

### Visuals

The first visual compares an opening as published with the same opening rewritten in the proposed style. Every fact in the rewrite comes from the original page, which shows the rule changes the order of information and adds nothing.

| | Opening text |
|---|---|
| *Captured: copied from* Takt Landing Windows*, published 7 Oct* | "Run the unattended loop on a fixed cadence and give each tick, and the operator, its own window on the integration branch, so that two or more runners can work one queue without landing over each other." |
| *Rewritten in the proposed* So what *style* | In 16 days, automated runs and the operator's sessions landed on the shared branch within 30 minutes of each other 93 times, and when the branch moves under a run, that run re-runs a 20–25 minute test suite. A second automated runner is planned, which adds to this. The change gives each runner, and the operator, its own time slot to land in. Repos that don't opt in see no change. |

*In brief* shows the target order under *What you get*. The second visual compares it with today. It is a diagram, not a screen, so it needs no provenance label:

```
Today                              After
─────                              ─────
Title + one-sentence summary       Title + status
Problem                            In brief  (so what · what you get · what changes · what we need)
Options                            Settled already  (question → answer)
Recommendation                     Why
Not doing                          Options
Open decisions                     Recommendation
Breakdown                            └ Visuals  (Captured / Spike capture / Sketch)
Risks                              Not doing
                                   Open decisions  (options + recommended answer)
(page: any order the session       Breakdown · Risks
 chose)                            For the builder  (collapsed on the page)
                                   (page: same order as the file)
```

## Not doing

- **Rewriting existing proposals in the new shape.** They are decided records. Reopen a proposal if it returns for a decision.
- **A shipped HTML page skeleton** (option D). Reopen if pages from different sessions vary enough that a reader reports finding their way around each one as a cost.
- **A hook or test that checks the template's sections.** It would be a guard over what prose says, which ADR 0017 D5 retired. Never.
- **A separate brief document** (option C). Two copies drift. Reopen if one shape can't serve both readers after five proposals.
- **Requiring a Mac for UI proposals** (option V3). Where a session runs is the operator's call. The run only has to say early that it needs a Mac.
- **A screenshot tool in the harness.** Each repo owns its capture route, as Calibrate does. Reopen if two consuming repos end up building the same one.

## Open decisions

None. The three that were open were answered on 10 Oct and are listed under *Settled already*.

## Breakdown

1. **Proposal template and page contract.** Add *In brief*, *Settled already*, *Visuals*, *For the builder* and the page contract to `templates/proposal.md`. Bring `authoring` → *Proposal spec*'s section list into line with it. In `/propose`, step 3 renders by the contract and runs the cold-read check. · `assurance:simple` · separable
2. **Screens from captures.** In `/propose`, step 1 checks whether the proposal touches a user-facing surface and whether this host can capture it. Step 3 hands off when it can't, and step 4 files the operator-held capture ticket first when captures are still owed at acceptance. The template's *Visuals* section gets the spike-capture and provenance rules. · `assurance:simple` · sequential with 1: the same files, done by one builder in one sitting, so both items file as one ticket

## Risks

- **A short brief can hide a caveat.** A decider who reads only the top may miss a risk that would change the answer. Mitigation: *What we need from you* names any risk that bears on the decision asked.
- **The cold read shares the author's vocabulary.** An agent can pass a page that a person still finds unclear. The real test is a person. Barry reading this page cold is the acceptance check for the shape.
- **A spike spends build time before the decision.** Building the screens on a throwaway branch costs part of a build run for a proposal that may be rejected. Calibrate paid that once and found five things the hand-drawn version got wrong, one of them invented fields. On a cold host, Route A also installs Playwright and a browser on first use.
- **The word budget is measured from one example.** This proposal's first brief was about 305 words and came down to 193 without losing a decision; with *What you get* added it is 212. An earlier version of this file reported 410 and 294 and raised the budget to 300. That count had also caught the template's own brief in Appendix A, so the budget is back at 250. Revisit it after five proposals.
- **The template grows.** It gains four sections and loses the one-line summary. Each new section answers a failure shown above, and *Settled already* is omitted when nothing was settled.

## For the builder

Read these before amending the template. Every anchor was read on 10 Oct 2026 against `540b6367` on `dev`.

- `templates/proposal.md`: the sections today are the one-sentence blockquote, *Problem / motivation*, *Options*, *Recommendation*, *Not doing*, *Open decisions*, *Breakdown* and *Risks / unknowns*, followed by the lifecycle footer. The footer stays unchanged.
- `skills/authoring/SKILL.md` → *Proposal spec*: its first paragraph restates the template's section list. Update it in the same change, or the two disagree.
- `skills/propose/SKILL.md` → step 3, *Hand it over*: it asks for "a shareable rendering" and sets no structure. Step 1, *Scaffold*, is where the host-capability check belongs.
- `CLAUDE.md` → *Proposal renderings*: this names the Artifact as the page on Claude Code. It stays valid and needs no edit.
- `templates/rules/design-system.md` → *Visual evidence, when the diff touches a user-facing surface*: this is the capture route `/propose` refers to. It must not name `/propose`, because the repo principle is that a producer names no consumer.
- Calibrate `design/AGENTS.md` → *Visual evidence*: Route A (Expo Web, any host) and Route B (iOS simulator, Mac). This is the consumer's own route, and the harness ships nothing for it.
- The plugin version moves per `/build` step 7.

---

## Appendix A: the proposed template

This replaces `templates/proposal.md` above its lifecycle footer. The footer is kept unchanged.

````markdown
---
proposal: {short-slug}
status: draft            # draft | under-decision | accepted | shipped | rejected | split | superseded
date: YYYY-MM-DD
related: []
---

# {Title: the outcome in plain words}

## In brief

For a reader who was not in the conversation that produced this and has two minutes. 250 words at most, table included. No term that needs looking up, and no ticket number, principle number or file path doing work that a plain phrase could do.

**So what.** Two or three sentences: what changes, for whom, and why now.

**What you get.** Only when the proposal changes something a user sees: the target-state screens of the recommended change, labelled as under *Visuals*. Images don't count toward the word budget.

**What changes.**

| Today | After |
|---|---|
| {what the affected person sees or does now} | {what they see or do after} |

**What we need from you.** The decision this page asks for, its options and the recommended answer. Name any risk that bears on it. If nothing is open: approve as written.

## Settled already

Each question answered while this was drafted. Omit the section when there are none.

| Question | Answer | Who, when |
|---|---|---|

## Why

The problem and its evidence, inline: the number, the short quote, the example. Do not give a pointer the reader has to follow. Say what it costs if nothing changes. Define each term where it first appears.

## Options

Real alternatives, each with its trade-offs. Mark the recommended one.

## Recommendation

The direction, and why it beats the others.

### Visuals

Required when the proposal changes something a user sees, and omitted otherwise. The recommended target state already sits in *In brief*; this section holds the before-and-after pairs, each alternative's screens and the analysis. A screen that exists starts from a capture taken through the repo's visual-evidence route, at a named commit. The "after" is the change built on a throwaway branch and captured the same way. Label every screen: *Captured*, *Spike capture* or *Sketch, not the app*. Where this host cannot capture a screen, write *Capture owed: {screen}, needs {route}* in its place, and hand off or file the operator capture ticket first. Diagrams and charts are not screens and need no label.

## Not doing

- {capability}: {why it is out}. Reopen if {trigger}.

## Open decisions

| Decision | Options | Recommended | Who decides |
|---|---|---|---|

## Breakdown

1. {change}: {scope} · `assurance:{level}` · {separable | sequential with N}

## Risks

## For the builder

Grounding for the agents who file and build this: anchors by identifier, file paths, ticket numbers, tree facts, each read against a named commit. The decider may skip this section.
````

**The page contract**, which goes in `/propose` step 3:

> The page renders the file's sections in the file's order and adds nothing the file doesn't say. *In brief*, with its target-state screens, sits above the fold, and *For the builder* is collapsed or left as a link to the file. Before hand-over, give a fresh agent the page and nothing else, and ask it for the so-what, what changes and the decision asked. If its answer differs from *In brief*, fix the page.

---

**Lifecycle.** Unchanged from `templates/proposal.md`.
