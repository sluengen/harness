# RUNBOOK.md — operational runbook for the harness's own loops

Operational procedures for the operator who runs the harness's Build and Quality
loops on their own machine. This is an **app-operator** doc, not distributed
guidance — it names this operator's local trigger files, which live outside the
repo. The universal logic those triggers fire is versioned in the surface
(`commands/harness.md`, `skills/work-discovery/SKILL.md`); this runbook only keeps
the *triggers* honest against it.

---

## Re-syncing the local routine triggers

**Principle: _version the logic, not the schedule._** The pick/discovery logic
and the loop steps are versioned in the repo — the `/harness routine build` and
`/harness routine quality` commands, and the `work-discovery` skill they invoke.
A scheduled trigger must therefore be a **thin caller**: it fires the versioned
routine and nothing else. It must never carry its own copy of the loop logic,
because a copy drifts — and a trigger that has drifted runs yesterday's process
while the repo believes today's is live.

### The two triggers

The operator's macOS/Claude scheduled tasks that drive the loops:

| Task file (`~/.claude/scheduled-tasks/…`) | Must invoke | Loop |
|---|---|---|
| `harness-work-pull` | `/harness routine build` | hourly work-pull |
| `harness-code-assess` | `/harness routine quality` | idle / weekly assessment |

### The drift this fixes

These triggers were authored before the routines were versioned and before run
reclamation shipped, so they drifted:

- they **inlined the pick logic** as their own prose instead of invoking the
  versioned routine, and
- they said **"use `/build`"** directly rather than calling `/harness routine
  build` (whose primary surface, in the harness repo, is `/harness run`), so the
  reclamation pre-flight and the resume path never ran on a nightly tick.

Inlining is the failure mode the drift guard
(`tests/unit/test_work_discovery_skill.py`) exists to catch on the *repo* side;
this runbook is the matching operational fix for the *out-of-repo* trigger files.

### Re-sync procedure

For **each** task file above:

1. Open the task's prompt/config in `~/.claude/scheduled-tasks/<task>/`.
2. **Replace its body with a thin invocation** of the versioned routine — the
   single line `/harness routine build` (or `/harness routine quality`) plus only
   the minimum context the runner needs (the working directory / repo path). Do
   **not** restate the queue-reading, ranking, or actionability logic in the
   trigger; that lives in the `work-discovery` skill the routine invokes.
3. Delete any leftover pre-reclamation wording and any direct "use `/build`"
   instruction — the routine chooses its own build surface.
4. Save, and confirm the schedule (cron / interval) is unchanged — only the
   *logic* is being re-pointed, never the schedule.

### Verify the re-sync

- The trigger body is one routine invocation, not a procedure. If you can read
  the pick criteria in the trigger, it is still inlined — send it back to step 2.
- Fire the task once manually and confirm it runs the reclaim pre-flight before
  picking work (the signature that the versioned routine — not a stale copy — is
  what ran).
- Re-run the guard on the repo side: `uv run --extra dev pytest
  tests/unit/test_work_discovery_skill.py` stays green, confirming the versioned
  surface the trigger now calls still single-homes the logic.

---

## Substrate: always-on local is the default

The local triggers above are the **default** substrate for the harness's own
loop — they already work and cost nothing per run. Running the loop off-machine
is *possible* (the gate is Linux-clean and the verbs run in-process), but is
**deferred and optional**: if the device ever stops being always-on, the recorded
next step is a **Claude cloud routine** driving the same `/harness routine build`
— **not** GitHub Actions (rejected: a private repo meters Actions minutes and the
loop is a long agent run, not a cheap CI gate).

The decision, the optional cloud path, and the **per-target-repo gate rule**
(off-machine viability is set by the *target's* gate — an Xcode/macOS-bound target
stays local or on a macOS runner) are recorded in
`specs/decisions/0001-cloud-runnable-harness-loop.md`.

## The promotion routine — moving `dev → staging → main`

Promotion moves completed work toward release. It is a **first-class, audited
harness lifecycle** — the same shape as the build verbs (`start` → `review` →
`close`), applied to branch movement over the universal `dev → staging → main`
topology ([ADR 0003](specs/decisions/0003-promotion-lifecycle.md)). An **outer
agent** triggers it on a schedule and may repair within a narrow policy; the
harness owns every state transition and records it in a promotion ledger.

