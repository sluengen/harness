---
spec: infrastructure
last_updated: YYYY-MM-DD
---

# Infrastructure

The operational reality of this system — domains, hosting, services, accounts. The source of truth when making a deployment or configuration decision. A **reference spec** (`spec-authoring`): update it when the infrastructure changes, not per task.

## Domains

| Domain | Purpose | DNS / registrar |
|---|---|---|
| {example.com} | {what it serves} | {provider} |

## Hosting / services

| Service | Platform | Source | Notes |
|---|---|---|---|
| {e.g. landing page} | {e.g. GitHub Pages} | {dir / build} | {deploy trigger, e.g. push to main} |

## Repository

| Repo | Visibility | URL |
|---|---|---|
| {owner/name} | {public/private} | {url} |

## Accounts / external services

{Email, payment, analytics, error tracking, CI — what is used, where it is managed, and any account/owner notes. Omit rows that do not apply.}

## Secrets

{Where credentials live (the env file, the secret manager) and which services they unlock. Never the values themselves — those are gitignored / in the secret store.}
