<!-- guidance:template-context@0.1.7 -->
# CONTEXT.md

Agent-facing context for **{repo name}**. This is the one file allowed to name this repo. The guidance files (skills, agents, commands) are universal and point here for everything repo-specific: stack, commands, paths, tools, and principles.

`README.md` is for humans. This is for agents. Read it first.

<!-- The block below is structured so the pipeline harness can parse and inject it.
     Keep it accurate; agents and tooling both rely on it. -->
```yaml
profile: harness               # the single registry profile (one surface); repo type is set by layers below, not by a profile
visibility: committed          # committed (all guidance in git; enables cloud execution; default private) | local (only this file in git; internals bootstrapped locally; default public)
repo:
  name: {repo name}
  linear: {Linear workspace/team — or 'none' for the rare repo not on Linear}
# Layers carry repo-type variation — what the retired standard/harness profiles'
# `default_layers` used to encode is now per-repo config here. A product repo:
# feature_specs: true (+ design_system: true if it has one). An infra / pipeline
# repo: both false (design-doc / SPEC.md is the as-built record).
layers:                        # which optional guidance layers this repo uses
  linear: true                 # the standard; set false only if this repo is not on Linear
  design_system: false         # on → frontend uses the design system; engages the design-system skill (ux-design applies to any user-facing surface regardless)
  feature_specs: true          # on → as-built record is specs/features/ via templates/feature.md; off → design doc / SPEC.md
stack:
  language: {e.g. Python 3.11 / TypeScript}
  framework: {e.g. FastAPI / React}
commands:
  install: "{e.g. uv sync}"
  lint:    "{e.g. ruff check .}"
  typecheck: "{e.g. mypy . — or omit}"
  test:    "{e.g. pytest}"
  test_one: "{e.g. pytest path::test_name}"
  verify:  "{the canonical combined gate, if the repo has one — e.g. bash scripts/verify.sh — or omit}"
  run:     "{e.g. docker compose up}"
branches:
  integration: {e.g. dev}      # feature branches base from and merge here
  release: {e.g. main}         # how production is fed
conventions:
  commit_format: "{e.g. type(scope): description — feat/fix/chore/docs/refactor/test — or omit}"
tools:
  linear_cli: "{exact invocation, e.g. python -m tools.linear — or 'GraphQL via curl'}"
  # Linear workspace/team IDs and label IDs live here, not in the linear-sync skill
paths:
  source: {e.g. app/}
  tests: {e.g. tests/}
  proposals: specs/proposals/       # proposal specs (pre-Linear, unconfirmed/large ideas)
  feature_specs: specs/features/    # canonical, as-built feature specs (decisions embedded inline)
  infrastructure: {e.g. specs/infrastructure.md — or omit}   # reference spec
  architecture: {e.g. specs/architecture.md — or omit}       # architecture-principles reference spec (cross-cutting decisions live here)
  design_system: {path or external repo — or omit}
env:
  file: {e.g. .env}            # file to source before Linear/tooling; MUST be gitignored, never committed
  linear_token: LINEAR_API_KEY # the var holding the Linear API token; omit only if linear: false
```

## What this repo is

{Two or three sentences: the product or system, who it serves, the shape of it. The thing an agent needs to hold in its head before designing a change. State it plainly (writing-quality).}

## Architecture

{The big picture that takes reading several files to reconstruct: the main components, how they talk, the layer boundaries this repo enforces, the non-obvious decisions. Keep it to what an agent cannot discover quickly by reading the tree.}

## Repo-specific principles

{A brief summary of the conventions a design is held to here that extend `engineering-principles`. Example: "the API owns all domain logic; clients never compute it." For a repo with rich architecture conventions, keep the full set in the architecture-principles spec (above) and point to it here. A principle that contradicts a universal one is itself a recorded decision. Omit if none.}

## Where deeper truth lives

- **What the product does today, and why** → `specs/features/` (decisions embedded inline)
- **Ideas not yet confirmed** → `specs/proposals/`
- **How the system is built / cross-cutting decisions** → architecture-principles spec (if any)
- **Operational reality** → infrastructure spec (if any)
- **{Design system, if any}** → `{path or repo}`
- **Linear (issues / in-flight work)** → {workspace link}

## Gotchas

{The handful of things that bite every newcomer: a non-obvious build step, a value returned as a string, an auth quirk. Keep it short and real. Omit if none.}
