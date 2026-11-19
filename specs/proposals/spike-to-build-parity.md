---
proposal: spike-to-build-parity
status: accepted         # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-11-19
related: [proposal-legibility]
---

# Build screens from the proposal's prototype, and name every place the build differs from it

## In brief

**So what.** In this harness, a *proposal* is the document where a change is decided before AI agents build it. For a screen change, someone builds a quick prototype on a separate code branch and screenshots it, so the decider sees the result. The prototype is then thrown away, the builder starts from scratch, and nothing checks the finished screen against those screenshots. A design worked over for several rounds can drift unnoticed.

**What changes.**

| Today | After |
|---|---|
| The prototype branch is discarded. | It is kept and named in the proposal, but never merged: its code is copied in file by file. |
| The building agent rebuilds each screen. | It writes tests, then copies in the prototype's code for that screen and makes it production quality. |
| The reviewing agent checks screenshots against the product's design rules. | It also compares them with the proposal's screenshots. Each visible difference needs a reason: accessibility, the product's shared styles and components, or a technical limit. An unexplained difference fails the review. |
| The builder screenshots changed screens. | Same count, matching the proposal's screens and states. |

**What we need from you.** Nothing more. The operator accepted option C on 2026-11-19, along with the recommended answers to the two smaller decisions. The options considered were C (both changes above), A (comparison only), B (prototype reuse only) and D (automated image comparison, which needs tooling the harness lacks). The risk accepted with C is that reviews may fail on trivial differences, so C limits "difference" to layout, content, hierarchy and states.

## Settled already

| Question | Answer | Who, when |
|---|---|---|
| Is the direction already decided, or should it be weighed first? | Weighed here first. This is why the change is a proposal rather than a ticket. | Operator, 2026-11-19 |
| If a proposal produces several screen tickets, which one inherits the prototype's code? | Each screen ticket takes the prototype's code for its own screen. The builder writes tests first, then brings that code in and makes it production quality. | Operator, 2026-11-19 |
| What is the built screen compared against, and how are accepted differences recorded? | It is compared against the proposal's prototype screenshots. Every difference is named as accessibility, design system or technical limit, and recorded in the as-built record, which is the reviewer's account of what shipped. A difference with no name fails the review. | Operator, 2026-11-19 |
| How does reusing the prototype's code fit test-first building? | The prototype counts as the probe: tests are written against its behaviour and shown failing without it, then its code is brought in and hardened. | Operator, 2026-11-19 |

| Which option? | C: keep the prototype, build from it, and compare against it. | Operator, 2026-11-19, accepting the proposal as written |
| A difference outside the three named reasons, such as a deliberate design change found during the build | Amend the proposal's *Visuals* first. No fourth reason. | Operator, 2026-11-19, as written |
| When is the prototype branch deleted? | When the proposal's tickets have all landed, by the umbrella close-out. | Operator, 2026-11-19, as written |
The rows on inheriting code and on test-first apply to options B and C. The row on comparison applies to A and C.

## Why

The operator reported the problem from use: what gets built drifts from what the proposal showed. Some drift is expected. Accessibility fixes, design-system tokens and technical limits all change a screen, and they should. The problem is drift nobody chose and nobody can see, and it matters most when the design went through several rounds before approval.

Two causes are visible in the guidance:

- **The prototype is discarded.** The proposal template says the prototype branch "is never merged". `/propose` calls it a throwaway branch in three places, one of them the screenshot ticket it files when screens are still owed. The builder rebuilds the screen from the app's components, which repeats work and adds a second chance to get it wrong.
- **Nothing compares the build with the proposal.** The build's screenshot step is in the repo's design-system rule. That rule judges each screenshot "against the reference or the applicable archetype". It never names the proposal's screenshots, and the reviewer has no duty to open them.

The practice already exists, but nothing in the guidance supports it. Calibrate is the main consuming repo with screens. 41 of its 196 proposals carry prototype screenshots. At least one, the achievements redesign, keeps its prototype pushed as `spike/achievements-prototype-20261114` and tells the builder "never merge. Lift from it", naming the files to take. The guidance says the opposite of that instruction, so it only works when whoever writes the proposal remembers to add it.

If nothing is done, every screen proposal pays for its prototype twice. Drift reaches the integration branch and is found by the operator rather than the review, which is the expensive place to find it.

How much drift actually happens is not measured. This proposal relies on the operator's report and on the guidance plainly having no comparison step.

## Options

**Option A: compare only.** The prototype stays throwaway. The builder screenshots the screens and states the proposal shows, and the reviewer compares the two sets, with every difference named. · Catches drift at review for almost nothing, because the builder already owes these screenshots. Still pays for the screen twice, and the rebuild creates drift that the review then has to push back on.

