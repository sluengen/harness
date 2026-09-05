@AGENTS.md

<!--
`AGENTS.md` is the source instruction file and the one both hosts read (#537).
This file exists so Claude Code loads it and so Claude-specific deltas have a
home; everything shared lives there, and nothing is restated here. Configuration
is `harness.yaml`.
-->

# Claude Code deltas

Nothing in `AGENTS.md` is repeated below. These are the differences that apply on
this host alone.

- **Slash commands are skills.** Each of the nine lifecycle workflows ships once,
  as a skill under `skills/`, so one artefact serves both hosts. Seven carry
  `disable-model-invocation: true` and are yours to trigger; `build` and `review`
  stay model-invocable because `/routine` drives `/build` and `/build` drives the
  review stage, and the flag would break that composition.
- **Hooks.** `hooks/hooks.json` registers the six guards at install; no per-repo
  wiring. Permissions and the unattended authorisations live in
  `settings/harness.json`.
- **Sub-agents.** `agents/` defines the four roles Claude Code dispatches. Codex
  reads its own equivalents from `.codex/agents/`.
