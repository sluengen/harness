<!-- guidance:template-context@0.1.18 -->
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
  linear: {Linear workspace/team — or 'none' for the rare repo not on Linear (then set tracker: none below). The tracker address; read only when tracker: linear}
  project: {optional — the project the /harness routine loops scope to; omit to run the whole tracker queue}
  # repo.project is OPTIONAL (proposal optional-project-scope, D3 — absence is the
  # signal; there is no `all` sentinel). Set → the /harness routine loops scope to
  # that one project; omit → they work the whole tracker queue. What "unscoped"
  # means per backend: tracker: linear → the team named in repo.linear; tracker:
  # github → the board (already the full queue, so omitting it is a no-op there).
  # Only relevant if this repo self-hosts the harness routine loops.
tracker: linear                # single source of truth for the tracker: linear | github | none. The switch the harness engine reads: none → the verbs run tracker-less (no LINEAR_API_KEY, no fetch, no transitions) and `start <id>` takes an opaque run identifier. Coupled to repo.linear above (linear needs an address; none forbids one); an inconsistent pair is rejected.
# For tracker: github (the GitHub Projects v2 backend), set tracker:
# github above, set repo.linear: none (the Linear address is unused), and add the
# github: block below — a top-level key naming the issues repo and the board. It
# is required when tracker: github (repo + project both) and ignored otherwise, so
# it lives commented here. Uncomment and fill it:
# github:
#   repo: owner/name           # the issues repository (owner/name)
#   project: owner/number      # the Projects v2 board (owner/number)
#   status_field: Status       # optional — the board's single-select status field; omit → the built-in "Status"
# Layers carry repo-type variation — what the retired standard/harness profiles'
# `default_layers` used to encode is now per-repo config here. A product repo:
# feature_specs: true (+ design_system: true if it has one). An infra / pipeline
# repo: both false (design-doc / SPEC.md is the as-built record).
layers:                        # which optional guidance layers this repo uses
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
# The autonomous loop's spend bounds, read by the harness engine. Values are
# bare integers, never {e.g. …} placeholders — the reader matches digits only, so
# a placeholder silently falls back to the code default while reading to a human
# as though it were set. Shipped equal to those defaults, so deleting a line
# changes nothing until you retune it. Only relevant if this repo self-hosts the
# harness routine loops.
loop:
  max_review_cycles: 5           # how many review→fix cycles a run may SPEND — the review after them is refused. The stop policy these numbers tune lives in `skills/review-discipline/SKILL.md`; this block is only its numbers.
  unconditional_review_cycles: 3 # how many of those run with no convergence judgment required. Keep it at or below `max_review_cycles`; the loader clamps rather than erroring.
  wall_clock_budget_minutes: 110 # the longest a legitimate **unattended** run may take — since ADR 0011 it bounds that mode alone, an attended run being bounded by the operator and, for reclamation, by `attended_idle_minutes` below. ALSO `harness reclaim --stale`'s staleness threshold for an unattended run — one quantity seen from two directions (a run refused at review but spared reclamation would be alive on the board and unable to finish), so this single line moves both.
  attended_idle_minutes: 480     # `harness reclaim --stale`'s staleness threshold for a run started `--attended`. A longer threshold, not an exemption: a session paused on a question to the operator touches none of the liveness clocks, so the wall clock above would revert its ticket underneath them — while a session abandoned overnight is still reclaimed by morning. Keep it at or above `wall_clock_budget_minutes`.
  untracked_file_limit: 1000     # how far past its own git index a run worktree may drift before `harness review` refuses to spawn an engine over it — a worktree carrying thousands of untracked files (a stray `.venv`, a build tree) drowns the review engine's tool use, and the observed signature is a review that burns the whole `engine_timeout_seconds` ceiling and returns `engine_timeout` having reviewed nothing. The refusal is instant and costs no review cycle. Coarse on purpose: raise it if your gate legitimately leaves a large untracked tree in the worktree, or set `0` to disable the check entirely.
  engine_timeout_seconds: 720    # per-subprocess ceiling for BOTH engines, review and design — a hung engine is killed and surfaced as an infra failure (exit 3, reason=engine_timeout) instead of hanging the verb. Raise it if a legitimately slow design is being killed; sit it at or below any external ops kill so the clean exit wins.
  probe_max_entries: 3           # how many mutations `harness review`'s probe stage may run per review (#363): the engine proposes edits to the code under review, each is applied to a throwaway worktree at the reviewed SHA and the suite is run against it, and a survivor comes back as a finding. A mutation table certifies only what its author thought to mutate, and the author is the person being reviewed. Costs one baseline suite run plus one per entry, so keep it small; set `0` to disable the stage entirely.
  probe_budget_seconds: 720      # ceiling on that probe subprocess, clamped to `engine_timeout_seconds` above — one review's added cost can never exceed one engine's ceiling. Lower it if probing is eating the loop; do NOT raise `engine_timeout_seconds` to buy a probe more time.
  review_model: opus            # the alias the claude review engine runs on, for every ticket (#321). Not a bound like the keys above — one value, one edit to change, and read as a **plain string alias, not a two-value enum**: an enum makes a third alias a code change and coerces a typo to the default, hiding an operator's mistake behind a review that quietly ran the wrong model. An unrecognized alias reaches the claude CLI and fails loudly there. `harness review --model <alias>` still overrides it for host/testing. `DEFAULT_REVIEW_MODEL` carries the same alias in lockstep, so a repo with no `loop:` block runs it too (#291). **Moved sonnet -> opus on 2026-08-08, as an interim operator decision while the review-verb timing work is in flight.** It replaced ADR 0005's per-ticket `review:<tier>` label (#321), which was never once set; `sonnet` was that recorded behaviour kept deliberately, on observational evidence (fail rate 17.3% vs 18.4% pre-#177) across a boundary where the builder, the guidance and the design verb all changed too. What is NOT claimed for this move is a timing benefit: measured the same day, opus reviews average **599s (n=4)** against sonnet's **475s (n=58)**, so on `engine_timeout_seconds` above this *increases* exposure to the ceiling rather than relieving it — the ledger's own signal is that successful reviews since 2026-08-04 run to a q3 of 633s and a max of 708s against that 720s ceiling, which is the saturation the timing work addresses. The case for opus here is verdict quality on a repo this size, not latency: on #352 it returned two blocking findings — a migration ordering defect that broke every verb against an existing ledger, and a containment regression whose own test stayed green — where the cheaper model had returned nothing.
