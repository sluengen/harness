---
spec: infrastructure
last_updated: 2026-08-15
---

# Infrastructure

The operational reality of the harness — repository, CI, packaging, and the credentials a run needs. The source of truth when making a deployment or configuration decision. A **reference spec** (`spec-authoring`): update it when the infrastructure changes, not per task.

The harness is self-hosted developer infrastructure: it has **no end-users and no product hosting**. It runs on a contributor's machine and in GitHub Actions CI. Its one public network surface is a **static documentation page** — the repo-guide (`docs/index.html`) served via GitHub Pages (see Hosting / services). Rows that do not apply are marked N/A rather than invented.

ADR 0015 retires the runtime, and with it everything that had to be deployed: the Docker image, the `~/bin/harness` wrapper, the native console-script install, and the GHCR publish path. There is no artifact to ship — the repo is a checkout that runs a gate, so "hosting" now means CI and the documentation page, and nothing else.

## Domains

N/A — no owned or custom domains. The documentation page is served from the GitHub Pages **default host**, `https://sluengen.github.io/harness/` (no custom domain — decided, CAL-1201).

## Hosting / services

| Service | Platform | Source | Notes |
|---|---|---|---|
| CI (verification gate) | GitHub Actions | `.github/workflows/ci.yml` | `lint-and-test` runs `scripts/verify.sh` — the canonical gate, whose current stage list is the script itself — on push/PR to `main` and `dev`. The `push: dev` trigger verifies each merged state and catches merge skew between concurrently-landed changes. `ubuntu-latest`, `uv`, Python 3.11, 20-minute job timeout |
| CI (nightly promotion) | GitHub Actions | `.github/workflows/nightly-staging-promotion.yml` | Runs the gate on `dev` at 14:00 UTC and, only on green, fast-forwards `staging` to it. The logic is `scripts/promotion-step.sh`, not a `run:` block, so it is executed by a test rather than read (`specs/architecture-principles.md`). It never merges, forces, or repairs: a red gate or a non-fast-forward stops the job |
| Local execution | A checkout | repo root | `uv sync --extra dev`, then `bash scripts/verify.sh`. There is nothing to install — ADR 0015 retires the CLI, so no image, wrapper, or console script is deployed |
| Container registry | N/A | — | No published artifact. The image and its GHCR publish workflow are retired (ADR 0015) |
| Repo-guide docs page | GitHub Pages (deploy from branch) | `docs/index.html` | Public static landing page at `https://sluengen.github.io/harness/`, deployed from `main` `/docs`. Shareable via Open-Graph/Twitter meta + favicon. See **Public documentation page** below (CAL-1201) |

### Public documentation page

The repo-guide (`docs/index.html`, authored under CAL-1200) is hosted as the harness landing page via **GitHub Pages** — *deploy from branch*, `main` `/docs`, at the default host `https://sluengen.github.io/harness/`. No custom domain (decided). The README stays the canonical text front door; the page is its **visual companion**, linked from the top of the README. Enabling Pages is a one-time operator repo-settings action (Settings → Pages → Deploy from branch → `main` `/docs`).

**Exposure & cadence.** `docs/` on `main` is **world-readable** (the repo is public — CAL-1029), so anything committed under `docs/` is published. The page only updates when a release carries `dev` through to `main`, so the hosted page lags `dev` by one release — an authored change to `docs/index.html` on `dev` is not live until the next release carries it to `main`.

## Repository

| Repo | Visibility | URL |
|---|---|---|
| sluengen/harness | public | git@github.com:sluengen/harness.git |

Branch model: feature branches base from and merge back to `dev` (integration); releases move `dev → staging → main` (`CONTEXT.md` `branches:`). Guidance is distributed branch-based — `dev` dogfoods, `main` releases (merge-guidance-into-harness decision D7).

## Accounts / external services

| Service | Used for | Managed where |
|---|---|---|
| Anthropic / Claude Code | The orchestrating + implementing agent | OAuth token (see Secrets) |
| OpenAI Codex | The reviewer behind `/build --engine codex` | Subscription auth via `~/.codex` on the host; invoked by the agent, never by this repo |
| GitHub | Code hosting, CI, and the issue tracker | `sluengen/harness`; issues + the Projects v2 board `sluengen/2` |

## Secrets

Nothing in this repo reads a credential. The `LINEAR_API_KEY` row that used to sit here belonged to the verbs, which fetched and transitioned tickets through Linear's GraphQL API; ADR 0015 deleted them, and this repo's tracker is GitHub (`CONTEXT.md`). What remains is the credentials the *agent host* needs, listed so an operator knows what to have in place — read from the environment or the OS keystore at invocation, **never committed or logged**, with `.env` gitignored and values living only on the host.

| Secret | Unlocks | Where it lives |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code auth in a non-interactive context | The host environment; interactive use reads `~/.claude/` and needs no variable |
| Codex subscription auth | The Codex reviewer | `~/.codex` on the host |

Every credential is now read from the host directly. ADR 0015 retires the container that used to receive them by mount and the `~/bin/harness` wrapper that extracted the Keychain token to hand it over, so there is no assembly step left to document — see the **Gotchas** in `CONTEXT.md` for what remains host-specific.
