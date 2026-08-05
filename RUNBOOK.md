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

## Owed: state the target repo before the implicit form is removed (#306)

Every verb now takes an explicit `--repo <path>`. Omitting it still works and
still means "the current working directory", but prints one deprecation line to
stderr:

```
warning: no --repo given — defaulting to the current working directory. The implicit form is deprecated and will be removed; pass --repo <path> explicitly (ADR 0012).
```

The warning is the whole point of the release: ADR 0012 retires ambient shell
state as an interface, and the implicit form is removed in a later change. What
follows is the work that must land **before** that removal, split by who can do
it.

### Callers outside this checkout — the operator's job

Neither file is in this repo, so no guard here can see them and no change here
can fix them:

| Caller | Fix |
|---|---|
| `~/.claude/scheduled-tasks/harness-work-pull` | Give the thin caller the absolute repo path, and pass it as `--repo` on each verb invocation it makes. |
| `~/.claude/scheduled-tasks/harness-code-assess` | Same. |

**How to check one:** fire the task once and read stderr. A deprecation line
means that caller is still implicit. Silence means it is done.

### The wrapper — a repo-side prerequisite (#351)

**Half of this is now done.** #307 rewired the wrapper's tail onto
`harness.hostenv.client`, so container construction is Python
(`harness.hostenv.spawn`) rather than hand-rolled bash. Two consequences:

- **The argv half is discharged.** `spawn.rewrite_repo_argument` resolves an
  explicit `--repo`, rewrites it to `/workspace` when it names the mounted repo,
  and refuses it (`repo_mismatch`) when it names another — so the flag no longer
  resolves outside the allowlist, and the same translation applies on both the
  socket and fallback paths.
- **The line-ratchet blocker is gone.** The wrapper dropped from 158 to 116
  executable lines and the ratchet in `tests/unit/test_wrapper_delegates.py` was
  re-baselined 165 → 120. The remaining work is Python, which that ratchet does
  not bound at all.

What is **not** done, and is what [#351](https://github.com/sluengen/harness/issues/351)
still is: the mount still follows `$(pwd)`, not the `--repo` value. The client is
invoked as `… client "$(pwd)" -- "$@"`, so naming a *different* repo is refused
rather than mounted, and `.env` is still read from the invoking directory.
Invocations through `~/bin/harness` therefore stay implicit and keep warning until
the mount half lands.

This is also why the in-repo callers in `commands/harness.md` are deliberately
**not** updated to pass `--repo`: documenting an invocation the primary entry
point rejects would be worse than the warning.

Order of operations: #351 → the in-repo callers → the two operator triggers
above → remove the implicit form.

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
topology (ADR 0003). The full loop — the five verbs, the states an outer agent
branches on, what it must never do, and how bounded repair and escalation
behave — is versioned in **`/promote`** (`commands/promote.md`); this section
names only this repo's own operational facts around it.

### The two flows, on this repo's own schedule

- **Nightly `dev → staging` (the stabilized candidate).** A cron trigger fires
  the outer agent once a night: `/promote dev to staging`. This is the routine,
  repetitive movement the loop exists to automate.
- **Deliberate `staging → main` (the release).** A human (or a deliberately
  fired schedule) runs `/promote staging to main` when a stabilized candidate
  is ready to release. The loop is identical; only the trigger is intentional
  rather than nightly. Merging the release PR stays a deliberate human/CI act —
  the harness opens the PR, it never auto-merges.

There is no interim `dev → main` path; the topology is three-tier from the
start. See `/promote` for the orchestrator loop, the lifecycle states, the
forbidden outer-agent actions, and the bounded-repair/escalation policy.

One concrete, cheap occupant of the outer-agent slot — OpenCode driving the
verbs non-interactively with a local MLX model, on a `launchd` schedule — is
spiked in [`specs/local-orchestrator-stack.md`](specs/local-orchestrator-stack.md).
It is a hypothesis, not yet validated, and nothing above depends on it.

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

### Non-secret pre-scrub surfaces in history — accepted (CAL-1193)

Separate from secrets, and decided separately. The **current tree** is scrubbed of
two private surfaces — the Linear **workspace URL** and the operator **home path** —
and a gate guard (`tests/unit/test_no_private_surfaces.py`) keeps it that way. That
guard covers the **tracked tree, not history**: pre-scrub commits (before the
CAL-1027 scrub) still contain the current and legacy workspace-URL slugs and the
home path.

**Decision — accept and keep; do not rewrite history for these.** They are **not
secrets** (the gitleaks audit above is clean): the workspace URLs 404 for anyone
outside the private Linear org, and the home-path username is already implied by
commit-author identity. Against that low impact, a `git filter-repo` rewrite would
change **every commit SHA** and so falsify the SHA citations the repo deliberately
keeps across `CHANGELOG*`, `specs/`, and `assessments/LOG.md` — a worse outcome than
the surface it would hide. This is the disclosure review's recommendation (CAL-1189,
`assessments/2026-07-19-pre-publication-readiness.md`, should-do 4). The secret rule
above is unchanged: a **real secret** ever found in history still returns the
history-rewrite decision to the operator; a non-secret surface does not.