**The contract is agent-agnostic.** Hermes is the likely local cron driver on the
always-on device, but the same surface works for **OpenClaw**, **Claude**,
**Codex**, or a **human** — the harness returns deterministic facts, policy
classifications, bounded evidence, and lifecycle state, and the outer agent
decides what to do with them. The harness surface is **deterministic and
model-free**: it does not depend on any local inference runtime. Local inference,
where an orchestrator uses it at all, powers **only the outer agent** — drafting
PR prose from the harness's deterministic facts, and judging whether an in-policy
conflict is worth a bounded repair. It never sits inside the harness surface.
*(Guidance propagation across repos — the sequenced per-repo `update-guidance`
jobs — is a sibling routine documented separately; it is not part of this
promotion loop.)*

One concrete, cheap occupant of that outer-agent slot — OpenCode driving the
verbs non-interactively with a local MLX model, on a `launchd` schedule — is
spiked in [`specs/local-orchestrator-stack.md`](specs/local-orchestrator-stack.md).
It is a **hypothesis, not yet validated**, and nothing in this section depends on
it: the contract below is what any orchestrator follows.

### The two flows

Two promotions run on this topology, on different cadences:

- **Nightly `dev → staging` (the stabilized candidate).** A cron trigger fires the
  outer agent once a night. It opens a promotion from `dev` into `staging`, lets
  the harness merge and gate, repairs one bounded conflict/gate failure if policy
  permits, and on a green candidate opens the candidate PR. This is the routine,
  repetitive movement the loop exists to automate.
- **Deliberate `staging → main` (the release).** A human (or a deliberately-fired
  schedule) opens a promotion from `staging` into `main` when a stabilized
  candidate is ready to release. The loop is identical; only the trigger is
  intentional rather than nightly. **Merging the release PR stays a deliberate
  human/CI act** — the harness opens the PR, it never auto-merges.

There is no interim `dev → main` path; the topology is three-tier from the start.

### The orchestrator loop

For one promotion (either flow), the outer agent runs:

```text
1. harness promote start --repo <repo> --from <src> --to <dst>
     → the harness fetches origin, validates the pair, creates the promotion
       worktree/branch from the target, attempts the merge, and (on a clean
       merge) runs the verify gate. It returns one structured state.
2. branch on that state:
     • pr_ready       → go to step 4 (open the PR)
     • agent_may_fix  → make ONE bounded, in-policy repair in the worktree,
                        then: harness promote continue --promotion-id <id>
                        (re-classify + re-gate); branch on the new state
     • needs_ticket   → go to step 5 (escalate)
     • blocked        → go to step 5 (escalate)
     • opened         → ungated (no verify: configured); treat per repo policy
3. (inspect any time) harness promote status --promotion-id <id> --json
4. harness promote pr --promotion-id <id>
     → pushes ONLY the promotion branch, opens the PR into the target from
       deterministic facts, records pr_opened. Stop — success.
5. harness promote escalate --promotion-id <id>
     → files/updates a Linear ticket with the evidence, records escalated.
       Stop — a human owns it now.
```

The outer agent **stops** on either terminal — `pr_opened` (a PR is waiting for a
human/CI merge) or `escalated` (a ticket is waiting for a human). It does not loop
past a terminal, and it does not retry a `needs_ticket`/`blocked` promotion by
re-running `start`.

### The commands and the states it branches on

The five subcommands are the orchestrator's stable pause points:

| Command | Role |
|---|---|
| `harness promote start --from <src> --to <dst>` | Open a promotion: create the worktree/branch, attempt the merge, run the gate on a clean merge, and return a policy classification. |
| `harness promote continue --promotion-id <id>` | Resume an `agent_may_fix` promotion after **one** bounded repair: commit the resolved merge, re-run the gate, increment the attempt count. |
| `harness promote status --promotion-id <id> --json` | Read-only: report the promotion's current lifecycle state. |
| `harness promote pr --promotion-id <id>` | Success finalizer: push the promotion branch and open the PR (refused unless the promotion is `pr_ready` with fresh gate evidence). |
| `harness promote escalate --promotion-id <id>` | Non-success terminal: file/update a Linear ticket with the evidence and mark the promotion `escalated`. |

