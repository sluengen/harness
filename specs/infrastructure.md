---
spec: infrastructure
last_updated: 2026-08-19
---

# Infrastructure

The operational reality of the harness — repository, CI, packaging, and the credentials a run needs. The source of truth when making a deployment or configuration decision. A **reference spec** (`spec-authoring`): update it when the infrastructure changes, not per task.

The harness is self-hosted developer infrastructure: it has **no end-users and no product hosting**. It runs on a contributor's machine and in GitHub Actions CI. Its one public network surface is a **static documentation page** — the repo-guide (`docs/index.html`) served via GitHub Pages (see Hosting / services). Rows that do not apply are marked N/A rather than invented.

ADR 0015 retires the runtime, and with it everything that had to be deployed: the Docker image, the `~/bin/harness` wrapper, the native console-script install, and the GHCR publish path. There is no artifact to ship — the repo is a checkout that runs a gate, so "hosting" now means CI and the documentation page, and nothing else.

## Branch topology

**Two roles: `dev` (integration) → `main` (release).** Feature branches base from and merge back to `dev`; the nightly promotion carries `dev → main`. There is no `staging` role in this repo.

> **2026-08-19 — the nightly promotes by pull request (ADR 0003 as amended 2026-08-19, #485).** `main` is protected and requires a pull request, so `github-actions[bot]` cannot update `refs/heads/main`: every scheduled run was refused with GH006, and the job below had never once succeeded. The nightly now opens — or reuses — a pull request whose head is `dev` itself, waits for the required `lint-and-test` check on the gated commit, and merges it through the API with a server-side head-SHA match. **The discipline is unchanged where it can be**: gate on the exact candidate; the tree that lands equals the tree that was gated; never force, never repair, never resolve a conflict; a refused night leaves the pull request open rather than fixing anything. **What changes is the invariant's shape** — fast-forward-only publishing is retired in favour of tree identity, because a pull-request merge necessarily puts a merge commit on `main` that `dev` does not contain. That divergence is **empty by construction** (`tree(main) == tree(the last promoted candidate)`), and this repo therefore **does not back-merge** — a named departure from the generic rule in the `infrastructure` skill ("after the release hop, back-merge"), which exists for a release branch that gains *content*; back-merging here would put an empty merge commit on `dev` every night. A `main` that ever gains real content is caught by the promotion's own pre-condition and stops the job.

> **2026-08-18 — staging retired (ADR 0003 as amended by ADR 0017 D6).** `staging` was a deployment concept, and this repo deploys nothing: after ADR 0015 the middle hop had become a third gate run and a third merge verifying the same trees, so this repo's topology is recorded as `dev → main`. The promotion discipline is unchanged — gate on the exact candidate, fast-forward or nothing, never a merge, force, or repair — but **the release hop is now what the nightly advances: on a green gate, the nightly advances `main` unattended** *(as a fast-forward when this was written; by an API merge of its own pull request since 2026-08-19 — see the note above. What the nightly advances did not change; how it lands did.)* That is what `dev → main` promotion means here, and it is a deliberate departure from the generic default in the `infrastructure` skill ("unattended automation never advances release"): the recorded decision *is* the deliberateness, per ADR 0003's amendment. The `staging` branch still exists on the remote; deleting it is an operator action, not part of this record. Repos that ship to staging environments keep all three roles.

## Domains

N/A — no owned or custom domains. The documentation page is served from the GitHub Pages **default host**, `https://sluengen.github.io/harness/` (no custom domain — decided, CAL-1201).

## Hosting / services

| Service | Platform | Source | Notes |
|---|---|---|---|
| CI (verification gate) | GitHub Actions | `.github/workflows/ci.yml` | `lint-and-test` runs `scripts/verify.sh` — the canonical gate, whose current stage list is the script itself — on pushes to `main` and `dev`, and on pull requests into `dev`. The `push: dev` trigger verifies each merged state and catches merge skew between concurrently-landed changes; pull requests into `main` deliberately raise no run (see **Branch topology** — a bot-opened promotion pull request would get an approval-gated duplicate nothing unattended can approve). This row describes what is *configured*: what a merge performed by the Actions token itself raises is a separate, unsettled question (#485). `ubuntu-latest`, `uv`, Python 3.11, 20-minute job timeout |
| CI (nightly promotion) | GitHub Actions | `.github/workflows/nightly-promotion.yml` | Runs the gate on `dev` at 14:00 UTC and, only on green, opens or reuses a `dev → main` pull request and merges it once the required check on the gated commit is green (see **Branch topology**). The logic is `scripts/promotion-step.sh`, not a `run:` block, so it is executed by a test rather than read (`specs/architecture-principles.md`). It never forces, repairs, or resolves a conflict; it stops and reports when the gate is red, when `main` carries content `dev` does not, when `dev` moved past the gated commit, when the required check failed or never completed, when no open pull request is reusable, or when the merge's tree is not the gated one. A night with nothing to promote exits clean without spending the gate |
| Local execution | A checkout | repo root | `uv sync --extra dev`, then `bash scripts/verify.sh`. There is nothing to install — ADR 0015 retires the CLI, so no image, wrapper, or console script is deployed |
| Container registry | N/A | — | No published artifact. The image and its GHCR publish workflow are retired (ADR 0015) |
| Repo-guide docs page | GitHub Pages (deploy from branch) | `docs/index.html` | Public static landing page at `https://sluengen.github.io/harness/`, deployed from `main` `/docs`. Shareable via Open-Graph/Twitter meta + favicon. See **Public documentation page** below (CAL-1201) |

### Public documentation page

The repo-guide (`docs/index.html`, authored under CAL-1200) is hosted as the harness landing page via **GitHub Pages** — *deploy from branch*, `main` `/docs`, at the default host `https://sluengen.github.io/harness/`. No custom domain (decided). The README stays the canonical text front door; the page is its **visual companion**, linked from the top of the README. Enabling Pages is a one-time operator repo-settings action (Settings → Pages → Deploy from branch → `main` `/docs`).

**Exposure & cadence.** `docs/` on `main` is **world-readable** (the repo is public — CAL-1029), so anything committed under `docs/` is published. The page updates when the nightly's merge lands on `main` — **provided** GitHub's branch-based Pages build fires for a merge performed by the Actions token, which is **unverified as of 2026-08-19** and is being settled by observation on the first runs (#485). If it does not fire, the page stops updating until a build is requested explicitly; nothing else about the promotion changes.

## Repository

| Repo | Visibility | URL |
|---|---|---|
| sluengen/harness | public | git@github.com:sluengen/harness.git |

Branch model: feature branches base from and merge back to `dev` (integration); the nightly promotion moves `dev → main` (`CLAUDE.md` `branches:`, and **Branch topology** above). `dev` dogfoods, `main` releases (merge-guidance-into-harness decision D7).

## Accounts / external services

| Service | Used for | Managed where |
|---|---|---|
| Anthropic / Claude Code | The orchestrating + implementing agent | OAuth token (see Secrets) |
| OpenAI Codex | The reviewer behind `/build --engine codex` | Subscription auth via `~/.codex` on the host; invoked by the agent, never by this repo |
| GitHub | Code hosting, CI, and the issue tracker | `sluengen/harness`; issues + the Projects v2 board `sluengen/2` |

## Secrets

Nothing in this repo reads a *stored* credential. The `LINEAR_API_KEY` row that used to sit here belonged to the verbs, which fetched and transitioned tickets through Linear's GraphQL API; ADR 0015 deleted them, and this repo's tracker is GitHub (`CLAUDE.md` `tracker:`). What remains is the credentials the *agent host* needs, listed so an operator knows what to have in place — read from the environment or the OS keystore at invocation, **never committed or logged**, with `.env` gitignored and values living only on the host.

| Secret | Unlocks | Where it lives |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code auth in a non-interactive context | The host environment; interactive use reads `~/.claude/` and needs no variable |
| Codex subscription auth | The Codex reviewer | `~/.codex` on the host |
| `GH_TOKEN` | The nightly promotion's pull-request create/merge and its check reads | The job-scoped `secrets.GITHUB_TOKEN`, forwarded to that one step by `nightly-promotion.yml`. Actions-issued and ephemeral — not a PAT, never stored, never logged |

Every credential is now read from the host directly. ADR 0015 retires the container that used to receive them by mount and the `~/bin/harness` wrapper that extracted the Keychain token to hand it over, so there is no assembly step left to document.
