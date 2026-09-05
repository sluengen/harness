# ADR 0001 — The harness's own loop runs always-on local by default; cloud is optional and per-target-repo

- **Status:** Accepted
- **Date:** 2026-07-01 (revised 2026-07-02, CAL-930)
- **Source:** proposal the `harden-loop-layer` proposal (settled; removed from the tree by #547, kept in git history) (WS3); CAL-908, corrected by CAL-930.

This is the first record in `specs/decisions/`. Design docs still live in `specs/`; this directory holds discrete architecture decisions from here on.

## Context

`/harness routine build` is not just a harness invocation — read honestly, it is a **loop**: it discovers its own work off the Linear queue, runs unattended, and feeds itself across runs via Linear and the ledger. The *Loop Engineering* field study is blunt that the overnight sweep belongs somewhere that stays awake, because "laptops get their lids closed."

WS3's corrected technical finding (still true) is that the harness's own loop has **no hard technical blocker to running off-machine**: the full gate (`scripts/verify.sh`) runs green on `ubuntu-latest` in CI, there are zero Xcode/Swift/macOS/Homebrew dependencies, the verbs run in-process off the native `harness` console script (`pyproject` `[project.scripts]`, no Docker-in-Docker), and the credential reads already come from the process environment (`harness/linear.py` reads `LINEAR_API_KEY` from `os.environ`). So a cloud substrate is *possible*.

The first cut of this ADR (CAL-908) over-read that finding and made a **GitHub Actions workflow the primary substrate**. CAL-930 corrects that — see the decision below and the rejected-alternatives section for why.

## Decision

**The harness's own Build/Quality loop runs always-on local by default** — the operator's local scheduled task `~/.claude/scheduled-tasks/harness-work-pull`, which invokes the versioned `/harness routine build` (see `RUNBOOK.md`). This is the active, working path today and costs nothing per run.

**A cloud substrate is optional and deferred.** If lids-close autonomy is ever needed off-machine, the recorded path is a **Claude cloud routine** (`/schedule`) driving the same versioned `/harness routine build` — billed as Claude usage, not as CI minutes. It reuses everything the local loop uses: the native entry point, `LINEAR_API_KEY` as an environment secret, the Claude review engine, and the Linear-keyed reclaim pre-flight (which reconciles a fresh clone with no local ledger). It is not built here; standing it up is out of scope.

### Why always-on local is the default

- **It already works** — `harness-work-pull` (and the sibling `ios-work-pull`) drive `/harness routine build` on a local schedule today, at zero marginal cost.
- **The device is effectively always on** for the operator's workflow, so the "laptops get their lids closed" hazard is weak in practice — and that hazard was the cloud's whole justification.
- **No credential re-plumbing, no substrate risk** — the local Docker wrapper already sources `LINEAR_API_KEY` and Claude auth; the loop is proven end-to-end there.

## Rejected alternative: GitHub Actions

CAL-908 chose a GitHub Actions workflow as the primary substrate. **CAL-930 rejects it**, for cost and fit:

- **Cost.** This repo is **private**, so Actions minutes are metered (~2,000/month on the free tier — there is no Pro subscription). The loop is a **long-lived agent run** — clone → build → Claude review → close, ~30–90 min of wall-clock *per ticket* — and Actions bills that entire wall-clock. Nightly runs would eat or blow the monthly minute budget. The original reasoning conflated this with CI running the **gate** (a ~24-second pytest pass), which is a completely different, cheap workload: "the gate runs green on `ubuntu-latest` in CI" does **not** imply "running the whole loop on Actions is cheap."
- **Fit.** GitHub Actions is designed for short, bounded CI jobs, not multi-hour interactive agent sessions.
- **Prior decision.** The four-loops operating model already had the loops running as Claude cloud Routines, not GitHub Actions; the Actions choice diverged from that without cause.

The versioning argument for Actions (the schedule lives in-repo) does not outweigh the cost/fit problems, and it is partly recoverable anyway — a Claude routine's prompt is the versioned `/harness routine build`, and its setup can be documented in the repo.

## The per-target-repo gate rule (retained, substrate-independent)

**"The harness's own loop can run off-machine" must not be read as "the harness can run any repo off-machine."**

The harness is infrastructure other repos self-host. Its *own* loop is off-machine-viable because *its own gate* has no macOS dependency. Viability for a **self-hosting target repo** is set by **that target's gate**, not by the harness's auth:

- A target whose gate needs Xcode / Swift / macOS tooling (e.g. an iOS repo) **stays local, or runs on a `macos-latest` runner.**
- A target with a Linux-clean gate can adopt the same pattern.

Cloud-enabling self-hosting target repos is **out of scope** for this decision.

## Consequences

- **No cloud dependency and no metered-minute exposure.** The loop runs on the always-on device via the existing local trigger; nothing bills against GitHub Actions.
- **Lids-close autonomy is deferred, not designed out.** If the device ever stops being always-on, the recorded next step is a Claude cloud routine (above) — not GitHub Actions.
- **The cloud loop would review via Claude, not Codex** (recorded for when the option is taken): Codex's `~/.codex` subscription auth does not travel as a secret and is bwrap-blocked in-container anyway (CAL-866), so an off-machine loop uses the Claude review engine. That forgoes the model-*family* diversity a local Codex reviewer gives — acceptable, but tracked against the generator/evaluator principle; a local `--engine codex` pass remains the way to get family diversity. (ADR [0013](0013-codex-engines-in-container.md) amends the in-container half of this: the bwrap wall is a seccomp profile, not a privilege grant. The auth half — subscription credentials that do not travel as a secret — is untouched, so the cloud-loop conclusion here stands on its own.)