**Option B: reuse only.** The prototype branch is kept and named, and each screen ticket starts from its code for that screen. · Reduces drift where it starts and saves the rebuild. But hardening the code changes the screen (tokens replace hard-coded values, accessibility fixes move things), and nothing checks what those changes did.

**Option C: reuse and compare** *(recommended)*. Both A and B. · Reuse removes most drift before it happens. The comparison catches the rest and requires a reason for each difference. The review costs no more screenshots than A. Adds one review rule that can fail a build.

**Option D: automated before-and-after image comparison.** Every build captures before and after screens and compares them by image difference. · Catches the smallest drift, but costs a screenshot tool, a stable rendering setup and a threshold to tune. The harness owns no screenshot tool, and an earlier proposal kept one out until two consuming repos need it.

## Recommendation

**Option C.** It fixes both causes rather than one. It traces to *Build quality in*: the build ends on a pass/fail signal (each difference is named or it fails). It also traces to *Reduce waste*, because the prototype stops being built twice, which is rework the guidance currently requires.

Four rules make it work:

1. **The prototype branch is kept, pushed and named.** `/propose` pushes it as `spike/<proposal-slug>`, and the proposal's *Visuals* names the branch and the commit every screenshot came from. It is still never merged: it was cut from an older base and carries demo code. The builder takes the files for its screen from it.
2. **Each screen ticket starts from its slice of the prototype.** The builder reads the prototype's code for the screen and writes the tests against the behaviour it shows. They fail on the base, then the test lock is set (a hook that blocks test edits once implementation starts). Only after that does the builder copy the prototype's code in and make it production-ready. The prototype's code reaches the branch only after the lock, so the ordinary test-first build applies unchanged.
3. **The builder screenshots what the proposal showed.** For each screen the ticket changes, it takes the same screens, states and widths as the proposal's prototype screenshots. These count toward the screenshots the build already owes, within the existing 12-per-review limit. No new "before" screenshots are needed, because the proposal holds them. In its hand-off, the builder lists each difference with its reason.
4. **The reviewer compares and records.** The reviewer compares the two sets and checks each listed difference. A visible difference with no reason is a blocking finding. A reason outside the three categories means the proposal's *Visuals* must be amended before the build can pass, because the proposal binds what its tickets build. The reviewer writes the differences into the as-built record. "Difference" means layout, content, visual hierarchy or a state shown or missing. It does not mean anti-aliasing, a system font substitution, or a value the design system's token replaced exactly.

The parity rule applies only where the proposal's screenshot is labelled *Spike capture*, the template's label for a screenshot of the prototype. A *Captured* screen shows today's app and a *Sketch, not the app* is not the app, so neither has prototype code to reuse or a target to match.

