---
spec: infrastructure
last_updated: 2026-07-21
---

# Infrastructure

The operational reality of the harness — repository, CI, packaging, and the credentials a run needs. The source of truth when making a deployment or configuration decision. A **reference spec** (`spec-authoring`): update it when the infrastructure changes, not per task.

The harness is self-hosted developer infrastructure: it has **no end-users and no product hosting**. It runs on a contributor's machine (Docker wrapper or native install) and in GitHub Actions CI. Its one public network surface is a **static documentation page** — the repo-guide (`docs/index.html`) served via GitHub Pages (see Hosting / services). Rows that do not apply are marked N/A rather than invented.

## Domains

N/A — no owned or custom domains. The documentation page is served from the GitHub Pages **default host**, `https://sluengen.github.io/harness/` (no custom domain — decided, CAL-1201).

## Hosting / services

| Service | Platform | Source | Notes |
|---|---|---|---|
| CI (verification gate) | GitHub Actions | `.github/workflows/ci.yml` | `lint-and-test` runs `scripts/verify.sh` (ruff → mypy → pytest → CLI smoke → landing-page drift guard → design-token drift guard → changelog fragment guard → release-cadence report) on push/PR to `main` and `dev`. The `push: dev` trigger verifies each merged state (incl. the close verb's direct pushes) and catches merge skew between concurrently-landed runs. `ubuntu-latest`, `uv`, Python 3.11, 20-minute job timeout |
| CI (release cadence) | GitHub Actions | `.github/workflows/ci.yml` | `release-cadence` runs `scripts/cadence.py check` **only** on a PR into `main` — the release (#350). Its own job, not a step in `lint-and-test`, so a cadence breach (an overdue release) blocks the release without halting unrelated changes; the gate merely reports the same bounds. 5-minute job timeout |
| Local execution (primary) | Docker — the `~/bin/harness` wrapper | `docker/` | Builds the `harness:dev` image; mounts CWD as `/workspace`; each verb is a one-shot `docker run`. See `docker/README.md` |
| Local execution (alternate) | Native — `uv tool install .` | repo root | Installs the `harness` console script on PATH; credentials must be set manually. Use when Docker is unavailable |
| Container registry | — | — | Not yet published; the image is built locally as `harness:dev` (override with `HARNESS_IMAGE`). GHCR publish is tracked in **CAL-623** |
| Repo-guide docs page | GitHub Pages (deploy from branch) | `docs/index.html` | Public static landing page at `https://sluengen.github.io/harness/`, deployed from `main` `/docs`. Shareable via Open-Graph/Twitter meta + favicon. See **Public documentation page** below (CAL-1201) |

### Public documentation page

The repo-guide (`docs/index.html`, authored under CAL-1200) is hosted as the harness landing page via **GitHub Pages** — *deploy from branch*, `main` `/docs`, at the default host `https://sluengen.github.io/harness/`. No custom domain (decided). The README stays the canonical text front door; the page is its **visual companion**, linked from the top of the README. Enabling Pages is a one-time operator repo-settings action (Settings → Pages → Deploy from branch → `main` `/docs`).

**Exposure & cadence.** `docs/` on `main` is **world-readable** (the repo is public — CAL-1029), so anything committed under `docs/` is published. The page only updates on a `dev → staging → main` release (`RELEASING.md`), so the hosted page lags `dev` by one release — an authored change to `docs/index.html` on `dev` is not live until the next release carries it to `main`.

## Repository

| Repo | Visibility | URL |
|---|---|---|
| sluengen/harness | public | git@github.com:sluengen/harness.git |

Branch model: feature branches base from and merge back to `dev` (integration); releases are PRs `dev → main` (`CONTEXT.md`, `RELEASING.md`). Guidance is distributed branch-based — `dev` dogfoods, `main` releases (merge-guidance-into-harness decision D7).

## Accounts / external services

| Service | Used for | Managed where |
|---|---|---|
| Linear | Issue tracking and the change-spec home | Team **CAL**, project **Harness v3**; GraphQL API only — no CLI |
| Anthropic / Claude Code | The orchestrating + implementing agent | OAuth token (see Secrets) |
| OpenAI Codex | The `review` verb's reviewer | Subscription auth via `~/.codex`, mounted into the review container |
| GitHub | Code hosting, CI, tag-based releases | `sluengen/harness`; release process in `RELEASING.md` |

## Secrets

Credentials are read from the environment or the OS keystore at run time and are **never committed or logged** — `.env` is gitignored and values live only on the host.

| Secret | Unlocks | Where it lives |
|---|---|---|
| `LINEAR_API_KEY` | The Linear GraphQL API | `.env` at the repo root |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code auth inside the container | Extracted from the macOS Keychain by the `~/bin/harness` wrapper |
| Codex subscription auth | The `review` verb (Codex) | `~/.codex`, mounted into the review container |

See `docker/README.md` for how the wrapper assembles these for a containerised run, and the **Gotchas** in `CONTEXT.md` for host-specific credential handling (e.g. this host has no ssh-agent forwarding, so container pushes use a tokenised-HTTPS remote).
