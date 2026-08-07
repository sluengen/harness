<!-- guidance:template-proposal@0.1.3 -->
---
proposal: review-probing
status: accepted
date: 2026-08-07
related: [specs/features/verb-model.md, specs/features/run-ledger.md, specs/proposals/engine-activity-aware-timeouts.md, specs/proposals/visual-evidence-for-review.md]
---

# Proposal: let the reviewer run an experiment, not only read a diff

> Give `review` execute against a throwaway tree at the reviewed SHA and a bounded budget for the experiments it may run, so a finding can move from argued to demonstrated — starting with the mutations the builder did not think of.

## Problem / motivation

The review engine can read the diff and reason about it. It cannot run anything, so it
can never move a finding from plausible to proven, and it cannot discover a defect that
only appears when the code executes.

Two runs supply the evidence, and they fail in the same direction.

In `nano-erp`, ERP-225 reached review with a green gate, a recorded design, and a
host-side visual pass. The verb timed out, the operator authorised an adversarial
sub-agent instead, and that sub-agent found three blocking defects that had survived the
gate and 803 tests. Two of the three required execution to establish: one depended on
React's commit semantics and only reproduces with two distinct component types, so a
first reproduction attempt using `rerender` passed; the other depended on the HTML
spec's queued `toggle` task, and the delivered tests asserted synchronously, before the
task ran. Neither is a distinction anyone gets right reliably by inspection. The third
was reachable by reading.

In this repo, a recent run's adversarial pass found two defects, and both were
experiments rather than inspections — the shape was *add `--ignore` to the gate and watch
twelve guards stay green*. No amount of reading finds that reliably; running it finds it
immediately.

There is a sharper version of the same gap, and it is the repo's own recorded lesson: a
mutation table certifies only what its author thought to mutate. #360's context section
records two concrete instances — an aggregate assertion in #207 that reported a kill it
never made, and four mutations in #336 that evaluated to the original value and printed
SURVIVED. The builder writes that table. Nobody proposes the mutations the builder did
not think of, because the only party positioned to do so cannot run anything.

Doing nothing keeps review at the ceiling of what careful reading achieves, on a repo
whose most expensive recurring defect class is a test that passes without exercising the
thing it claims to guard.

### What the environment actually permits today

Verified in the tree rather than recalled:

