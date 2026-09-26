# harness

**Ticket to merged, run by agents.**

A Claude Code and Codex plugin that runs your repo's delivery loop with agents:
ticket to spec, test-first build, independent review, gated merge — on demand or
unattended. Built on Lean principles.

📖 **[The one-page guide →](https://sluengen.github.io/harness/)** is the visual
companion; this README is the canonical text.

## What it does

Install the plugin, hydrate a repo, and every agent session in it works one
process:

1. **Capture or propose.** A decided change is filed as a ticket carrying its
   change spec, acceptance criteria and assurance lane (`/capture`). An idea that
   is unconfirmed or too big for one change becomes a proposal first — options,
   a recommendation, a decision — and an accepted proposal spawns the tickets
   that build it (`/propose`).
2. **Build.** `/build` takes a ticket onto its own branch in its own worktree,
   grounds the spec against the code as it is, locks the tests, and builds
   against them test-first.
3. **Review.** A separate agent in a fresh context reviews the diff against the
   spec and runs the gate itself. It returns **PASS**, **FAIL** (back to the
   builder, for a bounded number of cycles) or **DEFER** (held for you). On PASS
   the reviewer — never the builder — writes the as-built record.
4. **Land.** `/promote` rebases onto the integration branch, runs the gate again
   over the exact tree that will land, pushes, and closes the ticket. The same
   command moves completed work along the repo's release branches.
5. **Improve.** Every build ends with a short reflection that files what should
   change to an improvement ledger. `/assess` runs periodic health checks;
   `/drain` clears the ledger and anything held for you.

`/routine` runs steps 2–4 unattended: it picks the next ready ticket off the
queue, builds it, and lands it — and holds the ticket for you rather than push
past a red gate, a review that will not converge, or a decision only a person can
make.

A small fix skips the ticket. Ask for it and it gets the same worktree and the
same gate.

## How it decides

The process is Lean, applied to agent-run repos. Hydration writes it into your
repo as the **spine** — `AGENTS.md`, loaded in every session — which carries:

- **An operating context.** The stage the repo is at, the risk it accepts and
  the risk it does not, stated once so every principle below is read against it.
- **Six principles**, each stating what it refuses: *Do less* (which overrides
  the rest), build quality in, reduce waste, flow, stop the line, and continuous
  improvement.
- **Seven laws** — the per-change obligations derived from them. Among them: no
  claim of done without gate output read in the same session; the reviewer, never
  the builder, records what shipped; no editing a test while building against
  it.
- **The contract** every workflow shares: ticket states, holds, the queue and its
  WIP limit, and three assurance lanes — *fix*, *change* and *feature* — so a
  one-line fix and a contract change are not weighed the same. Work that reaches
  user data, credentials or money stops and waits for a person.

Your repo's commands, branches, tracker and layers live in `harness.yaml`. The
gate is yours: `commands.verify` names it, and the builder runs it and reads its
output before claiming anything complete.

## What the plugin carries

| | | |
|---|---|---|
| **Workflows** | 9 | The lifecycle entry points — see below |
| **Craft skills** | 8 | `engineering`, `architecture`, `authoring`, `review-discipline`, `worktree-isolation`, `work-discovery`, `tracker`, `design-system` — loaded by task, not all at once |
| **Agent roles** | 5 | `dev`, `reviewer`, `architect`, `steward`, `harness-audit` |
| **Hooks** | 4 | One refuses: an edit to a test file while the run has locked its tests. Three advise: injection-shaped content on write, a source edit on the default branch or outside a worktree, and a push aimed at a branch the repo declares |

The hooks are a backstop, not the assurance. The assurance is the repo's gate,
run and read by the builder, plus the independent review. Branch protection and
any other server-side controls stay the repository's own.

Tickets live in GitHub Issues and Projects, Linear, or nowhere — with `tracker:
none` the process degrades to specs and session reports.

### The nine workflows

| Workflow | Does |
|---|---|
| `build <ticket>` | Implement, verify and review a ticket, ending at PASS |
| `capture` | File an already-decided change straight onto the queue |
| `propose` | Work an idea to a decision before build time is spent; accepted proposals spawn tickets |
| `review` | Review a branch that needs only the review stage |
| `routine` | One unattended discover → build → land cycle |
| `promote` | Land a reviewed branch, or move completed work toward release |
| `drain` | Clear what has accumulated for you: held tickets, then the improvement ledger |
| `assess` | Periodic whole-system health assessment — `code`, `architecture` or `process` |
| `hydrate` | Bring a repo into the process, first time or after a plugin update |

In Claude Code each runs as `/harness:<name>`. In Codex, ask for it by name.
`capture`, `propose` and `hydrate` are yours to trigger; the other six can also
be driven by the model, because `routine` drives `build` and `promote`, `build`
drives `review`, and `assess` drives `drain`.

## Install

This repo is the marketplace for both hosts.

**Claude Code**

```
/plugin marketplace add sluengen/harness
/plugin install harness@harness
```

**Codex**

```bash
codex plugin marketplace add sluengen/harness
codex plugin add harness@harness
```

Then hydrate the repo you want to run the process in: `/harness:hydrate` in
Claude Code, or ask Codex to hydrate Harness. Both hosts read the same workflow.

### What hydration writes

It interviews for the values the repo has not already declared, then writes the
files that must be repo-owned:

- `harness.yaml` — commands, branches, tracker, layers and paths
- the spine, `AGENTS.md`, and a `CLAUDE.md` that imports it
- path-scoped rules, and the sub-directory instruction files that carry them to
  Codex
- Codex role adapters in `.codex/agents/`
- the specs scaffold and the infrastructure record
- the plugin's marketplace entry in `.claude/settings.json`, with auto-update on
- the gate's ignore patterns in `.gitignore`

**It writes no gate and nothing under `scripts/`.** The gate is the repository's
own; where there is none, hydration says what it must do and leaves the writing
to you.

Run it again after a plugin update — one command, no flag. It refreshes the
plugin-marked spine block and Codex adapters, leaves every repo-owned file alone,
and reports each path as written, rewritten, retained or blocked. Hydration only
touches the working tree: no commits, no pushes, no tracker writes.

The plugin carries one version and no per-file pins. A repo that needs to
diverge from a shipped skill forks it locally.

## This repo

The plugin's source, and it ships its own changes through the same process:
every change here is a fix or a ticket, built test-first and landed through the
gate.

- **Guidance** — `skills/`, `agents/`, `hooks/`, `templates/`
- **The gate** — `scripts/verify.sh`: ruff, mypy, pytest under a coverage floor,
  and a design-token drift check
- **The guards** — `tests/unit/`, admitted under ADR 0017's rule: behaviour of
  executable code, properties of the spine, integrity of shipped assets

There is no runtime and no service. Python is tooling only; the hooks and the
configuration reader run on Node.

```bash
git clone https://github.com/sluengen/harness.git && cd harness
uv sync --extra dev          # the dev toolchain (needs uv)
bash scripts/verify.sh       # the gate (also needs node and jq)
```

Work lands on `dev`. A nightly job promotes `dev` to `main` only when the gate
is green on the exact candidate, and what lands on `main` is exactly the tree
that was gated (`specs/infrastructure.md`).

**Stack:** Python 3.11+ (stdlib only) · Node · pytest · ruff · mypy · uv

## Why it is shaped this way

The decisions are ADRs in [`specs/decisions/`](./specs/decisions/), indexed in
[`specs/architecture-principles.md`](./specs/architecture-principles.md). The
ones that set the current shape:

- **ADR 0015** — the runtime is retired; the harness becomes a thin verification layer
- **ADR 0017** — the guidance ships as a plugin, under one version
- **ADR 0019** — purpose before proof: name what a check protects before
  writing it
- **ADR 0022** — the plugin is the whole deliverable, and the repo's declared
  gate is the assurance

What each component assumes the model cannot do, and the test that would retire
it, is in [`specs/harness-assumptions.md`](./specs/harness-assumptions.md).

**Design ancestry:** inspired by [Archon](https://github.com/coleam00/Archon)
and Anthropic's "build skills, not agents" guidance. A greenfield build, not a
fork.

## Contributing and security

Issues and pull requests are welcome and handled on a **best-effort** basis —
this is a single-maintainer project that runs on its own process. See
[`CONTRIBUTING.md`](./CONTRIBUTING.md). To report a security issue, do **not**
open a public issue; follow [`SECURITY.md`](./SECURITY.md) to disclose it
privately.

## Licence

**MIT** ([`LICENSE`](./LICENSE)) — the whole repo, guidance and tooling alike.
Use any of it in any repository, including a closed-source one.
