# harness

📖 **[Read the one-page guide →](https://sluengen.github.io/harness/)** — the operating model and the guidance at a glance. (This README stays the canonical text; the page is its visual companion.)

**A thin verification layer for agent-driven development**: a versioned set of
skills, agents, commands and hooks that tell an agent how work happens here, plus
a deterministic gate that decides whether a change is allowed to land.

> Let the agent do the judgement work; make the repo own the evidence.

An AI agent does everything that needs judgement — the design, the code, the
fixes, the decision about how to answer a review finding. This repo owns only the
parts that must not depend on an agent remembering them:

- **One verification gate.** `bash scripts/verify.sh` is the whole contract: lint,
  types, the test suite under a coverage floor, and the drift guards that hold
  generated artifacts to their sources. Green is the only evidence a completion
  claim may cite.
- **Executable guidance.** The skills, agents and commands that encode *how work
  happens here* are version-stamped, distributed from this repo, and — where they
  make a checkable claim — held by a test that reads the tree. A rule with a test
  is a bound; a rule in prose alone is advice.
- **Builder / recorder separation.** The agent that promises delivery is not the
  one that records it, which keeps the as-built record honest.
- **Mutation proof for new guards.** A test that was green the moment it was born
  has not been shown to measure anything. `scripts/mutate.py` is the instrument
  that proves it does.

It is **dogfooded on its own development**: every change here is built through the
same `/build` lifecycle, against the same gate, that the guidance publishes.

**Status:** v4 — a verification layer, no runtime. The earlier deterministic YAML
workflow engine was retired in CAL-574, and the verb model that replaced it (a
CLI, a SQLite run ledger, a Docker container and a close gate) was retired in
[ADR 0015](./specs/decisions/0015-harness-v4-thin-verification-layer.md). Their
as-built records are kept under [`specs/retired/`](./specs/retired/).

## Is this turnkey? No — it's dogfood infrastructure

**This is infrastructure one maintainer runs on their own machine, published to
read and adapt — not a turnkey product.** It assumes a particular setup — an
agent host, a GitHub tracker, this repo's own branch model — and nothing here is
packaged for installation: there is no image, no wrapper, and no console script
to put on PATH. Treat the whole repo as a worked example to **adapt to taste**,
not a dependency to install unchanged. The concepts — a gate that cannot be
talked around, the builder/recorder split, guards that read the tree — are the
portable part; the plumbing around them is not.

## What it does

A single agent session reads the ticket, writes the code and tests, hands the
result to an independent reviewer, and ships it. The repo contributes three
things to that loop and nothing else:

- **The process**, in [`CLAUDE.md`](./CLAUDE.md) (and its byte-identical
  `AGENTS.md` / `GEMINI.md` mirrors) plus [`CONTEXT.md`](./CONTEXT.md) — the
  lifecycle every agent follows, and this repo's own values for it.
- **The gate**, `bash scripts/verify.sh` — the one command whose output is
  evidence. It is the same command in CI, in a local checkout, and in the
  nightly `dev → staging` promotion.
- **The guards**, under `tests/` — roughly 1,300 tests, most of which read the
  tracked tree and fail when a document, a version stamp, or a generated
  artifact stops matching its source.

There are **no non-goals worth listing as absences** any more, but two are worth
stating because the repo used to do them: it runs no long-lived process and
schedules nothing of its own. What used to be a daemon and a cron is now a
command an operator or an agent host invokes.

## Quickstart

The honest minimum: clone it and run the gate.

```bash
git clone https://github.com/sluengen/harness.git harness
cd harness
uv sync --extra dev          # resolve the dev dependency group (needs uv)
bash scripts/verify.sh       # the canonical gate — lint, types, tests, drift guards
```

There is nothing to install. The repo is not a Python package: it has no console
script, no wheel, and no runtime dependencies.

## Driving a ticket

Work is agent-led and there is one way to drive it. Unattended, that is
`/build <TICKET>` — implement, verify, review, and ship, end to end. Attended, it
is the same lifecycle a step at a time: `/start → /review → /ship`. Both are
available in every repo on this guidance, and neither needs anything beyond the
agent host and this repo's own gate.

The full lifecycle, its load-bearing rules, and the skills that carry them are in
[`CLAUDE.md`](./CLAUDE.md).

## Repository layout

```
harness/
├── agents/        ← agent role definitions (dev, reviewer, architect, steward)
├── skills/        ← reusable skills (TDD, scope discipline, review discipline, …)
├── commands/      ← user-invocable slash commands (/build, /start, /review, /ship, …)
├── hooks/         ← agent-host hooks (guidance freshness, context monitor, push guards)
├── process/       ← the canonical process doc the root mirrors are generated from
├── templates/     ← the shapes specs, decisions and assessments are written in
├── specs/         ← design specs, decisions/ for ADRs, retired/ for superseded records
├── tests/         ← the guard suite
├── scripts/       ← the verify gate (scripts/verify.sh) and the mutation instrument
├── design/        ← the design system for docs/index.html
├── CONTEXT.md     ← agent-facing repo context (read first)
└── CLAUDE.md      ← the process, mirrored to AGENTS.md and GEMINI.md
```

`agents/`, `skills/`, `commands/` are agent-agnostic (plain markdown). Claude Code
sees them via symlinks under `.claude/`; the Codex adapters under `.codex/` are
generated from the same sources.

## Tech stack

Python 3.11+ (stdlib only) · pytest · ruff · mypy · uv

## Related

- **Design ancestry:** Inspired by [Archon](https://github.com/coleam00/Archon) (worktree-per-run, event log) and Anthropic's "build skills, not agents" guidance. Greenfield Python rewrite, not a fork.
- **Read first:** [`CONTEXT.md`](./CONTEXT.md) (agents) · [`CLAUDE.md`](./CLAUDE.md) (the process) · [`specs/decisions/`](./specs/decisions/) (why it is shaped this way).

## Contributing & security

Issues and pull requests are welcome and handled on a **best-effort** basis — this
is a single-maintainer, dogfood project. See [`CONTRIBUTING.md`](./CONTRIBUTING.md)
for the contribution stance. To report a security issue, do **not** open a public
issue — follow [`SECURITY.md`](./SECURITY.md) to disclose it privately.

## License

Two licences, split along what gets installed where:

- **This repo's own code** — the gate, the mutation instrument, the drift guards
  and the test suite — is **AGPL-3.0-only** ([`LICENSE`](./LICENSE)). Use it for
  anything, including commercially; a derivative you distribute or run as a
  network service carries the same freedoms. It cannot be taken proprietary.
- **The guidance** — the skills, agents, commands, templates, hooks, process doc
  and settings the installer copies into *your* repo — is **MIT**
  ([`GUIDANCE-MIT.md`](./GUIDANCE-MIT.md)). Install it into any repository,
  including a closed-source one, and it encumbers nothing.

The boundary is not hand-maintained prose: the `files:` block of
[`registry.yaml`](./registry.yaml) *is* the set the installer copies out, so it
defines what is MIT, and a test holds the two in correspondence.