Every command emits machine-readable JSON carrying the promotion's `status`. The
lifecycle states the orchestrator branches on:

| State | Meaning — what the outer agent does |
|---|---|
| `opened` | The row/worktree/branch exist and the merge was attempted, but nothing is gated yet (no `verify:` configured — ungated). Treat per repo policy. |
| `pr_ready` | Clean merge **and** a green gate, with a recorded `gated_sha`. Open the PR (`promote pr`). |
| `agent_may_fix` | A small, in-policy conflict or gate failure. Make **one** bounded repair, then `promote continue`. |
| `needs_ticket` | A real block beyond local repair authority. Escalate (`promote escalate`) — do not repair. |
| `blocked` | The promotion cannot proceed on infrastructure grounds (missing credentials, remote permission, unclean base) rather than a code decision. Escalate. |
| `pr_opened` | Terminal success: the branch is pushed and the PR is created. Stop. |
| `escalated` | Terminal non-success: a Linear ticket carries the evidence. Stop. |
| `cancelled` | A withdrawn or superseded promotion — recorded, never deleted, and never acted on by the routine. |

`status` is the source of truth here; the orchestrator reads these off the JSON,
it does not scrape prose.

### What the outer agent must never do

The harness owns every promotion lifecycle transition. The outer agent **must
not**, under any orchestrator:

- **Push the target/release branch directly.** Only `harness promote pr` pushes,
  and it pushes **only the promotion branch** — never `staging` or `main`.
- **Open, close, or merge a PR outside the harness.** PR creation is
  `harness promote pr`'s job; a PR opened outside it is off-ledger. The harness
  never auto-merges the release PR — that stays a human/CI act.
- **Mutate Linear promotion state outside the harness.** Escalation tickets and
  their promotion links are `harness promote escalate`'s job; the outer agent does
  not create, transition, or comment on promotion tickets out of band.
- **Mark a promotion done.** Terminal state (`pr_opened` / `escalated`) is a
  ledger transition the harness records — the orchestrator observes it, it does
  not assert it.

Every one of these is a lifecycle state transition, and every transition belongs
in the harness ledger. Doing any of them **outside the harness** puts git, PR, or
tracker state out of band from the audit trail — the exact failure the audited
lifecycle exists to prevent.

### Bounded repair and escalation

Repair is **one bounded attempt**, and only for small, low-semantic problems:

- **Allowed:** docs / changelog / generated-summary / spec-prose conflicts; small
  source conflicts under the configured file/line threshold; obvious formatting or
  import-order gate failures.
- **Escalate instead of repair:** schema migrations; auth / payment / security /
  release / deployment scripts; package-lock conflicts unless the repo opts in;
  conflicts over the file threshold; a **second** gate failure after one bounded
  fix; missing credentials or remote-permission failures; an ambiguous topology or
  an unclean base.

After a bounded edit the orchestrator calls `promote continue` **once**, which
re-runs classification and the gate and increments the attempt count. A promotion
**cannot become `pr_ready` without fresh gate evidence** — the same evidence
discipline the `review`/`close` gate enforces. If that re-gate fails, the bounded
attempt is spent and the promotion moves to `needs_ticket`; the outer agent does
not try a second repair.

**Escalation** is a first-class terminal path, not an error. `harness promote
escalate` files (or, when the promotion is already linked, comments on) a Linear
ticket carrying the promotion id, source/target branches, conflict files, a
bounded gate-output summary, and the branch/worktree to inspect — then records the
`escalated` state. Missing Linear credentials return a structured `blocked` result
rather than a raw failure, leaving the promotion row untouched so a human can
supply the credentials and re-escalate.

## The guidance-update routine — sequenced per-repo `update-guidance` jobs

Guidance ships from this repo (the guidance source) and is **copied into** every
consuming repo, so a harness release does not propagate itself. After a release
makes a new guidance version available on `main`, each consuming repo has to pull
that version in, prove it still passes its **own** gate, and move it toward
release. This is the **sibling routine** the promotion routine above defers to: it
reuses the same per-repo promotion mechanics, but it is **not** part of the
promotion lifecycle, and the harness does **not** run it as one fleet-wide
operation.

