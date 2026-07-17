---
spec: infrastructure
last_updated: 2026-06-13
---

# Infrastructure

The operational reality of the harness — repository, CI, packaging, and the credentials a run needs. The source of truth when making a deployment or configuration decision. A **reference spec** (`spec-authoring`): update it when the infrastructure changes, not per task.

The harness is self-hosted developer infrastructure: it has **no end-users, no public hosting, and no domains**. It runs on a contributor's machine (Docker wrapper or native install) and in GitHub Actions CI. Rows that do not apply are marked N/A rather than invented.

## Domains

N/A — the harness serves no network traffic and owns no domains.

## Hosting / services

| Service | Platform | Source | Notes |
|---|---|---|---|
| CI (verification gate) | GitHub Actions | `.github/workflows/ci.yml` | Runs `scripts/verify.sh` (ruff → mypy → pytest → CLI smoke) on push/PR to `main`. `ubuntu-latest`, `uv`, Python 3.11, 10-minute job timeout |
| Local execution (primary) | Docker — the `~/bin/harness` wrapper | `docker/` | Builds the `harness:dev` image; mounts CWD as `/workspace`; each verb is a one-shot `docker run`. See `docker/README.md` |
| Local execution (alternate) | Native — `uv tool install .` | repo root | Installs the `harness` console script on PATH; credentials must be set manually. Use when Docker is unavailable |
| Container registry | — | — | Not yet published; the image is built locally as `harness:dev` (override with `HARNESS_IMAGE`). GHCR publish is tracked in **CAL-623** |

## Repository

| Repo | Visibility | URL |
|---|---|---|
| sluengen/harness | private | git@github.com:sluengen/harness.git |

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
