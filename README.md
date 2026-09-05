# harness

📖 **[Read the one-page guide →](https://sluengen.github.io/harness/)** — the operating model at a glance. (This README stays the canonical text; the page is its visual companion.)

**A spec-driven development process for agent-driven repos, shipped natively for
Claude Code and Codex**: nine lifecycle workflows, the craft skills behind them, four agent
roles, and enforcement hooks that make a green gate the only path to a shared
branch.

> Let the agent do the judgement work; make the repo own the evidence.

An AI agent does everything that needs judgement — the design, the code, the
fixes, the answer to a review finding. The harness owns the parts that must not
depend on an agent remembering them:

- **One verification gate.** The repo's verify command (here,
  `bash scripts/verify.sh`) decides green and writes a marker named after the
  exact git tree it verified. Green over those exact bytes is the only evidence
  a completion claim may cite; one more edit invalidates it.
- **The spine.** A repo-owned `AGENTS.md` carries the five principles, the laws
  derived from them, and the lifecycle contract — always loaded, never optional.
  `CLAUDE.md` is `@AGENTS.md` plus the deltas that apply on that host alone, and
  the repo's configuration is `harness.yaml`. Skills carry the depth and load by
  task; path-scoped rules under `.claude/rules/` load with the files they scope.
- **Builder / recorder separation.** The agent that promises delivery is not the
  one that records it, which keeps the as-built record honest.
- **Hooks that refuse.** A completion claim without fresh gate evidence, a push
  to a protected branch without a marker over the pushed tree, and any history
  rewrite are refused at the agent host. The controls of record stay
  server-side: branch protection and gate output in CI.

It is **dogfooded on its own development**: every change here ships through the
process the plugin publishes, against the same gate.

## Install

This repo is the marketplace for both native plugin manifests.

Claude Code:

```
/plugin marketplace add sluengen/harness
/plugin install harness@harness
```

Then, in the repo you want to run the process in:

```
/harness:init
```

Codex:

```bash
codex plugin marketplace add sluengen/harness
codex plugin add harness@harness
```

Then ask Codex to initialize Harness in the repository. Both hosts read the same
`init` workflow from `skills/init/`.

`init` interviews for the repo's values and writes the files that must be
repo-owned: `harness.yaml`, the spine (`AGENTS.md`) and its `CLAUDE.md` pointer,
the path-scoped rules, Codex role adapters,
the specs scaffold, the infrastructure record, and — where the repo has no gate yet — a
`scripts/verify.sh` skeleton that delegates to `node scripts/gate-marker.js run`.
After a plugin update, `/harness:init --refresh` regenerates the marked blocks,
generated Codex role adapters, and recognized Harness-owned gate assets. It leaves
custom gate wiring and unsafe JavaScript module contexts untouched, with a
path-specific report for the operator.

Codex installs a native `.codex-plugin/plugin.json` package. Its `skills/`
directory contains every skill both hosts read, the nine lifecycle workflows
among them — each ships once, not as a mirror of a command file. The
repository-owned `.codex/agents/*.toml` files are Codex role adapters for
named-agent workflows; `/harness:init` hydrates them into a consumer repository,
and `tests/unit/test_codex_agent_adapters.py` holds each one in correspondence
with its `agents/*.md` counterpart. Codex also runs the plugin hooks; the scripts
accept both hosts' payload and output contracts.

## The nine commands

| Command | Does |
|---|---|
| `/build <ticket>` | Implement, verify, review, and ship a ticket — the one lifecycle driver |
| `/capture` | File an already-decided change straight to Todo |
| `/propose` | Work an idea before it becomes work; accepted proposals spawn tickets |
| `/review` | Review the current branch when it needs only that |
| `/routine` | One unattended discover→build→ship cycle |
| `/promote` | Move completed work toward release along the repo's role branches |
| `/digest` | The operator's console: report, then drain held decisions |
| `/assess` | Periodic whole-system health assessment |
| `/harness:init` | Hydrate a repo (the one command that needs its prefix spoken) |

Small fixes need no command and no ticket: the fast lane is the same isolation
and the same gate, invoked by asking.

## The triad

Three skills split *how* from *what*: `engineering` (build), `architecture`
(design and decide), `infrastructure` (operate and promote). Each is a generic
skill body, a plugin asset where the argued rationale accretes, and a repo
asset seeded by `init` — the repo's own stack, decisions, and topology. The
builder and the reviewer read the same files, so the bar is identical on both
sides.

## This repo

The plugin's source, dogfooding itself. Three parts: the guidance surface
(`skills/`, `agents/`, `hooks/`), the gate (`scripts/verify.sh`:
ruff, mypy, pytest under a coverage floor, drift guards, marker write), and the
guards (`tests/unit/`, admitted by ADR 0017's rule — behaviour of executable
code, properties of the spine, integrity of shipped assets, frontmatter). There
is no runtime and nothing to install beyond the plugin: ADR 0015 retired the
CLI, ADR 0017 retired the per-file versioning that followed it.

```bash
git clone https://github.com/sluengen/harness.git && cd harness
uv sync --extra dev          # the dev toolchain (needs uv)
bash scripts/verify.sh       # the canonical gate
```

Work moves `dev → main`: feature branches merge to `dev` through the gate, and
a nightly promotes `dev` to `main` only when the gate is green on the exact
candidate — what lands is exactly the tree that was gated
(`specs/infrastructure.md`).

**Stack:** Python 3.11+ (stdlib only) · pytest · ruff · mypy · uv

## Related

- **Why it is shaped this way:** [`specs/decisions/`](./specs/decisions/) —
  ADR 0015 (the verification layer), ADR 0017 (the plugin shape); retired
  designs live under [`specs/retired/`](./specs/retired/).
- **Design ancestry:** inspired by [Archon](https://github.com/coleam00/Archon)
  and Anthropic's "build skills, not agents" guidance. Greenfield rewrite, not
  a fork.

## Contributing & security

Issues and pull requests are welcome and handled on a **best-effort** basis —
this is a single-maintainer, dogfood project. See
[`CONTRIBUTING.md`](./CONTRIBUTING.md) for the stance. To report a security
issue, do **not** open a public issue — follow [`SECURITY.md`](./SECURITY.md)
to disclose it privately.

## License

**MIT** ([`LICENSE`](./LICENSE)) — the whole repo: the guidance the plugin
carries into your sessions and the repo's own gate, mutation instrument, and
test suite alike. Use any of it in any repository, including a closed-source
one; it encumbers nothing.
