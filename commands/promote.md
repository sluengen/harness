<!-- guidance:promote@0.3.0 -->
# /promote — drive a promotion through the harness lifecycle

Usage: `/promote <src> to <dst>`

Promotion moves completed work toward release — `dev → staging → main` on the
universal three-tier topology (ADR 0003). It is a **first-class, audited
harness lifecycle**, the same shape as the build verbs (`start` → `review` →
`close`), applied to branch movement. This command is the versioned caller: it
transcribes the orchestrator loop that drives the five `harness promote` verbs,
so an outer agent runs `/promote` instead of re-deriving the loop from prose
each time.

**The contract is agent-agnostic.** Hermes is the likely local cron driver on
the always-on device, but the same surface works for OpenClaw, Claude, Codex,
or a human — the harness returns deterministic facts, policy classifications,
bounded evidence, and lifecycle state, and the outer agent decides what to do
with them. The harness surface is **deterministic and model-free**: it does not
depend on any local inference runtime. Local inference, where an orchestrator
uses it at all, powers only the outer agent — drafting PR prose from the
harness's deterministic facts, judging whether an in-policy conflict is worth a
bounded repair. It never sits inside the harness surface.

There is **no no-arg form** — a release hop is deliberate, not inferred. Both
`<src>` and `<dst>` are required.

## Argument resolution

Each word resolves against this repo's `CONTEXT.md` `branches:` roles first,
falling back to a literal branch ref:

1. If the word is one of the three canonical role keys — `integration`,
   `staging`, `release` — and `CONTEXT.md` defines that role, resolve to the
   branch name it names.
2. Otherwise, use the word itself as a literal branch ref.

This is why the same invocation shape works everywhere, whatever a repo calls
its branches. Take this repo's own roles (`integration: dev`, `staging:
staging`, `release: main`):

- `/promote dev to staging` — the nightly stabilization hop. `dev` matches no
  role key, so it is used literally; `staging` matches the `staging` role,
  which also resolves to `staging` here. Either path lands on the same pair.
- `/promote staging to main` — the deliberate release hop. `staging` resolves
  via the role; `main` matches no role key and is used literally.
- `/promote integration to release` resolves identically to the `dev to
  staging` example above — the canonical role names always work too.

Now take a repo whose roles are `integration: develop`, `staging: staging`,
`release: production` — a different repo, different branch names for the same
three roles. **The identical invocation drives it unchanged:**
`/promote develop to staging` — `develop` matches no role key so it is used
literally (and happens to be that repo's actual integration branch); `staging`
resolves via the role to `staging`. No per-repo command variant is needed; the
resolver is what changes, not the command.

## The loop

```text
1. harness promote start --repo <repo> --from <src> --to <dst>
     → fetches origin, validates the pair, creates the promotion
       worktree/branch from the target, and attempts the merge. Does NOT run
       the gate — the caller does (step 2a). Returns one structured state.
2. branch on that state:
     • gate_pending   → 2a. run the repo's verify gate in the promotion
                            worktree (host-side, where the toolchain lives),
                            capturing its output to a log; then:
                            harness promote continue --promotion-id <id>
                              --gate-exit <code> --gate-log <path>
                            → green → pr_ready; red → needs_ticket. Branch
                            again.
     • agent_may_fix  → make ONE bounded, in-policy repair in the worktree,
                        run the gate on the resolved tree, then:
                        harness promote continue --promotion-id <id>
                          --gate-exit <code> --gate-log <path>
                        (completes the repair + classifies the gate); branch
                        again.
     • pr_ready       → go to step 4 (open/land it — `harness promote pr`).
     • needs_ticket   → go to step 5 (escalate).
     • blocked        → go to step 5 (escalate).
     • opened         → ungated (no verify: configured); treat per repo
                        policy.
3. (inspect any time) harness promote status --promotion-id <id> --json
4. harness promote pr --promotion-id <id>     ← the success finalizer; the hop
                                                selects the mechanism
     → --to staging: advances staging itself to the gated SHA, opens NO PR,
       records promoted. Stop — success, nothing pending.
     → --to main:    pushes ONLY the promotion branch, opens the PR into the
       target from deterministic facts, records pr_opened. Stop — success, a
       human merges it.
5. harness promote escalate --promotion-id <id>
     → files/updates a tracker ticket with the evidence, records escalated.
       Stop — a human owns it now.
