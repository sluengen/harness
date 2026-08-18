---
name: infrastructure
description: Use when moving work between environments or role branches — promotion, release, CI/CD, and what a gate means at each boundary. The operate leg of the triad — the generic discipline; the repo's actual topology, environments, and services live in its infrastructure reference spec.
---
# Infrastructure

How work moves through environments here — the discipline `/promote` and the release automation follow. This is the *how*; the *what* — this repo's actual branch topology, environments, domains, and services — is the repo-owned infrastructure reference spec (`paths` in `CLAUDE.md`, conventionally `specs/infrastructure.md`), seeded by `/harness:init` and updated when the infrastructure changes, not per task.

## Roles, not names

`CLAUDE.md` → `branches:` declares the repo's role branches. The common roles: **integration** (feature branches base from it and merge back to it), optionally **staging** (a stabilized candidate, meaningful only where something deploys to a staging environment), and **release** (the intentional release line). Topology is per-repo configuration (ADR 0003 as amended): a repo with staging environments runs three roles; a repo that deploys nothing runs integration → release. The hooks protect every branch named in the block, whatever its role.

## The gate decides, at every boundary

Only a green gate advances a role branch — the same gate, the same marker, at every hop.

- **Merge on a candidate, never on the target.** Promotion merges the source into a candidate branched from the target, runs the gate on the candidate, and advances the target only on green. Nothing lands on a role branch until the gate has passed on exactly what would land.
- **Fast-forward-only publishing.** The target moves only as a fast-forward, checked locally and enforced again by the server. Nothing is repaired, merged in place, or forced: a red gate or a non-fast-forward stops the run and reports.
- **The release hop is deliberate — and by default that means attended.** The default: advancing the release branch is a human or reviewed act (a PR, or an operator-driven `/promote`), and unattended automation advances only the earlier hops on green. A repo's recorded topology decision may override the default — an entry in its infrastructure reference spec stating that an unattended promotion advances release, and under what discipline — because the recorded decision is itself the deliberateness the rule asks for. The live example is this plugin's own source repo: its nightly fast-forwards `dev → main` on a green gate, recorded as its topology's first entry. Absent such a record, the default stands.

## After the release hop, back-merge

When the release branch gains commits the integration branch does not have — a merge commit, a release-time version bump, a hotfix — merge release back into integration promptly. Skipping it makes every subsequent promotion carry a phantom divergence that eventually surfaces as a conflict on someone else's ticket. The back-merge is part of the release, not housekeeping to remember later.

## Release mechanics

A release is where the plugin's one version moves: bump at release, never per change (ADR 0017), with the changelog folded from commit bodies (ADR 0014 — the commit body *is* the entry). CI logic lives in scripts a test can execute, not in workflow `run:` blocks (`specs/architecture-principles.md`); the workflow calls the script and nothing more.

## When something goes wrong

A red gate on a candidate is a finding against the *source* branch — fix it there and re-promote; never patch the candidate. An infrastructure failure (missing toolchain, credentials, unclean base) is distinguished from a red tree by the gate's reserved exit code and stops the run without filing blame against the code.
