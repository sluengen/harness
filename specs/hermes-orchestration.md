# Hermes Orchestration — architecture decision, interface spec, deployment model

> **Superseded 2026-06-11** by proposal [`harness-as-tool`](proposals/harness-as-tool.md) (accepted 2026-06-09; orchestration-inversion decision recorded in [`architecture-principles`](architecture-principles.md)).
>
> The **control half** of this spec is superseded: Hermes no longer *drives and monitors a deterministic harness run* (start-run / cancel / resume-decision as ways to walk a YAML workflow), and the "harness is the thing Hermes runs" framing is dropped. Under the verb model there is **one execution model** — a Claude session that orchestrates *and* implements, calling the `start` / `review` / `close` verbs — with **two triggers**: a human (`/harness run <ticket>`) or Hermes. Hermes is [Nous Research's Hermes](https://hermes-agent.nousresearch.com): a persistent containerised agent with a built-in cron dispatcher. It occupies the *trigger* slot a human would otherwise occupy — it launches a per-session agent runtime and reads the ledger back; it does not implement, manage worktrees, run codex, or do gitops, and it never writes the harness DB.
>
> The separate-runtime + sibling-container deployment + async-bridge design below (subprocess → socket → HTTP, polling, deferred daemon) is **dropped**. The remaining integration is a thin **launch handle** (`claude` + `/harness run <ticket>`) plus the container-invocation topology — now specified in §Runtime topology → *Launch handle and decision record* (CAL-576, decisions/contract; the end-to-end demo deferred), with the host-side launcher in CAL-579.
>
> **What survives:** the **observability half** — the run status object, the event stream, and artifact paths (`harness status` / `events --json`, `harness/cli/query.py`). Hermes still consumes these read-only to know whether a session started, passed review, and closed (or stalled). Read the sections below only for that observability surface; treat every "Hermes drives the run" statement as historical.

Hermes is the planning and conversational agent. The harness is the deterministic execution engine. This spec defines how they divide responsibilities, how they communicate, and how they should be deployed together.

---

## Purpose

Establish the boundary between Hermes (judgment, planning, user interaction) and the harness (deterministic execution), define the narrow interface through which Hermes drives harness runs, and record the deployment architecture decision so both runtimes can evolve without implicit coupling.

---

## Responsibility boundary

### Hermes owns

- Interpreting the user's goal and maintaining conversational context.
- Deciding when a workflow should be launched and which workflow to select.
- Parameterising workflow inputs from user intent.
- Monitoring run progress and summarising it for the user.
- Making judgment calls when a run needs escalation, retry, or human input.
- Routing `decision: human` approvals back to the harness.

### Harness owns

- Validating workflow inputs and target repo paths.
- Managing per-run working directories and git worktrees.
- Dispatching `ClaudeAgent` / `CodexAgent` sessions against the target repo.
- Persisting run state and event streams in SQLite.
- Executing script, check, decision, and loop nodes.
- Enforcing cleanup and safety rules.
- Returning structured run status and artifact paths to Hermes.

The harness never interprets user intent. Hermes never manages worktrees or dispatches agent sessions.

---

## Architecture decision: co-location vs service separation

### Decision

**Option B (same pod/task, separate containers) is the preferred production shape.**

Hermes and the harness run as sibling containers in the same task definition (ECS task, Kubernetes pod, or Fly.io machine). They share a mounted workspace volume. Each container has its own process, its own environment, and its own credentials. The bridge between them is a narrow local interface (see §Interface below).

**Option A (same container) is acceptable as the first working prototype.** It is not the long-term boundary. Collapsing to one container is an implementation shortcut to prove the workflow; the interface design must still treat the two runtimes as distinct processes with a declared protocol.

**Option C (harness as separate service) is the future path** when multiple Hermes instances or external callers need to share a harness fleet, or when run tracking needs centralised observability. Nothing in the v1/v2 interface design should foreclose this upgrade.

### Rationale for Option B over Option A

| Concern | Option A (same container) | Option B (separate containers) |
|---|---|---|
| Credential isolation | All secrets in one env | Harness env ≠ Hermes env |
| Process lifecycle | A harness crash can take down Hermes | Containers restart independently |
| Logs and health | Interleaved; hard to separate | Independent log streams and health endpoints |
| Resource limits | Single cgroup | Separate CPU/memory limits |
| Upgrade path | Tight coupling; harder to promote to service | Drop-in replacement with a real HTTP/socket API |

The operational cost is a small local bridge (CLI subprocess or Unix socket). That cost is justified because credential and lifecycle isolation are not easy to retrofit later.

### Rationale for Option B over Option C

Option C requires API auth, queuing, tenancy, and network design upfront. For a single Hermes instance talking to a single harness, that infrastructure overhead is not justified today. Promote to Option C when demand demonstrates it.

---

## Deployment model

### Option A — same container (prototype)

```
┌─────────────────────────────────────────┐
│  Container                              │
│  ┌──────────┐    subprocess / CLI       │
│  │  Hermes  │ ──────────────────────► harness CLI  │
│  └──────────┘                           │
│  Shared filesystem; all credentials     │
│  in one env                             │
└─────────────────────────────────────────┘
```

Hermes invokes `harness run ...` as a subprocess and reads stdout/exit code. Simplest path to proving the integration.

### Option B — same pod/task, separate containers (production target)

```
┌──────────────────────────────────────────────────────────┐
│  Pod / Task                                              │
│  ┌──────────────────┐   Unix socket or local HTTP        │
│  │  Hermes          │ ─────────────────────────────────► │
│  │  container       │                                    │
│  └──────────────────┘                  ┌──────────────┐ │
│                                        │  Harness     │ │
│                                        │  container   │ │
│                                        └──────────────┘ │
│  Shared workspace volume: /workspace                     │
│  Independent env, secrets, resource limits               │
└──────────────────────────────────────────────────────────┘
```

The shared volume gives the harness access to target repos and the SQLite DB. Hermes reads run status and event logs from the same volume, but does not write to the harness DB directly.

**Volume design:**

| Path | Owner | Access |
|---|---|---|
| `/workspace/<repo-name>/` | Hermes mounts; harness operates | Both read; harness writes |
| `/workspace/<repo-name>/.harness/harness.db` | Harness writes | Harness writes; Hermes reads |
| `/workspace/<repo-name>/.worktrees/` | Harness | Harness only |

**Secret scoping:**

| Secret | Hermes | Harness |
|---|---|---|
| `ANTHROPIC_API_KEY` / Claude OAuth | Both (Hermes dispatches its own sessions; harness dispatches agent nodes) | Both |
| `LINEAR_API_KEY` | Both (Hermes reads tickets; harness script nodes fetch data) | Harness |
| `GITHUB_TOKEN` | Hermes (PR creation, status checks) | Harness (git push, PR creation from workflow) |
| Hermes conversation keys / user session tokens | Hermes only | Never |
| Per-run agent isolation token (future) | Neither | Harness only |

### Option C — harness as separate service (future)

A harness daemon exposes a REST or gRPC API. Multiple Hermes instances submit runs to a shared pool. Suitable when run throughput or multi-tenant isolation demands it. Requires API auth, queuing, and tenant-scoped DB rows; out of scope for v1/v2.

---

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
         │                      (start/status/events/cancel/decision). NOT /var/run/docker.sock.
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

What crosses the boundary into the Hermes container is a **launcher control socket** exposing only the verb operations in §Interface (start / status / events / cancel / decision). It is **not** `/var/run/docker.sock`. Code inside the Hermes container can launch harness verbs; it cannot launch arbitrary containers, inspect siblings, or reach the host daemon.

**Why not just mount the docker socket (DooD).** Mounting `/var/run/docker.sock` is simpler — no shim to build — and was considered, then rejected. The docker socket is root-equivalent on the host: anything that reaches it can run `docker run -v /:/host --privileged …`, mount the whole host filesystem, read every other container's injected secrets, and persist on the host. On a developer's personal machine that is the entire home directory — `~/.ssh`, cloud credentials, browser sessions, every repo not explicitly mounted. The container boundary, which otherwise limits a session to the repos it was handed, becomes cosmetic. (Rootless does not save this on a single-user box: the daemon still runs as that user, so a mounted home exposes the same keys. Rootless mitigates host-root escalation, not "read my own secrets.")

**The deciding factor is who holds the capability.** The launch path is exercised on behalf of two runtimes with very different risk profiles. The Claude Code session is Anthropic's first-party agent, with comparatively narrow lateral initiative. Hermes is a third-party (Nous) runtime — higher supply-chain and vendor risk (a smaller vendor) and, by design, an orchestration layer built for broad initiative. The container boundary around Hermes is doing real work; DooD deletes it. We are not protecting the repo — the session edits it by design — we are protecting everything on the host that is *not* the repo from a higher-risk third-party runtime.

**The load-bearing property** the launcher uniquely provides — and DooD and off-the-shelf socket proxies do not — is that **the caller never specifies the mount, the privilege, or the env.** The caller says "run verb X on repo Y"; the launcher picks the image, the mounts (from the workspace allowlist), and the scoped credentials. That closes the host-escape vectors (`-v /:/host`, `--privileged`, `exec` into siblings) at the source. A socket proxy filters API verbs but typically still lets the caller pass host bind mounts, so it does not close the filesystem-escape vector; only constructing the `docker run` server-side does.

At single-machine scale the launcher is a thin local helper (≈100 lines, or `harness serve --local`), not the multi-tenant broker of Option C. Per-run credential isolation — a headline launcher benefit on multi-tenant hosts — is near-worthless on a single-user machine, so the justification here is host-filesystem containment, not credential scoping.

### The harness stays one-shot; the launcher is the only persistent process

SPEC §16 lists "long-running daemon / server" as a non-goal, and the bridge-transport question below previously flagged that a socket bridge "implies a daemon." It does not imply a *harness* daemon. The harness remains one-shot — each verb is `docker run … && exit`. The persistent process is the **launcher**: a separate, minimal host broker whose only jobs are (a) accept verb requests on the control socket, (b) issue `docker run` with the right mounts and env, (c) relay status and events back. It carries no workflow logic, no engine code, and no run state. The non-goal holds — we did not turn the harness into a service; we added a small privileged spawner beside it.

### Shared workspace and path equivalence

The Claude Code session and the harness verbs operate on the **same on-disk files**, read-write. The session does most of the editing; verbs mutate the same tree for the parts they own. Two constraints follow:

- **The workspace must be mounted at the identical absolute path on the host, inside the Hermes container, and inside every verb container.** Bind-mount sources are resolved by the *host* daemon, not by the calling container: when the launcher runs `docker run -v <path>:<path>`, `<path>` must exist on the host at that path. If the session refers to `/workspace/<repo>/…`, the host mounts the same volume at `/workspace/<repo>/…`, and verbs mount it there too, then a path the session passes through the control socket resolves identically inside the verb container. Diverging mount points silently break file references across the boundary, with no error — make `/workspace` (or the configured root) the canonical path everywhere.
- **Single-writer discipline per subtree.** Because the session and a verb can both write the same files, a file-mutating verb owns the working tree for the duration of its run. Verbs are synchronous from the session's point of view: it invokes a verb, waits for terminal status, then resumes its own edits. The session must not edit the same subtree while a mutating verb is in flight. Concurrent verbs stay isolated from each other through the existing worktree mechanism (SPEC §9) — each runs in `.worktrees/harness/<run-id>/` on the shared volume. A verb meant to collaborate in-place on the main tree (rather than in a worktree) must be the sole writer for its window.

### Relationship to the Option A/B/C decision

This topology is the concrete form of **Option B** for the Hermes-launches-Claude-Code model. It refines the earlier "harness as a long-lived sibling container" reading: the harness is not a persistent pod sibling driven over a socket — it is one-shot verb containers spawned on demand by the host launcher, and the interface client is the Claude Code session inside the Hermes container, not the Hermes process itself. Option C (harness as a shared multi-tenant service) is unchanged as the future path; the launcher does not foreclose it — a remote launcher endpoint is its natural evolution.

### Launch handle and decision record ([CAL-576](https://linear.app/calibrate-coffee/issue/CAL-576))

The "thin launch handle" the supersession header promises. Two parts: the **contract** for the launch command and how credentials/worktree/readback reach across it, and the **three decision blocks** the topology above settled. This is the as-built record for the decisions/contract half of CAL-576; the end-to-end demonstration (AC-1/AC-2/AC-3) is a deferred follow-up — see §Follow-up implementation tickets, Ticket 5.

#### The launch-handle contract

The trigger — Hermes on the autonomous path, a human on the interactive one — occupies the same slot and issues the same handle. It launches a **per-session agent runtime** and reads the ledger back; it never implements, manages worktrees, runs codex, does gitops, or writes the harness DB.

- **Launch command.** The trigger starts a headless Claude Code session from the image's **agent-mode entrypoint** (decision #3) and hands it one prompt: `claude -p "/harness run <TICKET>"` (decision #2). That session is *the* harness client: it edits the shared worktree directly and shells out to verbs for the bounded parts the harness owns. It must **not** run inside a one-shot verb container — that would make it per-call and reintroduce the lost-context problem the pivot removed (the invariant: agent per-session, verbs per-call).
- **How credentials reach the runtime.** Exactly as the documented `~/bin/harness` wrapper supplies them today (see `docker/README.md`): `LINEAR_API_KEY` from the target repo's `.env`; the Claude OAuth token injected into the agent runtime at launch; the codex subscription auth (`~/.codex`) mounted into the verb containers that run `review`. The session never holds `/var/run/docker.sock` — only the **launcher control socket** (decision #1), so each verb it requests is a one-shot container the launcher constructs server-side with the mount, image, privilege, and env all chosen by the launcher, not the caller.
- **How the worktree reaches the runtime.** Via the shared workspace mounted at an **identical absolute path** on the host, in the agent runtime, and in every verb container (the path-equivalence rule above). `harness start` creates the run's worktree on that shared volume and emits `worktree_path`; the session `cd`s there and implements; verbs mutate the same tree. A path the session passes through the control socket resolves identically inside the verb container.
- **How the outcome is read back.** The trigger determines the run outcome **solely by reading the ledger** — `harness status <run-id> --json` and `harness events --json` (the surviving observability surface; `harness/cli/query.py`) — watching the `start → review(pass) → close` progression or a stall. It performs **no harness DB writes**. On failure or stall it escalates to a human. (This is the AC-3 read-only property; demonstrating it end-to-end against a real trigger is the deferred AC-1.)

#### Decision blocks

The three decisions CAL-576 was filed to settle (its "Decisions to settle" list), recorded here in the live design doc as required by AC-4.

**Decision #1 — Agent-runtime hosting + docker handle.** *Settled (this section).* The per-session agent runtime runs as an **in-container subprocess of the trigger** (the Hermes container on the autonomous path), holding no host-daemon authority. It is granted the ability to spawn sibling one-shot verb containers through a **narrow launcher control socket** mounted into that container — **not** `/var/run/docker.sock`. *Rationale:* the docker socket is root-equivalent on the host; mounting it into a higher-risk third-party (Nous) runtime makes the container boundary cosmetic, exposing every host secret outside the mounted repo. The launcher's load-bearing property is that the caller never specifies the mount, privilege, image, or env — it says "run verb X on repo Y" and the launcher constructs the `docker run` server-side, closing the `-v /:/host` / `--privileged` / `exec`-into-siblings escape vectors at the source. See *The launch capability is narrow, not the docker socket* above; implemented as the CAL-579 launcher.

**Decision #2 — Interactive (TTY) vs. headless-autonomous runtime.** *Settled: headless.* The autonomous path runs the agent runtime **headless** via `claude -p "/harness run <TICKET>"`; Claude Code drives the full `start → implement → review* → close` loop non-interactively. The interactive (human-triggered) path may attach a TTY, but both forms preserve the invariant identically — **agent per-session, verbs per-call** — so the choice is a launch-flag detail, not a topology fork. The deployed trigger uses the headless form.

**Decision #3 — Image roles.** *Settled by human call (2026-06-11): one image, two entrypoints.* The per-session agent runtime (claude) and the per-call verb container (codex) ship as a **single image with two entrypoints** — an `agent` mode and a `verb` mode — rather than two separate images. The entrypoint selects the role: agent-mode drives `/harness run`; verb-mode runs a single one-shot verb. *Rationale:* one artifact to build, version, and keep in sync; the verb/agent split is a runtime entrypoint switch, not a packaging boundary. Both roles already share the same base (Python + git + node + the two CLIs), so a single image avoids duplicated dependency layers and divergent versions of the harness package between agent and verb. *Note:* this records the decision (AC-4); building the two-entrypoint switch into the image is part of the deferred end-to-end work (Ticket 5), not this change.

---

## Hermes-to-harness interface

Throughout this section, **Hermes** is shorthand for *the harness client*; in the deployed topology that client is the Claude Code session Hermes launches (see §Runtime topology), not the Hermes process itself. The interface must remain stable even as the underlying transport evolves (subprocess → socket → HTTP). The client should never call internal harness Python APIs directly.

### Transport options

| Transport | When to use |
|---|---|
| CLI subprocess + JSON stdout | Option A prototype; simplest |
| Unix socket (local HTTP or msgpack) | Option B production; low latency, no port management |
| TCP/HTTP | Option C or cross-host |

**Recommended path:** CLI subprocess for the Option A prototype. Unix socket with a thin HTTP layer for Option B. The harness already outputs JSON on all read commands (`harness status <id> --json`, `harness events <id> --json`); the Option A bridge uses those as-is.

### Operations

#### 1. Start run

```
Input:
  workflow_name       string     e.g. "build"
  linear_id           string?    e.g. "CAL-532"
  task_payload        object?    arbitrary inputs for non-Linear workflows
  target_repo_path    string     absolute path to the target repo
  branch_prefix       string?    e.g. "feature/"
  verify_command      string?    shell command to run as the verification gate
  agent               string?    "claude" | "codex" (default: "claude")

Output:
  run_id              string     ULID identifying this run
  status              string     "running" | "queued"

Exit code: 0 on accepted, non-zero on validation failure.
```

CLI form (Option A): `harness run build --linear=CAL-532 --repo /workspace/myapp`
The run_id is emitted to stdout as the first JSON line.

#### 2. Get run status

```
Input:
  run_id              string

Output (structured):
  run_id              string
  workflow_name       string
  workflow_version    integer
  target_repo_path    string     (from inputs_json)
  status              enum       queued | running | waiting | failed | completed | cancelled | stalled | paused
  started_at          ISO 8601
  completed_at        ISO 8601?
  duration_ms         integer?
  exit_code           integer?
  failure_reason      string?
  failure_retryable   bool?
  artifact_paths      object?    { worktree_path, worktree_branch, pr_url, report_path, ... }
  agent_session_ids   list[str]? session identifiers from dispatched agent nodes
```

CLI form: `harness status <run-id> --json`

#### 3. List/stream events

```
Input:
  run_id              string
  event_types         list[str]?   filter; default: all
  since_id            integer?     event row id for pagination / polling

Output:
  list of event objects:
    id                integer
    run_id            string
    node_id           string?
    event_type        string
    timestamp         ISO 8601
    duration_ms       integer?
    data              object
```

CLI form: `harness events <run-id> --json`
Incremental-poll form: `harness events <run-id> --after-id <last-seen-id> --json` (returns only events with `id > last-seen-id`; store the last returned `id` to advance the cursor on the next call)

Hermes consumes events to build compact progress summaries. Relevant event types for Hermes summarisation:

| Event type | Hermes use |
|---|---|
| `workflow_started` | Confirm run is live; surface run_id to user |
| `node_started` / `node_completed` | Progress updates ("implementing…", "running tests…") |
| `node_failed` | Identify failure cause; decide retry vs escalate |
| `loop_iteration` | "Testing: iteration 2 of 5" |
| `decision_requested` | Pause and prompt the user for a human-decision node |
| `workflow_completed` | Summarise outcome; surface artifacts |
| `workflow_failed` | Report failure; surface failure_reason |

#### 4. Cancel run

```
Input:
  run_id              string

Output:
  run_id              string
  outcome             "cancelled"

Exit code: 0 on accepted, 2 if run not found or already terminal.
```

CLI form: `harness cancel <run-id>`

Cancellation is *abandon / close-without-merge* (CAL-587), not a signal: the harness marks the in-flight run `status='cancelled'`, stamps `completed_at`, and emits a `workflow_failed` event with `reason='cancelled'` (so `failure_reason='cancelled'` surfaces in run status). There is no process to signal — `harness start` writes a ledger row and exits. A terminal run cannot be cancelled (exit 2).

#### 5. Fetch artifacts

Artifacts are paths within the shared workspace volume. Hermes reads them directly from the volume after the run completes, using paths surfaced in `get_run_status.artifact_paths`.

Key artifact paths (present on the state after the relevant workflow nodes complete):

| Artifact | State field | Notes |
|---|---|---|
| Worktree path | `worktree_path` | Available during run; cleaned up on `merge_to_base` |
| Worktree branch | `worktree_branch` | Persists after cleanup if `leave_for_inspection` |
| PR URL | `pr_url` | Set by the workflow's PR-creation script node |
| Review output | `review_output` | Set by review workflows |
| Steward report | `report_path` | Set by steward workflows |

#### 6. Resume decision (human-gate nodes)

```
Input:
  run_id              string
  verdict             "approve" | "reject"
  comment             string?

Output:
  run_id              string
  outcome             "resumed" | "cancelled"
```

CLI form: `harness decision approve <run-id> --comment="..."` or `harness decision reject <run-id>`

This is the bridge for `actor: human` decision nodes (v2). When the harness emits `decision_requested`, Hermes surfaces the question to the user and routes their response back through this operation.

---

## Safety requirements

### Target repo allowlist

The harness must validate the `--repo` path against a configured allowlist of workspace roots before creating worktrees or running commands. Paths outside the allowlist are rejected at startup with exit 2.

Configuration (container-level env var): `HARNESS_WORKSPACE_ROOTS=/workspace:/data/repos`

The engine normalises all target paths with `os.path.realpath()` before the allowlist check to prevent symlink traversal.

**Implemented** in `harness/workspace.py` ([CAL-584](https://linear.app/calibrate-coffee/issue/CAL-584)): the `--repo` acceptance point shared by `start`/`review`/`close` resolves the candidate and each root with `Path.resolve()`, accepts only path-segment descendants of a configured root (a string-prefix sibling like `/work/repo-evil` is rejected for root `/work/repo`), and fails closed when `HARNESS_WORKSPACE_ROOTS` is unset/empty — rejecting with exit 2 and a stderr message naming the path.

### Path normalisation

Every path passed to the harness — `--repo`, `cwd` in step YAML, artifact paths — is normalised to an absolute path and checked to lie within the resolved target repo root before use. Script nodes and worktree nodes inherit the normalised path.

### Per-run isolation

- Each run gets a unique ULID `run_id`.
- Worktrees are created at `<repo_root>/.worktrees/harness/<run_id>/` and branches at `harness/<run_id>`. Run IDs never collide.
- Concurrent runs against the same repo operate on distinct worktrees and SQLite rows. SQLite WAL mode prevents reader/writer contention.
- A run's working directory is never reused; `WorktreeNode.create` raises `WorktreeNodeError` if the path already exists.

### Secret scoping

Secrets flow into the harness container only via env var injection at task startup. The harness must not read or log `ANTHROPIC_API_KEY`, `LINEAR_API_KEY`, or other credential env vars beyond their intended use. Hermes-side secrets (session tokens, conversation state) must not appear in the harness env.

### Cleanup obligations

- The harness must run worktree cleanup nodes even on SIGTERM / SIGINT (the existing cancellation path already does this).
- `harness worktrees cleanup --age 24h` should be scheduled as a housekeeping cron in the harness container to remove stale worktrees from crashed runs.
- Cleanup actions are observable: `worktree_removed`, `branch_removed`, and `base_advanced` fields are emitted in the cleanup node's event.

### Hermes instructions cannot bypass contracts

Hermes provides workflow inputs at run-start. It cannot override the harness's Pydantic contract validation, inject arbitrary state, or skip nodes. The harness is authoritative over workflow execution.

---

## Observability requirements

### Run status object (compact, Hermes-consumable)

Hermes should not parse raw event logs to determine run state. The `harness status <run-id> --json` output is the canonical status surface. Required fields:

| Field | Type | Source |
|---|---|---|
| `run_id` | string | `runs.run_id` |
| `workflow_name` | string | `runs.workflow_name` |
| `workflow_version` | integer | `runs.workflow_version` |
| `target_repo_path` | string | `runs.inputs_json.repo` |
| `status` | enum | `runs.status` |
| `started_at` | ISO 8601 | `runs.started_at` |
| `completed_at` | ISO 8601? | `runs.completed_at` |
| `duration_ms` | integer? | `runs.duration_ms` |
| `exit_code` | integer? | `runs.exit_code` |
| `failure_reason` | string? | `data.reason` from the latest `workflow_failed` event |
| `failure_retryable` | bool? | derived from `failure_reason` |
| `artifact_paths` | object? | from `runs.state_json` key fields |
| `agent_session_ids` | list[str]? | from `tool_called` events |

`failure_reason` and `agent_session_ids` require a lightweight query against the events table. Both are included in `harness status --json` output.

### Event streaming

Hermes polls `harness events <run-id> --json` to build live progress updates. Polling interval: 2–5 seconds during active runs. The `id` field on each event row enables efficient incremental polling (store last-seen id, request `--after-id <id>` on the next poll).

### Failure summaries

When `status` is `failed` or `cancelled`, Hermes should surface to the user:

- `failure_reason` — the exception type or harness reason code (e.g., `loop_exhausted`, `ContractViolation`, `stalled`).
- `failure_retryable` — whether Hermes should offer a retry button (transient errors are retryable; contract violations usually require prompt repair).
- The last `node_failed` event's `data` for detailed context.

### Artifact discovery

On `status: completed`, Hermes reads `artifact_paths` from the status object and presents relevant links to the user (PR URL, report path, branch name). Hermes does not scan the workspace directory for artifacts; it relies on the harness to surface them via the status output.

---

## Open questions

1. ~~**Bridge transport for Option B.**~~ **Resolved — see §Runtime topology.** The bridge is a **launcher control socket** mounted into the Hermes container, exposing only the verb API (start / status / events / cancel / decision). A thin host **launcher** services it by issuing `docker run harness <verb>` per request and relaying status and events back. The harness runs no persistent daemon; the launcher is the only long-lived process and carries no workflow logic.

2. ~~**Daemon mode.**~~ **Resolved — see §Runtime topology.** The harness stays one-shot: each verb is `docker run … && exit`. The socket bridge implies a *launcher* daemon, not a *harness* daemon — a separate minimal host broker for container spawning and status relay. SPEC §16's "no long-running server" non-goal is preserved for the harness itself.

3. **Concurrent run limit.** Mechanism resolved, policy deferred. The launcher is the natural enforcement point — it sees every `docker run` and can cap concurrency per-repo or globally before spawning. Worktrees keep concurrent runs safe (distinct branches), so the cap is about agent API cost and git-lock contention, not correctness. Defer the actual limit until measured; the launcher gives it a home when needed.

4. **Per-run credential scoping.** Mechanism resolved, policy deferred. Because the launcher issues `docker run` per verb, it injects per-run env (`ANTHROPIC_API_KEY` / `LINEAR_API_KEY`) at spawn time — each verb container gets its own scoped credentials with no harness daemon required. Who maps a user/session to a credential set (the policy) is deferred to a multi-user deployment ticket.

5. **Workspace root allowlist management.** Enforcement point resolved, provisioning deferred. The launcher issues every mount, so it enforces `HARNESS_WORKSPACE_ROOTS` (combined with the path-equivalence rule in §Runtime topology). Static configuration is a launcher-level env var set at deploy time. Dynamic mounting of new repos at run time still needs a provisioning API — deferred until a workflow requires it.

---

## Follow-up implementation tickets

These tickets move the spec to shipped (Ticket 2 is already done):

### Ticket 1: Hermes-to-harness bridge — subprocess + JSON protocol (Option A)

Implement the Option A bridge so Hermes can drive the harness as a subprocess.

- Add `--json-run-id` flag to `harness run` that emits the run_id as the first stdout line (JSON).
- Document the subprocess invocation pattern and output contract.
- Wire up Hermes to invoke `harness run`, capture `run_id`, and poll `harness status --json`.
- Acceptance: Hermes can start a harness run, poll status, and surface completion to the user.

### ~~Ticket 2: Run status enrichment — current_node, agent_session_ids, after-id polling~~ ✓ shipped

`harness status --json` now includes `failure_reason`, `failure_retryable`, `artifact_paths`, and `agent_session_ids`. `harness events` now accepts `--after-id <integer>` for incremental polling. See `specs/cli.md` §`harness status` and §`harness events` for the full field reference. (`current_node` was also shipped here but removed in CAL-589: it derived from `node_started`, which the retired engine was the only producer of — it was always `null` under the verb model.)

### Ticket 3: Container packaging — separate-container deployment (Option B)

Define the Dockerfile and compose/task-definition shape for Option B deployment.

- Produce a harness container image with the harness binary and its dependencies; no Hermes code.
- Define a compose file (or ECS task definition) with both containers sharing a named workspace volume.
- Document the env var injection strategy for secret scoping (which secrets go to which container).
- ~~Add `HARNESS_WORKSPACE_ROOTS` allowlist enforcement to the CLI.~~ ✓ shipped ([CAL-584](https://linear.app/calibrate-coffee/issue/CAL-584)) — the "Ticket 3 survivor"; see §Target repo allowlist. `harness/workspace.py` is the launcher prerequisite for Ticket 4.
- Acceptance: `docker compose up` starts both containers; Hermes can drive a harness run against a repo mounted on the shared volume.

### Ticket 4: Host launcher — narrow control socket for verb-container launch ([CAL-579](https://linear.app/calibrate-coffee/issue/CAL-579))

Build the host-side launcher chosen over DooD in §Runtime topology. Hermes drives verbs through a narrow control socket; the launcher constructs each `docker run` itself so the caller never specifies the mount, privilege, image, or env.

- Expose a control socket (not `/var/run/docker.sock`) offering only the §Interface verb operations: start / status / events / cancel / decision.
- Construct each verb container server-side; pick mounts from the `HARNESS_WORKSPACE_ROOTS` allowlist (depends on Ticket 3); inject scoped per-run credentials.
- One-shot sibling containers (max one container deep; no DinD); thin local form factor (e.g. `harness serve --local`).
- Acceptance: with only the control socket mounted, Hermes can run a verb end-to-end; a test asserts a caller-supplied host path / privilege flag is rejected (host-escape vector closed); a test asserts mounts outside `HARNESS_WORKSPACE_ROOTS` are rejected.

**Implemented** in `harness/launcher.py` + `harness/cli/serve.py` ([CAL-579](https://linear.app/calibrate-coffee/issue/CAL-579)). The launcher speaks newline-delimited JSON over an `AF_UNIX` socket (`harness serve --local`), exposing exactly `{start, status, events, cancel, decision}` and nothing else — an unknown op is refused before any `docker run`. `build_verb_argv()` constructs each launch server-side: the only caller-derived value entering the docker-option region is the *resolved* repo path (checked through `harness/workspace.py`'s allowlist), mounted at an identical host/container path (`-v <repo>:<repo> -w <repo>`); everything else the caller supplies lands after the image as harness-verb arguments, so `--privileged` / `-v /:/host` / a rogue image / a caller-set env are not expressible. Params are an allowlist per op (any extra key — `privileged`, `volumes`, `image`, `env`, …  — is rejected as `bad_params`), and per-run credentials are injected by name (`-e NAME`) so secret values never enter the argv. Every launch is `docker run --rm` — a one-shot, unprivileged sibling removed on exit. Covered by `tests/unit/test_launcher.py`, `tests/unit/test_cli_serve.py`, and the over-the-wire `tests/integration/test_launcher_socket.py`.

### Ticket 5: Hermes launch handle — decisions + contract, then end-to-end demo ([CAL-576](https://linear.app/calibrate-coffee/issue/CAL-576))

The thin launch handle (`claude … /harness run <ticket>`) plus the container-invocation topology the supersession header defers to this ticket. Split into the independently-buildable decisions/contract half and the end-to-end demo that depends on the launcher (Ticket 4) landing.

- **Path A — decisions + contract (recorded).** The three decision blocks (agent-runtime hosting + docker handle; headless vs. TTY; image roles) and the launch-handle contract (launch command, credential/worktree threading, read-only ledger readback) are recorded in §Runtime topology → *Launch handle and decision record*. This satisfies **AC-4** and the Design/Interface contract. Decision #3 (one image, two entrypoints) was settled by human call 2026-06-11; #1 and #2 were settled in §Runtime topology.
- **Deferred — end-to-end demo (AC-1/AC-2/AC-3).** A trigger launches a per-session agent runtime that drives `start → implement → review → close`, each verb a one-shot container spawned **outside** the agent runtime via the launcher, with context retained across verbs and the outcome read solely from the ledger. Unblocked now that the `HARNESS_WORKSPACE_ROOTS` allowlist ([CAL-584](https://linear.app/calibrate-coffee/issue/CAL-584)) and the host launcher ([CAL-579](https://linear.app/calibrate-coffee/issue/CAL-579)) have shipped. Open before it can be built: the test strategy for the out-of-scope Hermes-side behaviour (AC-1/AC-3 name "Hermes" but changes to Nous' agent are out of scope) — a local stand-in that issues `claude … /harness run <ticket>` and reads `harness status` / `events --json` is the likely shape; confirm before building. Also builds the agent/verb two-entrypoint switch into the image (decision #3).

---

## Notable constraints

- The harness is the sole writer to its SQLite DB. Hermes reads status via the CLI or file-reads on the DB; it does not execute raw SQL.
- Hermes must not embed workflow YAML or contract logic. Workflow authoring lives in the harness repo.
- The interface operations above are the only surface Hermes should use. Direct Python imports from the `harness` package by Hermes code are forbidden.
- This spec covers Hermes ↔ harness integration only. Harness-internal design (engine, nodes, dispatch) is unchanged and continues to follow `SPEC.md` and `specs/`.
