# Agent task: domain steward review

A short, agent-run procedure that replaces the retired `workflows/steward.yaml`
(CAL-574). It is a read-only review — no worktree, no code mutation — that
produces a structured report on one domain of the codebase. The deterministic
engine that walked the YAML is gone; the orchestrating Claude session now runs
these steps directly. The workflow was never wired into an automated trigger,
so no running behaviour is lost.

See also the role brief in `agents/system-steward.md` /
`agents/code-steward.md` for the standards a steward applies.

## When to run

When you want a structured, systemic read on one domain — to surface recurring
patterns and systemic issues rather than line-level nits.

## Inputs

- `domain` — one of `architecture`, `harness`, `test`, `code`, `design`.

## Steps

### 1. Read the domain and produce a summary

Read the codebase for the chosen `domain` (use Read / Grep / Glob / Bash, all
read-only) and produce:

- `summary` — a structured summary of the domain.
- `key_files` — the files that anchor it.
- `open_questions` — what is unclear or undecided.

### 2. Assess

Against the `domain` principles, identify recurring patterns and systemic
issues and produce:

- `findings` — a list of `{severity, area, description}`.
- `systemic_insights` — cross-cutting observations.

### 3. Write the report

Write a structured markdown report capturing the summary, key files, open
questions, findings, and systemic insights to a `steward-<domain>-<date>.md`
file under the repo root. Print the `report_path`.

## Done when

The report file exists and contains the summary, findings, and systemic
insights for the requested domain.
