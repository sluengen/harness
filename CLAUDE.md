@AGENTS.md

# Claude Code deltas

Nothing in `AGENTS.md` is repeated below. These are the differences that apply on
this host alone.

- **Slash commands are skills.** Each of the nine lifecycle workflows ships once,
  as a skill under `skills/`, so one artefact serves both hosts. Three carry
  `disable-model-invocation: true` and are yours to trigger; `routine`, `build`,
  `review`, `drain`, `assess` and `promote` stay model-invocable because each
  answers to a caller that is not a human at a prompt — a scheduled run fires
  `/routine`, a work-pull run falls back to `/assess`, `/routine` drives `/build`
  and then `/promote`, `/build` drives the review stage, and `/assess` drives
  `/drain` — and the flag would refuse that caller (#564, #565, #627, #623).
  What keeps `/drain` at the keyboard, and `/promote`'s release hop deliberate,
  is the rule in each one's own body; the flag never enforced that for `/drain`'s
  predecessor either.
- **Hooks.** `hooks/hooks.json` registers the four guards at install; no per-repo
  wiring. Permissions and the unattended authorisations live in
  `settings/harness.json`.
- **Sub-agents.** `agents/` defines the five roles Claude Code dispatches. Codex
  reads its own equivalents from `.codex/agents/`.
  **Skills and agents are addressed differently, and only one is namespaced:** a
  plugin skill invokes as `/harness:<name>`, while an agent is dispatched by bare
  name in a flat list beside the host's own and beside whatever a consuming repo
  defines. So a skill needs no `harness-` prefix and an agent may earn one; the
  awkward `/harness:harness-<name>` only arises from confusing the two.
- **Proposal renderings.** `/propose` step 3 hands over a shareable rendering
  alongside the spec file, and here that rendering is an **Artifact**, so the
  operator reads and decides against it in the session instead of opening a path
  in the repo. The portable skill names no mechanism, because a host without one
  falls back to the file.
