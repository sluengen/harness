# Launcher & trigger runtime topology — Hermes integration (retired)

> **Superseded 2026-06-15** by CAL-712 (Hermes/launcher quarantine). The launcher control socket, the agent-side launcher client, the autonomous-dispatch trigger stand-in, and the `harness serve` command (~990 LOC) were scaffolding for an autonomous "Hermes" dispatcher that does not exist and is explicitly deferred (`specs/architecture-principles.md`: *"we are not running deterministic autonomy"*). The code was removed; this is kept as the **design, not built** reference for when the autonomous Build loop is actually built. The one load-bearing piece described below — the target-repo workspace allowlist (`HARNESS_WORKSPACE_ROOTS`) — survives in `harness.workspace`, enforced on every verb via `harness/cli/_repo.py`.

> Historical design reference for the harness's launcher / trigger / workspace-allowlist / observability surface: the runtime topology, the narrow launcher control socket, the launch handle and its decision record, the target-repo allowlist, and the read-only ledger observability Hermes would consume. The engine-era **control model** — Hermes driving a deterministic harness workflow, the Option A/B/C deployment decision, and the engine-era bridge interface — was superseded by [`harness-as-tool`](../proposals/harness-as-tool.md) and extracted to [`hermes-control-model.md`](hermes-control-model.md) (CAL-693). Hermes occupies the *trigger* slot a human would: it launches a per-session agent runtime and reads the ledger back; it does not implement, manage worktrees, run codex, do gitops, or write the harness DB.

## Runtime topology

Hermes runs in a container, but it does not invoke the harness directly. It launches **headless Claude Code sessions**, and those sessions are the harness's actual client: the session does the majority of the file work itself and calls harness verbs for the bounded parts the harness owns. This section pins down where each process runs, who holds host-daemon authority, and how a working tree shared between the session and the harness stays consistent.

### Invariants

Two rules keep the runtime flat instead of deeply nested:

1. **No Docker-in-Docker.** Every container is a sibling on the host daemon. Nothing that issues `docker run` does so from inside another container's daemon.
2. **A verb is exactly one container deep.** The agent a verb dispatches (Codex / Claude) runs as a *subprocess* inside the verb container, never as a further nested container (SPEC §4.7). The feared "Codex CLI → one-shot container → Claude → Hermes container" stack never forms, because the inner agent adds no container layer.

```
Hermes container  ── isolated; NO host docker socket
│
├── Hermes ............ planning / conversation. Spawns sessions. Holds no host authority.
│
├── headless Claude Code session(s)  ← spawned by Hermes as an in-container subprocess.
│        │                              THE harness client. Edits the working tree directly
│        │                              and invokes harness verbs for bounded sub-tasks.
│        │  holds: (1) launcher control socket   (2) read-WRITE workspace mount
│        ▼
└── launcher control socket  ── NARROW capability: exposes only the harness verb API
         │                      (start/review/close/status/events/cancel). NOT /var/run/docker.sock.
         ▼
════════ container boundary ════════
HOST
│
├── launcher  ── sole holder of host-daemon authority. Thin broker: translates verb
│        │       requests into `docker run harness <verb> …` and relays status/events back.
│        ▼
└── harness verb  ── ONE-SHOT container, sibling at host root. Mounts the shared workspace.
         └── Codex / Claude agent ── SUBPROCESS inside this one container (no further layer)
```

Worst-case depth for any unit of work is **one container**. Hermes and a running verb are peers on the host daemon, not parent and child.

### Where each process runs

- **Hermes** — in its container. Planning and conversation only. Spawns sessions; holds no host-daemon authority.
- **Claude Code session** — spawned by Hermes as an in-container subprocess. Trivial to launch (no host authority required to fork a local process). This is the harness client: it edits the working tree directly and invokes harness verbs.
- **Launcher** — a thin host process, the sole holder of host-daemon authority. Translates verb requests into `docker run`.
- **Harness verb** — a one-shot container, sibling at host root. Mounts the shared workspace; dispatches its agent as a subprocess.

The session need not leave the Hermes container. Putting it on the host would force Hermes to hold host-spawn authority — exactly what this topology denies it.

### The launch capability is narrow, not the docker socket

