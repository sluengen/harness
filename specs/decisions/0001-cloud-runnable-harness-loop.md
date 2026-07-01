# ADR 0001 — The harness's own loop runs in the cloud; cloud-viability is per-target-repo

- **Status:** Accepted
- **Date:** 2026-07-01
- **Source:** proposal `specs/proposals/harden-loop-layer.md` (WS3, decision **C2**); CAL-908
- **Supersedes:** the earlier "routines are local-trigger only / cloud execution is out of scope" posture, for the harness's **own** loop only.

This is the first record in `specs/decisions/`. Design docs still live in `specs/`; this directory holds discrete architecture decisions from here on.

## Context

`/harness routine build` is not just a harness invocation — read honestly, it is a **loop**: it discovers its own work off the Linear queue, runs unattended, and feeds itself across runs via Linear and the ledger. The *Loop Engineering* field study (Osmani / Anthropic / Stripe) is blunt that the overnight sweep belongs in the cloud, because "laptops get their lids closed." Until now the harness's loop was **local-only, and framed as out of scope for the cloud** — everything ran on a machine that had to stay awake.

The first draft of the harden-loop-layer proposal assumed cloud was "a project" because the Docker wrapper (`~/bin/harness`) sources credentials from the macOS Keychain, a local `.env`, and `~/.codex`. **On review that premise was wrong:**

- The full gate (`scripts/verify.sh`) already runs green on `ubuntu-latest` in CI on every `main` PR — the gate is Linux-proven.
- There are **zero** Xcode / Swift / macOS / Homebrew dependencies in the repo.
- The verbs run **in-process** off the native `harness` console script (`pyproject` `[project.scripts]`) — no Docker-in-Docker. The one daemon-needing test (`tests/integration/test_docker.py`) is `integration`-marked and self-skips when `docker info` fails.
- The Mac-local pieces are credential *sourcing*, not execution. Each becomes a standard cloud secret.
- The credential reads already come from the process environment (`harness/linear.py` reads `LINEAR_API_KEY` from `os.environ`), so no code change is needed to feed them from secrets.

So for the harness's **own** loop, cloud is a **secrets-wiring + engine-selection** job, not a re-architecture. Sequenced **last**, after WS1 (CAL-906): an unbounded loop must not run unattended in the cloud, so the ledger-backed spend-breakers (6-cycle review ceiling, 90-minute wall-clock budget) land first and this wiring is the capstone — the playbook's "add scale last, after the checks are proven."

## Decision

**Wire the harness's own Build/Quality loops onto a cloud schedule**, implemented as a versioned GitHub Actions workflow: [`.github/workflows/harness-loop.yml`](../../.github/workflows/harness-loop.yml).

### Why GitHub Actions (and not an off-repo Claude cloud routine)

The substrate is a real choice, so it is recorded here:

- **The workflow is a versioned repo artifact.** It lives in `.github/workflows/`, so the cloud schedule is under version control alongside the logic it runs — honoring *version the logic, not the schedule* (WS2's whole fight was trigger drift; an off-repo routine config is exactly the drift surface we removed). A Claude cloud routine's configuration lives in the app, off-repo, and would reintroduce that drift.
- **The gate is already proven on this exact substrate.** CI runs `scripts/verify.sh` green on `ubuntu-latest`; the loop runs on the same runner.
- **Credentials map cleanly to GitHub Actions secrets** (below).
- **A clean clone every run** (`actions/checkout`) is precisely the fresh-clone / no-local-DB case the Linear-keyed reclamation already handles.

A Claude cloud routine (`/schedule`, 1-hour-minimum interval) remains a viable *alternative trigger*; the overnight sweep's cadence tolerates either. If one is ever adopted, it must still drive the same versioned `/harness routine build` surface.

### Secrets (the cloud-secret credential model)

The workflow reads every credential from `secrets.*`; nothing is committed:

| Secret | Replaces (local sourcing) | Used for |
|---|---|---|
| `LINEAR_API_KEY` | the working copy's `.env` | ticket reads + the audited verb transitions |
| `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) | the macOS Keychain OAuth extraction | the orchestrating Claude agent + the Claude review engine |
| `GITHUB_TOKEN` (built-in, via `permissions: contents: write`) | the local push credentials | `close`'s push of the merged branch to `dev` |

There is **no** cloud secret for Codex's `~/.codex` subscription auth — see the engine choice.

### Engine: Claude, not Codex

The cloud loop uses the **Claude review engine** (the default). Codex's `~/.codex` subscription auth does not travel as a cloud secret, and Codex-in-container is already bwrap-blocked (CAL-866) with the engine falling back to Claude — so Codex is moot in the cloud. The workflow never selects `--engine codex`. This is already the in-container reality; the honest cost is recorded under Consequences.

### Clean-clone reconciliation

Each run is a fresh clone with no local ledger. Before picking work the workflow runs the **Linear-keyed reclaim pre-flight** (`harness reclaim --stale --project "Harness v3"`) — Step 0 of the Build routine, hoisted so it runs even before the agent starts. Because the sweep keys on Linear (not the absent local DB), it reverts any ticket stranded *In Progress* by a dead predecessor back to *Todo* so this run can pick it up. This is what makes the loop safe to run from a cold clone.

## The per-target-repo gate rule (load-bearing)

**"The harness runs its own loop in the cloud" must not be read as "the harness runs any repo in the cloud."**

The harness is infrastructure other repos self-host. Its *own* loop is cloud-viable because *its own gate* has no macOS dependency. Cloud-viability for a **self-hosting target repo** is set by **that target's gate**, not by the harness's auth:

- A target whose gate needs Xcode / Swift / macOS tooling (e.g. an iOS repo) **stays local, or runs on a `macos-latest` runner.** Its loop cannot move to a Linux runner just because the harness's can.
- A target with a Linux-clean gate can adopt the same pattern (its own workflow, its own secrets).

A future cloud rollout to a self-hosting target must check that repo's gate first. Cloud-enabling self-hosting target repos is **out of scope** for this decision.

## Consequences

- **Overnight autonomy no longer depends on a laptop staying open** — once the operator provisions the secrets and the workflow reaches the default branch, the cron fires the sweep nightly.
- **The cloud loop loses model-*family* review diversity.** Reviewing via Claude (generator) with a Claude reviewer (evaluator) forgoes the cross-model second opinion a Codex reviewer gives locally. Acceptable — it is already the in-container default — but tracked against the generator/evaluator principle; a local `--engine codex` pass remains the way to get family diversity.
- **The spend-breakers are now genuinely load-bearing.** An unattended cloud run is bounded only by the CAL-906 breakers (6-cycle ceiling, 90-minute wall-clock) plus the job `timeout-minutes` backstop. If those move, the cloud exposure moves with them.
- **First run is operator-gated (the demonstration residue).** This tick ships the versioned workflow and its structural guard (`tests/unit/test_cloud_loop_workflow.py`); it cannot itself provision GitHub secrets or trigger a live cloud run. The operator completes the demonstration — see below. This mirrors WS2's out-of-repo residue (the `~/.claude/scheduled-tasks/*` re-sync).

## Operator steps to complete the live demonstration

1. In the GitHub repo settings → **Secrets and variables → Actions**, add `LINEAR_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`). `GITHUB_TOKEN` is built in.
2. Ensure the workflow is on the **default branch** (`main`) — scheduled triggers only fire from there. (It reaches `main` on the next `dev → main` release.)
3. **Dispatch it once** (Actions → *harness-loop* → *Run workflow*) to perform the first, demonstrating run without waiting for the cron. Confirm the run: installs the harness natively, runs the reclaim pre-flight, and drives `/harness routine build` with the Claude engine to Done (or a clean idle exit).
4. Leave the `schedule:` cron enabled for the nightly overnight sweep.