The rules live in the plugin's own skills and templates: `/propose`, the proposal template, `/build` and the reviewer. The repo's design-system rule is left alone. Once hydration (the harness's setup step for a repo) seeds that rule, the consuming repo owns it and no later hydration overwrites it, so a change there would never reach Calibrate. The rule's "judge against the reference" already admits the proposal's screenshot as that reference.

## Not doing

- **Merging the prototype branch.** It is cut from an older base and carries demo-only code. Reopen if a prototype cut from the current base passes review unchanged.
- **Automated image comparison (option D).** This needs a screenshot tool, a stable renderer and a threshold, and the harness owns no screenshot tool. Reopen if reviews miss drift that the side-by-side screenshots plainly show, or if two consuming repos build the same comparison tool.
- **Editing the seeded design-system rule.** The consuming repo owns it once seeded, so the change would not reach existing repos. Reopen if a consuming repo reports that the rule's judging clause conflicts with the parity check.
- **New "before" screenshots at build time.** The proposal already holds today's screens. Reopen if a screen changed so much between proposal and build that its "before" no longer describes the base.
- **Parity for text-only diffs and fix-lane changes.** The existing text-only exemption stands, and the fix lane has no reviewer to compare. Reopen if drift is traced to a fix-lane change.

## Open decisions

None. All three were settled on acceptance and moved to *Settled already*.

## Breakdown

1. **Keep the prototype, build from it, and compare against it.** This covers the four rules above, across `/propose` steps 1, 2 and 4, the proposal template's *Visuals*, `/build`'s screenshot step and the umbrella close-out, and the reviewer's comparison and as-built entry. · shares none · orphans the "throwaway branch" wording in `/propose` and the proposal template, removed by this item · `assurance:complex` · separable

Filed on 2026-11-19 as [sluengen/harness#805](https://github.com/sluengen/harness/issues/805), in Todo at P2. It is filed flat, with no umbrella, because an umbrella groups several tickets and this breakdown has one.

This is one item. One builder in one worktree would make all of it in one sitting: every part edits the same contract, the *Visuals* record that `/propose` writes and `/build` and the reviewer read. Splitting it would make the second ticket wait on the first's wording. The lane is *feature* because it changes the contract between the proposal and build stages and adds a reason for a review to fail. The four-dimension test does not fire, because there is no data shape.

## Risks

- **Reviews fail on differences too small to matter.** Each failure costs a review round. Recommendation rule 4 limits what counts as a difference. If reviews still fail on trivia, tighten the definition. Do not drop the rule.
- **The prototype is stale by build time.** It was cut from an older base, and its code may not apply. The builder takes files rather than merging the branch, so a stale base costs adaptation rather than conflicts. Adapting the code can itself cause a difference, and the reviewer then sees that difference with its reason.
- **Demo code reaches production.** A prototype carries placeholder data and shortcuts, and Calibrate marks these `DEMO-THROWAWAY`. The tests are written before the code comes in, and the reviewer reads the diff as well as the screenshots, so placeholders face the same review as new code.
- **The prototype and the build are screenshotted on different setups.** Device, theme or data can differ. The proposal already names the device and data it used, and the builder matches them. Where the builder's host cannot match them, it says so and the comparison covers what it could take.
- **Calibrate has improvised this already.** Proposals written before this change say "never merged" and may name no branch. Their tickets get only the comparison, where prototype screenshots exist, and skip reuse.
- **The drift has not been measured.** If the comparison finds almost nothing over the first five screen tickets, rule 4 is a review cost without a return, and the rule should be retired.

## For the builder

Read against harness `963bea5a` (2026-11-15) and Calibrate `origin/dev` as fetched on 2026-11-19.

- `templates/proposal.md` → `### Visuals`: "that branch is never merged, and each capture names the commit or bundle it came from". This is where the branch name and commit become required, and where "throwaway" goes.
- `skills/propose/SKILL.md`: step 1 ("the change built on a throwaway branch"), step 2's *Recommendation* bullet, step 4's *Capture owed* bullet ("capture today's screens and the change built on a throwaway branch"). The `.claude/skills` directory is a symlink to `skills/`, so there is one copy.
- `skills/build/SKILL.md` → `## 2. Build`, the bullet beginning "Run the evidence each criterion names". It defers the visual work to the repo's `.claude/rules/design-system.md`. The parity set and the hand-off's list of differences go here, beside that delegation rather than inside the rule. The umbrella close-out audit (the `/build` path for an umbrella ticket) is where the branch deletion goes, if the operator accepts that row.
- Test-first: rule 2 needs no special path. The prototype's code enters the branch after the lock, so the ordinary *Tests first, checks, then lock* bullet holds. The *When the expected values can only be measured* path is for values that exist only once the change runs, and does not apply here.
- `templates/rules/design-system.md` and `skills/design-system/assets/AGENTS.md`: their *Visual evidence* sections are identical (both read "Judge each capture against the reference or the applicable archetype"). Leave both alone. `skills/hydrate/SKILL.md` step 5: "A rule is repo-owned once seeded, and a later hydration never overwrites it."
- `agents/reviewer.md`: "Screenshots support code reading and never replace it". The comparison duty and the as-built entry go into `review-discipline`, which the reviewer already loads for its obligations. `templates/feature.md` has no section for screen differences. The likely home is *Known limitations* or the behaviour scenario for the screen, and the design stage decides which.
- Calibrate evidence: its proposal `achievements-redesign`, in Calibrate's own proposals directory (status accepted). Its *Visuals* takes every screenshot "at commit `4da19abe7` of `spike/achievements-prototype-20261114`", and its builder section says "never merge. Lift from it" with four named files. The branch is on `origin` and carries one commit that is not on `origin/dev`. 41 of 196 proposals in `specs/proposals/` contain "Spike capture". Only 2 contain "Lift from it".
- Version: brief the reviewer with the case for both levels, and do not decide it here. For *major*: a review that used to pass can now fail on an unnamed difference. For *minor*: the new failure applies only to tickets built from a proposal with *Spike capture* screens, and a build that drifted was already open to a failure on its screenshots.
- Origin: `specs/proposals/proposal-legibility.md` → *Settled already*, the row "How is the 'after' screen made?", is where "throwaway branch" was adopted, copied from Calibrate's practice at the time.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as tracker issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.

**`under-decision`** sits between `draft` and those three. A proposal is `draft` while it is worked and clarified, `under-decision` once it is handed over complete for a decision, and `accepted`, `rejected` or `split` only on an explicit act against it as written. An answered question is not that act: answers change what the proposal says, not what state it is in, so a run that asked four questions and got four replies still holds an `under-decision` proposal and has spawned nothing.

Two further states apply *after* the decision rather than instead of it: **shipped**, once the change specs it spawned have landed, and **superseded**, when the machinery it describes is retired — whether it was built first or not. Advance the status and amend the file **in place**, with a dated banner naming the record that superseded it; never move or delete it, so links stay stable and the audit keeps the reasoning. An `accepted` proposal is a standing instruction to build, so leaving one accepted after its subject died is how a later ticket inherits instructions targeting deleted code.
