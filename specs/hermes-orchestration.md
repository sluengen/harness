# Hermes Orchestration — architecture decision, interface spec, deployment model

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
  current_node        string?    step.id of the currently executing node
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
  outcome             "cancelled" | "not_running"

Exit code: 0 on accepted, 2 if run not found or already terminal.
```

CLI form: `harness cancel <run-id>`

Cancellation is cooperative. The harness delivers SIGTERM to the running process; the runner's signal handler emits `workflow_failed` with `reason='cancelled'`, runs cleanup nodes (worktree teardown), and exits 130.

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
| `current_node` | string? | latest `node_started` event |
| `started_at` | ISO 8601 | `runs.started_at` |
| `completed_at` | ISO 8601? | `runs.completed_at` |
| `duration_ms` | integer? | `runs.duration_ms` |
| `exit_code` | integer? | `runs.exit_code` |
| `failure_reason` | string? | `data.reason` from the latest `workflow_failed` event |
| `failure_retryable` | bool? | derived from `failure_reason` |
| `artifact_paths` | object? | from `runs.state_json` key fields |
| `agent_session_ids` | list[str]? | from `tool_called` events |

`current_node` and `agent_session_ids` require a lightweight query against the events table. Both are included in `harness status --json` output.

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

Three tickets are required to move from spec to shipped:

### Ticket 1: Hermes-to-harness bridge — subprocess + JSON protocol (Option A)

Implement the Option A bridge so Hermes can drive the harness as a subprocess.

- Add `--json-run-id` flag to `harness run` that emits the run_id as the first stdout line (JSON).
- Document the subprocess invocation pattern and output contract.
- Wire up Hermes to invoke `harness run`, capture `run_id`, and poll `harness status --json`.
- Acceptance: Hermes can start a harness run, poll status, and surface completion to the user.

### ~~Ticket 2: Run status enrichment — current_node, agent_session_ids, after-id polling~~ ✓ shipped

`harness status --json` now includes `current_node`, `failure_reason`, `failure_retryable`, `artifact_paths`, and `agent_session_ids`. `harness events` now accepts `--after-id <integer>` for incremental polling. See `specs/cli.md` §`harness status` and §`harness events` for the full field reference.

### Ticket 3: Container packaging — separate-container deployment (Option B)

Define the Dockerfile and compose/task-definition shape for Option B deployment.

- Produce a harness container image with the harness binary and its dependencies; no Hermes code.
- Define a compose file (or ECS task definition) with both containers sharing a named workspace volume.
- Document the env var injection strategy for secret scoping (which secrets go to which container).
- Add `HARNESS_WORKSPACE_ROOTS` allowlist enforcement to the CLI.
- Acceptance: `docker compose up` starts both containers; Hermes can drive a harness run against a repo mounted on the shared volume.

---

## Notable constraints

- The harness is the sole writer to its SQLite DB. Hermes reads status via the CLI or file-reads on the DB; it does not execute raw SQL.
- Hermes must not embed workflow YAML or contract logic. Workflow authoring lives in the harness repo.
- The interface operations above are the only surface Hermes should use. Direct Python imports from the `harness` package by Hermes code are forbidden.
- This spec covers Hermes ↔ harness integration only. Harness-internal design (engine, nodes, dispatch) is unchanged and continues to follow `SPEC.md` and `specs/`.
