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