conventions:
  commit_format: "{e.g. type(scope): description — feat/fix/chore/docs/refactor/test — or omit}"
tools:
  linear_cli: "{exact invocation, e.g. python -m tools.linear — or 'GraphQL via curl'}"   # tracker: linear only
  # Custom/renamed-state UUID overrides live here; the linear skill resolves standard states by type at runtime
paths:
  source: {e.g. app/}
  tests: {e.g. tests/}
  proposals: specs/proposals/       # proposal specs (pre-Linear, unconfirmed/large ideas)
  feature_specs: specs/features/    # canonical, as-built feature specs (decisions embedded inline)
  infrastructure: {e.g. specs/infrastructure.md — or omit}   # reference spec
  architecture: {e.g. specs/architecture.md — or omit}       # architecture-principles reference spec (cross-cutting decisions live here, unless one clears the bar stated on `decisions:` below)
  decisions: {e.g. specs/decisions/ — or omit}               # optional, repo-relative: a directory of architecture decision records. Declaring it IS the switch — there is no strategy setting. Declare it only for decisions that are cross-cutting, consequential and expensive to reverse (branch topology, tracker architecture, security posture, certification invariants); omit it and every decision is embedded in the spec it governs, which is the default. The architecture index above owns placement, numbering and supersession for it
  design_system: {path or external repo — or omit}
# Optional. Gravity-well files where state/branching/rendering accumulate — when a
# planned or actual diff touches one, the change spec and the review carry a
# `Watchlist trigger` section (a small behavior-preserving seam extraction, or a
# recorded deferral with a reason). Repo-owned and preserved across guidance
# updates (/update-guidance never touches CONTEXT.md); omit it and the trigger is
# a no-op. Paths are repo-relative; globs allowed. See the `architecture` skill.
architecture_watchlist:               # optional — omit entirely if this repo opts out
  files:
    - {e.g. app/screens/BigScreen.tsx}
    - {e.g. src/orchestrator/*.py}
env:
  file: {e.g. .env}            # file to source before tracker/tooling calls; MUST be gitignored, never committed
  linear_token: LINEAR_API_KEY # tracker: linear only — the var holding the Linear API token; read from the environment/.env, never from CONTEXT.md; omit unless tracker: linear
  github_token: GITHUB_TOKEN   # tracker: github only — the var holding the GitHub token (repo + project scopes); read from the environment/.env, never from CONTEXT.md; omit unless tracker: github
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