What crosses the boundary into the Hermes container is a **launcher control socket** exposing only the harness verb operations (`start` / `review` / `close` / `status` / `events` / `cancel`). It is **not** `/var/run/docker.sock`. Code inside the Hermes container can launch harness verbs; it cannot launch arbitrary containers, inspect siblings, or reach the host daemon.

**Why not just mount the docker socket (DooD).** Mounting `/var/run/docker.sock` is simpler — no shim to build — and was considered, then rejected. The docker socket is root-equivalent on the host: anything that reaches it can run `docker run -v /:/host --privileged …`, mount the whole host filesystem, read every other container's injected secrets, and persist on the host. On a developer's personal machine that is the entire home directory — `~/.ssh`, cloud credentials, browser sessions, every repo not explicitly mounted. The container boundary, which otherwise limits a session to the repos it was handed, becomes cosmetic. (Rootless does not save this on a single-user box: the daemon still runs as that user, so a mounted home exposes the same keys. Rootless mitigates host-root escalation, not "read my own secrets.")

**The deciding factor is who holds the capability.** The launch path is exercised on behalf of two runtimes with very different risk profiles. The Claude Code session is Anthropic's first-party agent, with comparatively narrow lateral initiative. Hermes is a third-party (Nous) runtime — higher supply-chain and vendor risk (a smaller vendor) and, by design, an orchestration layer built for broad initiative. The container boundary around Hermes is doing real work; DooD deletes it. We are not protecting the repo — the session edits it by design — we are protecting everything on the host that is *not* the repo from a higher-risk third-party runtime.

**The load-bearing property** the launcher uniquely provides — and DooD and off-the-shelf socket proxies do not — is that **the caller never specifies the mount, the privilege, or the env.** The caller says "run verb X on repo Y"; the launcher picks the image, the mounts (from the workspace allowlist), and the scoped credentials. That closes the host-escape vectors (`-v /:/host`, `--privileged`, `exec` into siblings) at the source. A socket proxy filters API verbs but typically still lets the caller pass host bind mounts, so it does not close the filesystem-escape vector; only constructing the `docker run` server-side does.

At single-machine scale the launcher is a thin local helper (≈100 lines, or `harness serve --local`), not the multi-tenant broker of Option C. Per-run credential isolation — a headline launcher benefit on multi-tenant hosts — is near-worthless on a single-user machine, so the justification here is host-filesystem containment, not credential scoping.

### The harness stays one-shot; the launcher is the only persistent process

SPEC §16 lists "long-running daemon / server" as a non-goal, and the bridge-transport question below previously flagged that a socket bridge "implies a daemon." It does not imply a *harness* daemon. The harness remains one-shot — each verb is `docker run … && exit`. The persistent process is the **launcher**: a separate, minimal host broker whose only jobs are (a) accept verb requests on the control socket, (b) issue `docker run` with the right mounts and env, (c) relay status and events back. It carries no workflow logic, no engine code, and no run state. The non-goal holds — we did not turn the harness into a service; we added a small privileged spawner beside it.

### Shared workspace and path equivalence

The Claude Code session and the harness verbs operate on the **same on-disk files**, read-write. The session does most of the editing; verbs mutate the same tree for the parts they own. Two constraints follow:

- **The workspace must be mounted at the identical absolute path on the host, inside the Hermes container, and inside every verb container.** Bind-mount sources are resolved by the *host* daemon, not by the calling container: when the launcher runs `docker run -v <path>:<path>`, `<path>` must exist on the host at that path. If the session refers to `/workspace/<repo>/…`, the host mounts the same volume at `/workspace/<repo>/…`, and verbs mount it there too, then a path the session passes through the control socket resolves identically inside the verb container. Diverging mount points silently break file references across the boundary, with no error — make `/workspace` (or the configured root) the canonical path everywhere.
- **Single-writer discipline per subtree.** Because the session and a verb can both write the same files, a file-mutating verb owns the working tree for the duration of its run. Verbs are synchronous from the session's point of view: it invokes a verb, waits for terminal status, then resumes its own edits. The session must not edit the same subtree while a mutating verb is in flight. Concurrent verbs stay isolated from each other through the per-run worktree mechanism ([`worktree-lifecycle.md`](../features/worktree-lifecycle.md)) — each runs in `.worktrees/harness/<run-id>/` on the shared volume. A verb meant to collaborate in-place on the main tree (rather than in a worktree) must be the sole writer for its window.