| Fact | Evidence |
|---|---|
| the claude engine runs read-only | `harness/cli/review_protocol.py:405` — `["claude", "-p", "--permission-mode", "plan"]` |
| the codex engine runs read-only | the same function — `codex exec --sandbox read-only --ephemeral -` |
| the verb container carries no target-repo toolchain | the image is Debian trixie; the gate is already refused for this stated reason |
| a verb-allocated, flagless write grant already exists | `harness/cli/design_protocol.py:399` — `design` grants edit on one absolute file outside the worktree (#294) |
| that grant is honestly scoped | the same docstring: an agent-layer control, not a filesystem boundary — the mount stays read-write |
| the reviewed tree is defended by two conjuncts | `harness/cli/close.py:335-358` — a dirty worktree is refused (`dirty_worktree`, exit 2) *and* the pass must bind to current HEAD |

The last row corrects a natural assumption. The HEAD binding is not what protects the
tree from a reviewer that can write: an uncommitted edit leaves HEAD unchanged and the
binding would not notice. What protects it is the separate clean-tree conjunct, which
refuses the close outright. So the failure mode of a misbehaving prober is a **wedged
run**, not a laundered merge — a much better property than the ask assumes, and one this
proposal must not weaken.

The design verb's grant is the important precedent. The primitive being asked for here
is not write access to the tree under review. It is a disposable place to work plus the
ability to execute, which is the same shape #294 already shipped one path of.

## Options

**Option A — a writable scratch mount plus execute in the container** · Mount a tmpfs at
`/scratch`, grant the engine write and execute there, keep the reviewed tree read-only. ·
Cheapest, and it preserves the SHA binding cleanly. But it does not solve the toolchain
problem: a frontend repo's probes need `node_modules`, and any on the host mount are the
wrong architecture for the Linux container. It buys probing only for repos whose
toolchain the image happens to carry, which is the situation the gate rationale
explicitly refuses to design for.

**Option B — a probe callback** · The engine emits structured probe requests alongside
its findings; the verb returns them to the orchestrating session, which executes them
host-side exactly as it already runs the gate, and feeds the results back for a second
engine pass. · Architecturally consistent — execution stays where the toolchain is,
certification stays in the verb, and the reviewed tree is never touched by the reviewer.
Makes probe results recordable on the `review` event, so the ledger can distinguish a
finding that was demonstrated from one that was argued. Costs a round trip, a protocol
extension, and a second engine invocation against an already-tight clock.

**Option C — a mutation budget** · The reviewer proposes up to N mutation entries in
#360's table format; the orchestrator runs them through that harness; survivors come back
for a second pass and become findings. · The narrowest and most specific of the four. It
needs no general execute grant, because the thing being invoked is one tool with a fixed
contract rather than arbitrary shell. It is also the only option with an objective verdict
— a survivor is a fact about the suite, not an opinion about the diff. Strictly less
capable than B: it addresses guard vacuity and nothing else, and it is blocked on #360.

**Option D — a host-side review mode with a writable temp dir** · Extend the existing
host-side concession for `--engine codex` (ADR 0002) so a native install may probe. ·
Least new machinery, narrowest reach. It splits review capability by install method,
which is a bad property for a gate: the same diff would be reviewed to a different
standard depending on how the operator installed the tool.

## Recommendation

Take **Option C first, then Option B**, and treat A and D as rejected.

C is the specific version of the ask. It targets the failure class this repo actually
pays for, it rides on a mechanism already being built rather than inventing one, and its
output needs no adjudication — a mutation that survives is a hole, and the reviewer does
not have to be believed. It requires no general execute grant, so it carries none of the
trust escalation that B does, and it is therefore the honest test of whether a probing
reviewer earns its cost before that cost gets larger.

B is the general form and should follow if C pays off. Its virtue is that it respects the
constraint the other options argue with: no image can carry every target repo's
toolchain, so execution belongs on the host, where `--gate-exit` already puts it. Its
cost is a second engine pass on a clock that is already the loop's tightest resource.

This ordering is a deliberate narrowing of the ask, which was framed as execute plus a
throwaway tree plus a mutation budget together. The narrowing follows from
`engineering-principles` — smallest change, no premature generality — and from the same
staged shape `engine-activity-aware-timeouts` chose: prove the observation before setting
the policy. It is put to the operator as a decision below rather than assumed, because
the reasoning for taking all three at once is real: the throwaway tree is needed by both,
and building it twice is worse than building it once.

### The throwaway tree

Both options want the same primitive, and it should be a `git worktree add --detach` at
the reviewed SHA into a scratch path, not a copy. That gives three properties for free:
the probe tree is provably at the SHA under review, the reviewed worktree is untouched by
construction rather than by configuration, and the probe tree is clean — which matters,
because a polluted run worktree is the known cause of the review hang that #359 exists to
refuse.

### The verdict contract

Two invariants must be stated in the change spec and tested, not left implicit.

Nothing the engine produces may reach the reviewed SHA. Today that is enforced by
`close`'s two conjuncts and by the engine having no write capability at all. Granting
execute removes the third defence, so the first two become load-bearing in a way they are
not today, and the change must add a check that the run worktree is byte-identical after
the engine exits rather than relying on the close verb to catch it later.

**A probe must predict its outcome.** This is the same rule #360's AC-1 applies to
mutations, and it is what stops the vacuity problem from simply relocating into review. A
reviewer that runs the suite, sees green, and concludes "verified" has produced exactly
the shape this repo keeps paying for. A probe that declares what it expects to happen,
and is judged against that, produces evidence; a probe that merely runs something produces
a feeling.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Sequence C then B, rather than delivering execute, the throwaway tree, and the mutation budget in one change. | user | this proposal |
| Where probes execute — host-side through the orchestrator (recommended, follows `--gate-exit`), or in-container against a scratch mount. | user | accepted change spec; `verb-model.md` as-built record |
| Whether probes are typed (a mutation entry, a test selection) or free-form commands. Typed is recommended: the engine is reading an untrusted diff, and the container holds the ssh key and the tracker token. | user | accepted change spec |
| The probe budget — how many probes and how much wall clock — set after the first change reports a sample, not guessed now. | user | follow-up change spec and `CONTEXT.md` |

The execution-locus decision is the one that could clear the ADR bar, because it fixes
where a whole class of future capability runs. It is worth revisiting against
`architecture` once it is made; it does not need a standalone ADR before then.

### Resolved 2026-08-07

The operator accepted the **staged sequence — C then B**: ship the mutation budget first,
and decide the general probe callback on what it shows. The reasoning for taking all
three at once was real (the throwaway tree serves both, and building it twice is waste),
so change 1 builds that tree in a shape change 2 can reuse rather than in one specialised
to mutations.

The remaining rows — execution locus, typed versus free-form probes, and the probe
budget — stay open. The first two are resolved in change 1's design; the budget is set
from change 1's reported sample, as its own row says.

## Breakdown

Accepted 2026-08-07 on the staged sequence; filed as **#363** and **#364**. Both are
**Backlog, not Todo** — #363 is blocked on #360 and #364 is blocked on #363's evidence, and
a blocked ticket sitting in the Todo queue is one an unattended Build tick will pick up.

1. **A mutation budget for review** (#363) — the reviewer proposes up to N entries in #360's
   table format; the orchestrator runs them through that harness; survivors return for a
   second pass and become findings; the probe set and its outcomes are recorded on the
   `review` event. Includes the throwaway probe worktree at the reviewed SHA, the
   post-engine byte-identity check on the run worktree, and a measuring test for the added
   duration against the 720-second ceiling. **Blocked on #360.**
2. **The general probe callback** (#364) — typed probe requests emitted alongside findings,
   host-side execution through the orchestrator, a second engine pass, the probe budget as
   an enforced bound rather than a convention, and the demonstrated-versus-argued
   distinction on the event record.

Item 1 is shippable alone and is the decision point for whether item 2 is worth its cost.

## Risks / unknowns

- **This makes review slower, on the loop's tightest resource.** The `nano-erp` incident
  that motivates the proposal was itself two timeouts at the 720-second ceiling. A probe
  budget must land in the same change as the capability, not after it, or this proposal
  makes the timeout problem worse. It also interacts with
  `engine-activity-aware-timeouts`: a probing engine emits activity for longer, which is
  precisely the distribution that proposal wants to measure before setting thresholds.
- **A reviewer that can cause host-side execution is a real trust escalation.** It is
  reading an untrusted diff, and the verb container holds the ssh key and the tracker
  token. Typed probes bound this; free-form shell does not. This is the strongest argument
  for C over B, and for never letting the probe channel become a general command channel
  by increments.
- **The evidence is confounded.** In both incidents the agent had execution *and* an
  explicitly adversarial brief. Some of the gain is attributable to the framing rather
  than the capability. Adversarial framing is much cheaper than any option here, and it
  should be tested on its own so its effect is not credited to execution. The two compose;
  the attribution matters for deciding whether item 2 is worth building.
- **Vacuity can relocate rather than disappear.** A probing reviewer that runs a suite and
  reads green has produced no evidence. The prediction requirement above is the mitigation,
  and it needs its own test — a probe whose prediction is trivially satisfied should be
  rejected by the harness, not counted.
- **A functioning review verb would plausibly have caught one of the three `nano-erp`
  defects by reading alone.** The timeout that produced this comparison has a known cause
  and an open ticket (#359). Fixing that is cheaper than either option here and should not
  be deprioritised because this proposal is more interesting.
- **What would invalidate the recommendation:** if the first change shows the reviewer's
  proposed mutations are mostly no-ops or duplicates of the builder's own table, then the
  independent-counterparty premise is wrong and item 2 should not be built. #360's AC-1
  makes that measurable, because an entry that kills nothing is reported as a failure of
  the entry rather than as a survivor.

---

**Lifecycle.** This proposal is under decision. If accepted, create its tracker issues in
the decided sequence; if rejected, retain this file as the decision record; if split,
replace it with smaller proposals.