```

`--gate-log <path>` must name a file readable from inside the harness
container, exactly as `harness review`'s own `--gate-log` does — the wrapper
mounts only the repo root, so a host-side absolute path outside it reads as
missing. Prefer a path under the promotion worktree or `<repo>/.harness/`.
`promote` fails **closed** on this: an unreadable `--gate-log` alongside a
green `--gate-exit 0` rests at `gate_pending` rather than silently recording
empty evidence as a pass.

Stop on any terminal — `promoted` (the staging hop landed; nothing is
pending), `pr_opened` (a release PR is waiting for a human/CI merge), or
`escalated` (a ticket is waiting for a human). Do not loop past a terminal, and
do not retry a `needs_ticket`/`blocked` promotion by re-running `start`.

## The five subcommands

| Command | Role |
|---|---|
| `harness promote start --from <src> --to <dst> [--gate-exit <c> --gate-log <p>]` | Open a promotion: create the worktree/branch, attempt the merge, and classify. A clean merge that defines a gate rests at `gate_pending` until the caller supplies gate evidence — the verb never runs the gate. |
| `harness promote continue --promotion-id <id> [--gate-exit <c> --gate-log <p>]` | Resume a promotion: complete an `agent_may_fix` repair (**one** bounded attempt) or a `gate_pending` merge, then classify the caller's supplied gate evidence — green → `pr_ready`, red → `needs_ticket`. |
| `harness promote status --promotion-id <id> --json` | Read-only: report the promotion's current lifecycle state. |
| `harness promote pr --promotion-id <id>` | Success finalizer (refused unless the promotion is `pr_ready` with fresh gate evidence). The hop selects the mechanism: `--to staging` advances staging to the gated SHA with no PR (`promoted`); `--to main` pushes the promotion branch and opens the release PR (`pr_opened`). |
| `harness promote escalate --promotion-id <id>` | Non-success terminal: file/update a ticket on the configured tracker with the evidence and mark the promotion `escalated`. Refuses `no_tracker` (carrying the evidence in the payload) when the repo runs `tracker: none`. |

## Lifecycle states

The six states `start`/`continue` branch on, and the three terminals they stop
on:

| State | Meaning — what the outer agent does |
|---|---|
| `opened` | The row/worktree/branch exist and the merge was attempted, but the repo configures no `verify:` gate (ungated). Treat per repo policy. |
| `gate_pending` | Clean merge, the repo does define a `verify:` gate, and no evidence is supplied yet — or a green `--gate-exit 0` was supplied but `--gate-log` could not be read. Either way: run/re-run the gate in the worktree host-side, then `promote continue --gate-exit <c> --gate-log <p>`. |
| `pr_ready` | Clean merge and a green gate, with a recorded `gated_sha`. Publish it (`promote pr`). |
| `agent_may_fix` | A small, in-policy conflict or gate failure. Make one bounded repair, then `promote continue`. |
| `needs_ticket` | A real block beyond local repair authority. Escalate — do not repair. |
| `blocked` | The promotion cannot proceed on infrastructure grounds (missing credentials, remote permission, unclean base, or a gate whose toolchain could not run) rather than a code decision. Escalate. |
| **Terminal** `promoted` | Success on the **staging hop**: staging was advanced to the gated SHA. Nothing is pending. Stop. |
| **Terminal** `pr_opened` | Success on the **release hop**: the branch is pushed and the PR is created, awaiting a human/CI merge. Stop. |
| **Terminal** `escalated` | A tracker ticket carries the evidence. Stop. |
| `cancelled` | A withdrawn or superseded promotion — recorded, never deleted, and never acted on by this loop. |

`status` is the source of truth; the orchestrator reads these off the JSON, it
does not scrape prose.

## What the outer agent must never do

The harness owns every promotion lifecycle transition. The outer agent **must
not**, under any orchestrator:

- **Push the target/release branch directly.** Only `harness promote pr`
  pushes. That staging advances on a green gate is the harness's authority,
  exercised inside the audited lifecycle — not a licence for the outer agent to
  touch a target branch. `main` is never direct-pushed, by anyone.
- **Open, close, or merge a PR outside the harness.** PR creation is `harness
  promote pr`'s job; a PR opened outside it is off-ledger. The harness never
  auto-merges the release PR — that stays a human/CI act.
- **Mutate tracker promotion state outside the harness.** Escalation tickets and
  their promotion links are `harness promote escalate`'s job; the outer agent
  does not create, transition, or comment on promotion tickets out of band.
- **Mark a promotion done.** Terminal state (`promoted` / `pr_opened` /
  `escalated`) is a ledger transition the harness records — the orchestrator
  observes it, it does not assert it.

Every one of these is a lifecycle state transition, and every transition
belongs in the harness ledger. Doing any of them outside the harness puts git,
PR, or tracker state out of band from the audit trail — the exact failure the
audited lifecycle exists to prevent.

## Bounded repair and escalation

Repair is **one bounded attempt**, and only for small, low-semantic problems:

- **Allowed:** docs / changelog / generated-summary / spec-prose conflicts;
  small source conflicts under the configured file/line threshold; obvious
  formatting or import-order gate failures.
- **Escalate instead of repair:** schema migrations; auth / payment / security /
  release / deployment scripts; package-lock conflicts unless the repo opts in;
  conflicts over the file threshold; a second gate failure after one bounded
  fix; missing credentials or remote-permission failures; an ambiguous topology
  or an unclean base.

After a bounded edit the orchestrator runs the verify gate on the resolved tree
host-side and calls `promote continue --gate-exit <c> --gate-log <p>` once,
which completes the merge, classifies that supplied evidence, and increments
the attempt count. A promotion cannot become `pr_ready` without fresh gate
evidence. If that gate is red, the bounded attempt is spent and the promotion
moves to `needs_ticket`; the outer agent does not try a second repair.

**Escalation** is a first-class terminal path, not an error. `harness promote
escalate` files (or, when the promotion is already linked, comments on) a
tracker ticket carrying the promotion id, source/target branches, conflict
files, a bounded gate-output summary, and the branch/worktree to inspect — then
records the `escalated` state. Missing tracker credentials return a structured
`blocked` result rather than a raw failure, leaving the promotion row untouched
so a human can supply the credentials and re-escalate.

## Publishing the release PR

`promote pr`'s release hop shells out to `gh pr create` inside the harness
container — the runtime image must carry a `gh` binary for it to publish (issue
#187). Until that shipped, a green `pr_ready` promotion on the `--to main` hop
recorded `pr_opened` facts but could not actually create the PR, and the
orchestrator had to open it by hand from those facts. That gap is closed: `gh`
is installed in the runtime image and `doctor` checks for it (WARN on
absence). If a target repo's own runtime image predates that, the same manual
fallback applies until it rebuilds.

## Fallback: no harness app

Everything above assumes `harness` is on `$PATH` as the Docker wrapper
(`~/bin/harness`) — the same presence check `/harness run` depends on. A repo
without the harness app still has a `dev → staging → main` topology in its
`CONTEXT.md` and still needs a promotion driven, so `/promote` drives it
through a **deliberately reduced**, agent-orchestrated path instead: the
`/build`-is-available-everywhere pattern (`CLAUDE.md`), applied to release
movement.

**Detect first.** Check whether `harness` resolves on `$PATH` before doing
anything else. If it does, drive the verb loop above — never this path. If it
does not, drive the loop below. Do not infer presence from `CONTEXT.md` or
anything else; the `$PATH` check is the one test.

**The loop, reduced:**

1. Create a worktree off the **target** branch (`<dst>`, resolved the same way
   as the verb-backed path above).
2. Merge the **source** (`<src>`) into it. On conflict: **stop and report** —
   the conflicting files and a diff summary. No repair attempt, bounded or
   otherwise; unlike `agent_may_fix` above, this path has no repair authority
   at all.
3. Run the repo's `CONTEXT.md` `commands.verify` gate in that worktree — read
   it fresh from `CONTEXT.md` every run; never hardcode a gate command here,
   since this path keeps no ledger to remember one in. On red: **stop and
   report** the captured gate output. No retry.
4. On green, the hop asymmetry from the verb-backed path holds:
   - `--to` an **intermediate** branch (e.g. `staging`): push the merged tree
     directly to the target ref. No PR — the gate already made the call.
   - `--to` the **release** branch (e.g. `main`): push only the promotion
     branch (never the target directly), and open a PR into the target
     carrying the commit range and gate evidence. A human merges it.

**What you lose without the ledger.** This path has no promotion id, no
ledger row, and no resumable state — a conflict or a red gate stops the whole
hop cold rather than being recorded for a later `harness promote continue`.
There is no audit trail beyond ordinary git history and the PR itself. A repo
that needs any of that should install the harness app, not grow this path
toward it.

**Reduced by decision, not by omission.** ADR 0003's 2026-07-23 amendment
names this path explicitly reduced: no bounded repair, no five-state machine,
no ledger. Do not "complete" it into a mirror of the verb-backed loop above —
that would put two implementations of the promotion lifecycle in one file, and
they would drift from each other. If this path starts needing conflict
classification or a repair budget, that need belongs in the harness app, not
here.