### Relationship to the Option A/B/C decision

This topology is the concrete form of **Option B** (the co-location decision recorded in the retired control-model doc, [`hermes-control-model.md`](hermes-control-model.md)) for the Hermes-launches-Claude-Code model. It refines the earlier "harness as a long-lived sibling container" reading: the harness is not a persistent pod sibling driven over a socket — it is one-shot verb containers spawned on demand by the host launcher, and the interface client is the Claude Code session inside the Hermes container, not the Hermes process itself. Option C (harness as a shared multi-tenant service) is unchanged as the future path; the launcher does not foreclose it — a remote launcher endpoint is its natural evolution.

### Launch handle and decision record ([CAL-576](https://linear.app/calibrate-coffee/issue/CAL-576))

The "thin launch handle" the supersession header promises. Two parts: the **contract** for the launch command and how credentials/worktree/readback reach across it, and the **three decision blocks** the topology above settled. CAL-576 recorded the decisions/contract half; the end-to-end demonstration (AC-1/AC-2/AC-3) and the two-entrypoint image (decision #3) **shipped in [CAL-585](https://linear.app/calibrate-coffee/issue/CAL-585)** — see *As-built: launch handle end-to-end* below and §Follow-up implementation tickets, Ticket 5.

#### The launch-handle contract

The trigger — Hermes on the autonomous path, a human on the interactive one — occupies the same slot and issues the same handle. It launches a **per-session agent runtime** and reads the ledger back; it never implements, manages worktrees, runs codex, does gitops, or writes the harness DB.

- **Launch command.** The trigger starts a headless Claude Code session from the image's **agent-mode entrypoint** (decision #3) and hands it one prompt: `claude -p "/harness run <TICKET>"` (decision #2). That session is *the* harness client: it edits the shared worktree directly and shells out to verbs for the bounded parts the harness owns. It must **not** run inside a one-shot verb container — that would make it per-call and reintroduce the lost-context problem the pivot removed (the invariant: agent per-session, verbs per-call).
- **How credentials reach the runtime.** Exactly as the documented `~/bin/harness` wrapper supplies them today (see `docker/README.md`): `LINEAR_API_KEY` from the target repo's `.env`; the Claude OAuth token injected into the agent runtime at launch; the codex subscription auth (`~/.codex`) mounted into the verb containers that run `review`. The session never holds `/var/run/docker.sock` — only the **launcher control socket** (decision #1), so each verb it requests is a one-shot container the launcher constructs server-side with the mount, image, privilege, and env all chosen by the launcher, not the caller.
- **How the worktree reaches the runtime.** Via the shared workspace mounted at an **identical absolute path** on the host, in the agent runtime, and in every verb container (the path-equivalence rule above). `harness start` creates the run's worktree on that shared volume and emits `worktree_path`; the session `cd`s there and implements; verbs mutate the same tree. A path the session passes through the control socket resolves identically inside the verb container.
- **How the outcome is read back.** The trigger determines the run outcome **solely by reading the ledger** — `harness status <run-id> --json` and `harness events --json` (the surviving observability surface; `harness/cli/query.py`) — watching the `start → review(pass) → close` progression or a stall. It performs **no harness DB writes**. On failure or stall it escalates to a human. (This is the AC-3 read-only property; it is demonstrated end-to-end in CAL-585 — see *As-built: launch handle end-to-end* below.)

#### Decision blocks

The three decisions CAL-576 was filed to settle (its "Decisions to settle" list), recorded here in the live design doc as required by AC-4.

**Decision #1 — Agent-runtime hosting + docker handle.** *Settled (this section).* The per-session agent runtime runs as an **in-container subprocess of the trigger** (the Hermes container on the autonomous path), holding no host-daemon authority. It is granted the ability to spawn sibling one-shot verb containers through a **narrow launcher control socket** mounted into that container — **not** `/var/run/docker.sock`. *Rationale:* the docker socket is root-equivalent on the host; mounting it into a higher-risk third-party (Nous) runtime makes the container boundary cosmetic, exposing every host secret outside the mounted repo. The launcher's load-bearing property is that the caller never specifies the mount, privilege, image, or env — it says "run verb X on repo Y" and the launcher constructs the `docker run` server-side, closing the `-v /:/host` / `--privileged` / `exec`-into-siblings escape vectors at the source. See *The launch capability is narrow, not the docker socket* above; implemented as the CAL-579 launcher.

**Decision #2 — Interactive (TTY) vs. headless-autonomous runtime.** *Settled: headless.* The autonomous path runs the agent runtime **headless** via `claude -p "/harness run <TICKET>"`; Claude Code drives the full `start → implement → review* → close` loop non-interactively. The interactive (human-triggered) path may attach a TTY, but both forms preserve the invariant identically — **agent per-session, verbs per-call** — so the choice is a launch-flag detail, not a topology fork. The deployed trigger uses the headless form.

**Decision #3 — Image roles.** *Settled by human call (2026-06-11): one image, two entrypoints.* The per-session agent runtime (claude) and the per-call verb container (codex) ship as a **single image with two entrypoints** — an `agent` mode and a `verb` mode — rather than two separate images. The entrypoint selects the role: agent-mode drives `/harness run`; verb-mode runs a single one-shot verb. *Rationale:* one artifact to build, version, and keep in sync; the verb/agent split is a runtime entrypoint switch, not a packaging boundary. Both roles already share the same base (Python + git + node + the two CLIs), so a single image avoids duplicated dependency layers and divergent versions of the harness package between agent and verb. *Built in CAL-585:* `docker/entrypoint.sh` dispatches the role from the first argument — `agent <TICKET>` → `claude -p "/harness run <TICKET>"` (headless, decision #2); `verb <args…>` → `uv run harness <args…>`. A bare verb with no mode selector is treated as `verb` for backward compatibility, so the CAL-579 launcher and the `~/bin/harness` wrapper — which invoke `<image> start …` directly — keep working unchanged.

#### As-built: launch handle end-to-end ([CAL-585](https://linear.app/calibrate-coffee/issue/CAL-585))

The deferred demonstration (AC-1/AC-2/AC-3) now ships, proven by a hermetic local stand-in (`harness/trigger.py`, `tests/integration/test_hermes_demo.py`). The strategy — settled with the human 2026-06-11, with changes to Nous' Hermes agent out of scope — is a **local stand-in** that occupies the trigger slot: it launches a per-session agent-runtime stand-in driving `start → implement → review → close`, each verb requested over the launcher control socket, and reads the outcome solely from the ledger.

- **Every verb crosses the launcher socket (AC-1).** The launcher's operation surface (`harness/launcher.py`, `OPERATIONS`) now exposes the full lifecycle — `start`, `review`, **and** `close` — alongside the read/control ops, and each verb container is built with the launcher-controlled credential mounts the verbs need (`~/.codex` for `review`'s codex, `~/.ssh` + the forwarded ssh-agent for `close`'s push), mirroring the `~/bin/harness` wrapper. The agent-side counterpart is `harness/launcher_client.py`: a thin client that turns `harness <verb> …` into one control-socket request. Agent-mode (`docker/entrypoint.sh`) puts a `harness` shim ahead on `PATH` that runs it, so the unchanged `/harness run` loop routes *every* verb through the socket — the agent runtime holds the control socket but never `/var/run/docker.sock`, and spawns each verb as a one-shot `docker run --rm` sibling outside itself. `close`'s gate runs inside the verb container, so the socket cannot be used to bypass review: a close with no HEAD-bound passing review is refused (`no_passing_review`). For `close`'s push the launcher prefers the forwarded ssh-agent; when no agent socket is available it falls back to **tokenized https** if a GitHub token is in its env (`GITHUB_TOKEN` / `GH_TOKEN`) — `GIT_CONFIG_*` env rewrites the github ssh remote to https (`insteadOf`) and a credential helper supplies the token at push time, so the container authenticates without an agent and without a manual `gh auth token` dance per run. As with the other injected secrets, the token is forwarded by *name* (`-e <NAME>`) so its value never enters argv; and because it is a bearer push credential, it is scoped to the only verb that pushes — `close` — never injected into the `review` container, which runs codex unsandboxed and has no need to push ([CAL-622](https://linear.app/calibrate-coffee/issue/CAL-622)).
- **One session, context retained (AC-2).** A single agent runtime drives all three verbs; the `run_id` that `start` opens is the one `review` and `close` are bound to. There is one launch per ticket, not one per verb.
- **Outcome read solely from the ledger (AC-3).** The trigger derives `closed` / `review_passed` only from `harness status --json` / `harness events --json`; its read-back leaves the ledger DB byte-identical (it never writes). The verbs own every state mutation; the trigger only observes.

`harness/trigger.py` is the stand-in library, not deployment glue: the launch and ledger-reader collaborators are injected, so the demo substitutes an in-process agent that drives the real verbs with Linear / codex / git-push faked. The deployed trigger is Hermes (or a human via `/harness run`); wiring the real agent-runtime launch into Hermes lives in Nous, not this repo.

---

## Safety requirements

### Target repo allowlist

The harness must validate the `--repo` path against a configured allowlist of workspace roots before creating worktrees or running commands. Paths outside the allowlist are rejected at startup with exit 2.

Configuration (container-level env var): `HARNESS_WORKSPACE_ROOTS=/workspace:/data/repos`

The allowlist check normalises all target paths with `Path.resolve()` before the check to prevent symlink traversal.

**Implemented** in `harness/workspace.py` ([CAL-584](https://linear.app/calibrate-coffee/issue/CAL-584)): the `--repo` acceptance point shared by `start`/`review`/`close` resolves the candidate and each root with `Path.resolve()`, accepts only path-segment descendants of a configured root (a string-prefix sibling like `/work/repo-evil` is rejected for root `/work/repo`), and fails closed when `HARNESS_WORKSPACE_ROOTS` is unset/empty — rejecting with exit 2 and a stderr message naming the path.

### Per-run isolation

- Each run gets a unique ULID `run_id`.
- Worktrees are created at `<repo_root>/.worktrees/harness/<run_id>/` and branches at `harness/<run_id>`. Run IDs never collide.
- Concurrent runs against the same repo operate on distinct worktrees and SQLite rows. SQLite WAL mode prevents reader/writer contention.
- A run's working directory is never reused; `WorktreeNode.create` raises `WorktreeNodeError` if the path already exists.

### Secret scoping

Secrets flow into each verb container only via env-var injection by the launcher at spawn time (`-e <NAME>`, value never in argv). The harness must not read or log `ANTHROPIC_API_KEY`, `LINEAR_API_KEY`, or other credential env vars beyond their intended use. Hermes-side secrets (session tokens, conversation state) must not appear in the verb env.

### Housekeeping

`harness worktrees cleanup --age 24h` is the operator/cron tool that removes stale worktree directories from crashed or abandoned runs (direct git; it retains the branch). It is decoupled from the per-run lifecycle — `close` does not auto-remove the worktree.

### The trigger cannot bypass the close gate

The trigger (Hermes or a human) launches the agent runtime and reads the ledger; it never writes the harness DB. It cannot merge unreviewed work: `close` enforces the gate inside the verb container (a `verdict=pass` whose reviewed SHA == HEAD), so even an autonomous trigger cannot ship a ticket that was not reviewed.

---

## Observability requirements

Hermes determines a run's outcome **read-only**, from the ledger — it does not parse raw event logs or write the DB. The verb-model status surface is the feature specs' as-built record: the read commands (`harness status` / `events` / `runs`, `--json`) are in [`cli-surface.md`](../features/cli-surface.md), and the `runs` / `events` row and event shapes are in [`run-ledger.md`](../features/run-ledger.md).

What Hermes (or any trigger) reads to follow a run:

- **`harness status <run-id> --json`** — the canonical status object. The live run lifecycle is `open` → `closed` (gate passed) or `cancelled` (abandoned); see [`run-ledger.md`](../features/run-ledger.md) for the status values and the `runs` columns surfaced.
- **`harness events <run-id> --json`** — the append-only event log; `--after-id <id>` gives incremental polling (store the last-seen `id`, request `id > last-seen` next). The trigger watches the `start → review(pass) → close` progression or a stall, and escalates to a human on failure.

The trigger's read-back leaves the ledger byte-identical — every state mutation is owned by the verbs (see §Runtime topology → *As-built: launch handle end-to-end*).

---
