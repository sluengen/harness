# BOOTSTRAP.md — onboarding the harness to a repo

How to make a repo **harness-onboardable**: install the harness, wire its
credentials, bring in the guidance bundle (the universal `/start → /review →
/ship` commands, skills, and agents), and add the harness's own `/harness run`
command — so an agent can drive a Linear ticket end-to-end. Run this once per
repo; thereafter `/update-guidance` keeps the guidance current and the
[§Updating](#updating) steps below move you to a new harness release.

This is the **repeatable** procedure the rest of the docs point at:
`CLAUDE.md` / `AGENTS.md` / `GEMINI.md` reference [step 2](#step-2--make-room-for-the-guidances-start)
for the command-name collision, `RELEASING.md` references
[§Updating](#updating), and `.guidance-lock.yaml` is the lock file this
bootstrap writes ([step 3](#step-3--install-the-guidance-bundle-writes-guidance-lockyaml)).

> **Who runs this:** a human (or an agent acting for one) setting up the harness
> in a repo for the first time. It is not part of the `/harness run` loop — it
> is the one-time setup that makes that loop available.

---

## What you get

Two install methods; pick one. Both expose a `harness` invocation that runs the
three verbs (`start` / `review` / `close`) against the current repo.

| Method | Use when | Install |
|--------|----------|---------|
| **Docker image + `~/bin/harness` wrapper** (recommended) | You want zero per-repo Python setup; you drive other repos from your host | Build the image, install the wrapper (steps below) |
| **Native `uv tool install`** | Docker is unavailable, or you are iterating on harness source | `uv tool install .` from the harness checkout puts the `harness` console script on `PATH` |

The Docker wrapper handles all credential wiring automatically **on macOS**,
where it reads the Claude token from the Keychain (`security find-generic-password`).
On **Linux** that Keychain path does not exist, so export
`CLAUDE_CODE_OAUTH_TOKEN` in your shell before invoking the wrapper — it is the
one Claude credential the wrapper forwards (`-e CLAUDE_CODE_OAUTH_TOKEN`). The
wrapper does **not** pass `ANTHROPIC_API_KEY` or mount `~/.claude`; to use those
instead you run the plain `docker run` form (or edit the wrapper) — see
[`docker/README.md`](docker/README.md) §Authentication. The native install
requires you to set credentials and env vars yourself on any OS.

---

## The procedure

### Step 1 — install the harness

**Docker (recommended).** From the harness checkout, build the image once:

```bash
docker build -t harness:dev -f docker/Dockerfile .
```

Then install the thin wrapper `~/bin/harness` and put `~/bin` on your `PATH`.
The wrapper script — and exactly what it mounts and forwards — is in
[`docker/README.md`](docker/README.md) ("Thin shell wrapper"). Sanity-check the
image:

```bash
docker run --rm harness:dev version    # → harness 0.1.0
```

**Native (alternative).** From the harness repo root:

```bash
uv tool install .        # installs the `harness` console script on PATH
```

`uv tool install` installs only the Python package — it does **not** bring the
two external CLIs the verbs shell out to. Install both (the Docker image bundles
them; a native host must add them):

```bash
npm install -g @anthropic-ai/claude-code @openai/codex
```

`@anthropic-ai/claude-code` is the CLI the agent runs through; `@openai/codex`
provides the `codex` binary the `review` verb invokes (`codex exec`) — without
it `harness review` fails. Credentials and env vars must then be set manually
(see [step 4](#step-4--wire-credentials)).

> **The native CLI is not the wrapper.** [`commands/harness.md`](commands/harness.md)
> (the `/harness run` command) is written for the `~/bin/harness` Docker wrapper:
> it assumes `.env` is auto-loaded and credentials are wired for you. The native
> console script does neither — it reads `LINEAR_API_KEY` / `CLAUDE_CODE_OAUTH_TOKEN`
> from the actual environment. So before running the verbs natively, export them
> (`set -a; source .env; set +a`), and read the command doc's wrapper steps as
> "invoke the `harness` console script" rather than the containerised wrapper.

### Step 2 — make room for the guidance's `/start`

The guidance bundle installs its universal commands at their **bare** paths —
the guidance's `/start` lands at `commands/start.md`. The harness has its **own**
pipeline commands, and the harness's own "start" means *run the harness
pipeline*, not *begin the agent-led process*. Those would collide on
`commands/start.md`.

Resolve the collision **before** installing the guidance: namespace the
harness's own commands under `/harness <verb>` (so the harness's start lives in
`commands/harness.md` as `/harness run`, not in `commands/start.md`). The
bootstrap **refuses to clobber** an existing `commands/start.md`, so if the
harness's own `start` still occupies that path, move it out first.

In this repo the collision is already resolved — `commands/harness.md` holds
`/harness run` and `/harness ingest`, and `commands/start.md` is free for the
guidance's `/start`. A fresh repo with no `commands/start.md` needs nothing
here; a repo that already used the bare name for its own command must rename it
under `/harness` first.

### Step 3 — install the guidance bundle (writes `.guidance-lock.yaml`)

The guidance bundle — the universal `/start`, `/review`, `/ship`, `/propose`,
`/assess`, `/update-guidance` commands plus the skills, agents, hooks, and the
`harness` process doc — installs from **this repo**: the harness *is* the
guidance source (the guidance repo was merged in). **Do not hand-roll the
install here.** This repo carries the canonical, versioned installer —
[`INSTALLER.md`](INSTALLER.md) (`guidance:bootstrap`), the copy-in bootstrap
prompt; run *that* from inside the target repo, point it at this harness
checkout as the guidance source, and select the **`harness` profile**. It is the
single source of truth for the copy-in mechanics, so this doc does not restate
them — it does, in one pass:

- enforces the [step 2](#step-2--make-room-for-the-guidances-start) no-clobber
  rule (it refuses to overwrite a repo-owned `commands/start.md`);
- copies every `harness`-profile file from `registry.yaml` (`skills/`, `agents/`,
  `commands/`, `hooks/`, `templates/`, the process doc) into place;
- creates the `.claude/` discovery symlinks (`commands`, `skills`, `agents`,
  `hooks` → `../*`) and derives `.claude/settings.json` from `settings/harness.json`;
- derives the three byte-identical entry files `AGENTS.md` / `CLAUDE.md` /
  `GEMINI.md` from `process/harness.md`;
- scaffolds the repo-owned `CONTEXT.md` from the template (never a distributable —
  `/update-guidance` never overwrites it);
- **writes `.guidance-lock.yaml`** (the lock the header comment of that file
  attributes to BOOTSTRAP), recording the source ref and every file's version +
  hash so `/update-guidance` can later detect drift.

Use the harness's recommended **`committed`** visibility mode so a cloud / CI
runner has the guidance (the installer defaults private repos to it).

> **`/harness run` is not in that bundle.** `commands/harness.md` (the
> `/harness run` and `/harness ingest` commands) is **repo-owned here** — it
> ships in the harness repo but is deliberately excluded from `registry.yaml`,
> so the installer does not copy it into a *consuming* repo (a boundary the
> footprint guard locks in, **CAL-650**). Until `/harness run` is distributed as
> a surface unit, a consuming repo gets it by copying `commands/harness.md` from
> the harness repo directly.

Thereafter, **do not hand-edit installed guidance files** (that creates a
permanent local divergence) — run [`/update-guidance`](commands/update-guidance.md)
to pull a newer harness guidance ref, which rewrites the lock.

### Step 4 — wire credentials

The verbs need three credentials. With the `~/bin/harness` wrapper, all three
are wired automatically; the table is what to provide for a native install or CI.

| Credential | What it is for | Wrapper behaviour |
|------------|----------------|-------------------|
| `LINEAR_API_KEY` | `start` / `close` fetch and transition the ticket | Read from `.env` in the current directory |
| Claude Code OAuth (`CLAUDE_CODE_OAUTH_TOKEN`) | the agent that drives the loop | Extracted from the macOS Keychain (`Claude Code-credentials`) per invocation |
| Codex subscription auth (`~/.codex/auth.json`) | the `review` verb's reviewer | `~/.codex` mounted into the container |

Push transport for the `close` verb uses **ssh** — the wrapper mounts `~/.ssh`
read-only and forwards the host ssh-agent (`/run/host-services/ssh-auth.sock`
on macOS Docker Desktop). On a host **without** ssh-agent forwarding, `close`'s
`git push` has no working credential; until a tokenized-https fallback ships,
apply the manual workaround in [`docker/README.md`](docker/README.md) (point
`origin` at an `https://x-access-token:$TOKEN@github.com/…` URL via
`gh auth token`, push, then restore the ssh URL).

Get a `LINEAR_API_KEY` from **linear.app → Settings → API → Personal API keys**.
If Claude auth errors, run `claude /login` on the host to refresh the Keychain
entry.

### Step 5 — scaffold `.env` and `.gitignore`

Create a `.env` at the repo root (the wrapper reads `LINEAR_API_KEY` from it,
no `source` needed):

```bash
# .env (repo root) — never commit this
LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxx
```

Ensure `.gitignore` excludes the secret and the harness's local state so a run
never commits them:

```gitignore
# holds LINEAR_API_KEY — keep every variant out of git
.env
.env.*
# SQLite ledger (harness.db) + worktrees — host-local run state
.harness/
# local virtualenv (native install)
.venv/
```

(Comments must be on their own lines — git treats a trailing `#` as part of the
pattern, so `.env  # …` would *not* ignore `.env` and a later `git add .` could
stage the key.)

### Step 6 — verify the install

```bash
harness version                 # the wrapper or console script resolves
harness doctor                  # environment health checks (see caveat below)
```

`harness version` returning a version is the smoke test that the install
resolves. `harness doctor` reports on git / db / reviewer / cli wiring; its
**auth** row passes on any of `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, or
a mounted `~/.claude/` — so under the recommended wrapper (which injects
`CLAUDE_CODE_OAUTH_TOKEN`) the auth row reads `PASS`.

A repo is onboarded once `harness version` resolves, `.env` holds a valid
`LINEAR_API_KEY`, the guidance bundle is installed (`.guidance-lock.yaml`
present), and `commands/start.md` belongs to the guidance's `/start`.

---

## The onboarding snippet (the unit a consuming repo needs)

The unit a consuming repo needs is **this file plus the `/harness run` command**
([`commands/harness.md`](commands/harness.md)). The command is already
self-contained — it documents the full `start → review → (fix → review)* →
close` loop, the gate-refusal reasons, and context-economy recovery — so a
consuming repo gets a working pipeline command the moment it lands. Because
`commands/harness.md` is repo-owned and excluded from `registry.yaml` (CAL-650),
the installer does not copy it; today a consuming repo copies it across by hand
(see the [step 3](#step-3--install-the-guidance-bundle-writes-guidance-lockyaml)
note).

Put this minimal snippet in the consuming repo's **`CONTEXT.md`** — the
repo-owned file that is never a distributable, so a local addition there creates
no guidance drift. Do **not** paste it into `CLAUDE.md` / `AGENTS.md` /
`GEMINI.md`: those are byte-identical generated artifacts (step 3), and editing
one creates exactly the LOCAL divergence `/update-guidance` warns against. If
the entry point should reach every harness repo automatically, add it to the
source profile's process doc instead, so it ships through the bundle.

```markdown
## Driving a ticket with the harness

`/harness run <ISSUE-ID>` orchestrates the build loop (`start → review →
close`) for a Linear ticket; the harness verbs own every git and ticket
mutation, you own the implementation. First-time setup — install, credentials,
guidance bundle — is in `BOOTSTRAP.md`. When a task does not fit the pipeline
shape, fall back to the agent-led `/start → /review → /ship` flow.
```

> **Mind the base branch.** `harness start` defaults `--base dev`. A consuming
> repo whose integration branch is `main` (or anything other than `dev`) must
> pass `--base <branch>` on every `start`, so adapt the copied `/harness run`
> command (and the `harness start` calls it makes) to the repo's integration
> branch — otherwise the first run fails creating a worktree off a branch that
> does not exist. Removing this footgun with per-repo config (`.harness.toml`)
> is the open ticket **CAL-621**.

---

## Updating

To move a repo to a newer harness release, update **both** layers — the harness
code and the guidance bundle — per your install method:

**Harness code**

- **Docker:** `git checkout <new-tag>` in the harness checkout, then rebuild the
  image: `docker build -t harness:dev -f docker/Dockerfile .`. The wrapper
  resolves `harness:dev` on its next invocation.
- **Native:** `git checkout <new-tag>` then `uv tool install . --force` (or
  `uv tool upgrade harness`) to replace the console script.

**Guidance bundle**

- Run `/update-guidance` to pull the new harness guidance ref. It rewrites
  `.guidance-lock.yaml` with the updated versions and hashes; review the diff
  before committing.

See [`RELEASING.md`](RELEASING.md) for the release-side checklist that produces
the tags consuming repos check out here.