**One job per repo, fired in sequence — not a fleet-wide harness operation.**
Guidance propagation is deliberately *not* a single monolithic harness command
that fans out across the fleet. Each consuming repo owns its **own** scheduled
`update-guidance` job; the outer **scheduler/orchestrator** (Hermes, a cron, a
human) fires those jobs **in sequence**, one repo after another. The harness
supplies only the per-repo promotion mechanics each job calls — it never
orchestrates the fleet itself. Keeping the jobs separate is exactly what lets one
repo fail without wedging the rest: a single fleet-wide harness operation would
halt the whole chain on the first failure and obscure which repo broke.

### One repo's job

For a single consuming repo, its scheduled job runs:

1. **Pull the guidance** — run `/update-guidance` in the repo, which pulls the new
   guidance version from the source and stamps the installed files.
2. **Gate it with the repo's own gate** — run **that repo's** configured verify
   gate on the result. The gate is per-repo: an Xcode target gates on
   `xcodebuild`, this repo on `scripts/verify.sh`. A guidance bump that breaks a
   repo's gate is caught **in that repo**, before it moves toward release.
3. **Promote it through the repo's own path — or escalate.** On a green gate, the
   job opens a promotion of the guidance update through **that repo's own**
   `dev → staging` promotion path (the promotion routine above). On a red gate or
   a promotion block, it **escalates** instead of forcing the update through.

Every step uses **that repo's own** gate and **that repo's own** promotion path —
the harness gives each job the same audited promotion surface, and each job drives
it independently against its own branches. No job reaches into another repo.

### Failure policy — file a ticket, then continue or stop

A job that cannot complete — a gate failure, a promotion block, a missing
credential — **files or updates a Linear ticket** and hands off to a human rather
than wedging the chain silently. The ticket carries, at minimum:

- the **repo** that failed,
- the **guidance version** it was moving to,
- the **gate output** summary (the evidence of *why* it failed), and
- the **next action** a human should take.

The sequence then **continues or stops per documented policy** — a per-repo
failure does not silently halt every later repo's job. The default is to
**continue** the remaining repos (each is independent, so one repo's broken bump
does not block another's) and let the filed tickets carry the failures; a policy
may instead **stop** the chain when a failure is likely to recur everywhere (for
example, a malformed release). Either way the choice is **explicit and recorded**,
never an unexplained silent wedge.

*(The cross-repo scheduler that fires these jobs is out of scope here — this
runbook documents the per-repo job shape and its failure policy, not a fleet-wide
scheduler implementation, and not any automatic guidance-update mechanics inside
the harness.)*

## Pre-public secret audit

Going public exposes the full git history, and the decision on record is to
**keep full history** (scrub only the current tree). That decision is gated on a
history-wide secret audit — evidence the flip can cite.

**Audit of record (2026-07-06):** `gitleaks v8.30.1` scanned the **complete
history** (`git --log-opts="--all"`, 397 commits, ~5.22 MB) and reported
**0 findings**. `.env` has **never** been added to the tree
(`git log --all --diff-filter=A -- .env` is empty), and no env / private-key file
is tracked. No history rewrite is required. An earlier regex sweep
(`lin_api_` / `sk-ant-` / `ghp_` / OAuth patterns) agreed; the entropy scan is
the stronger confirmation.

`tests/unit/test_secret_hygiene.py` keeps the tree clean going forward — it fails
if any dotenv / private-key / keystore file is ever committed, and pins the
`.gitignore` rules that keep `.env` out of the index.

**Re-run the scan** (no host install; official image, repo mounted read-only):

```bash
docker run --rm -v "$(pwd):/repo:ro" \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
  ghcr.io/gitleaks/gitleaks:latest git --log-opts="--all" --no-banner /repo
# exit 0 + "no leaks found" = clean; exit 1 lists the leaks to triage.
```

Triage any future finding: a **real** secret returns the history-rewrite decision
to the operator (do not rewrite history unattended); a **false positive** goes in
a committed `.gitleaks.toml` allowlist. Re-run before the visibility flip and
whenever history gains sensitive-looking content.
