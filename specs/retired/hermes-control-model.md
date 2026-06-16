# Hermes Orchestration (control model) — architecture decision, interface spec, deployment model

> **Superseded 2026-06-14** by proposal [`harness-as-tool`](../proposals/harness-as-tool.md) (accepted 2026-06-09; orchestration-inversion decision in [`architecture-principles`](../architecture-principles.md)). This is the **control half** of the former `specs/hermes-orchestration.md`, extracted in CAL-693: Hermes driving a deterministic harness run — the responsibility boundary, the Option A/B/C co-location/deployment decision, and the engine-era Hermes→harness bridge interface (the `harness run <workflow>` operations and engine-era status enums). Under the verb model there is **one execution model** — a Claude session orchestrates *and* implements, calling `start` / `review` / `close` — with **two triggers** (a human via `/harness run` or Hermes). The observability / runtime-topology half is the now-also-retired [`hermes-orchestration.md`](hermes-orchestration.md) (its launcher/trigger scaffolding was removed in CAL-712). Kept for historical reference only.

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

## Hermes-to-harness interface

Throughout this section, **Hermes** is shorthand for *the harness client*; in the deployed topology that client is the Claude Code session Hermes launches (see the live runtime-topology reference, [`../hermes-orchestration.md`](hermes-orchestration.md)), not the Hermes process itself. The interface must remain stable even as the underlying transport evolves (subprocess → socket → HTTP). The client should never call internal harness Python APIs directly.

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
  artifact_paths      object?    { worktree_path, worktree_branch }
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
| Review output | `review_output` | Set by review workflows |

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

---

## Engine-era bridge roadmap, open questions, and constraints

> The remaining sections are the historical Hermes-bridge implementation roadmap and resolved open questions. The launcher / launch-handle parts that shipped are recorded as-built in the live [`../hermes-orchestration.md`](hermes-orchestration.md) §Runtime topology; the engine-era bridge tickets (subprocess `harness run`, Option A/B packaging) were superseded by the verb model. Kept for historical reference.

## Open questions

1. ~~**Bridge transport for Option B.**~~ **Resolved — see the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology.** The bridge is a **launcher control socket** mounted into the Hermes container, exposing only the verb API (start / status / events / cancel / decision). A thin host **launcher** services it by issuing `docker run harness <verb>` per request and relaying status and events back. The harness runs no persistent daemon; the launcher is the only long-lived process and carries no workflow logic.

2. ~~**Daemon mode.**~~ **Resolved — see the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology.** The harness stays one-shot: each verb is `docker run … && exit`. The socket bridge implies a *launcher* daemon, not a *harness* daemon — a separate minimal host broker for container spawning and status relay. SPEC §16's "no long-running server" non-goal is preserved for the harness itself.

3. **Concurrent run limit.** Mechanism resolved, policy deferred. The launcher is the natural enforcement point — it sees every `docker run` and can cap concurrency per-repo or globally before spawning. Worktrees keep concurrent runs safe (distinct branches), so the cap is about agent API cost and git-lock contention, not correctness. Defer the actual limit until measured; the launcher gives it a home when needed.

4. **Per-run credential scoping.** Mechanism resolved, policy deferred. Because the launcher issues `docker run` per verb, it injects per-run env (`ANTHROPIC_API_KEY` / `LINEAR_API_KEY`) at spawn time — each verb container gets its own scoped credentials with no harness daemon required. Who maps a user/session to a credential set (the policy) is deferred to a multi-user deployment ticket.

5. **Workspace root allowlist management.** Enforcement point resolved, provisioning deferred. The launcher issues every mount, so it enforces `HARNESS_WORKSPACE_ROOTS` (combined with the path-equivalence rule in the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology). Static configuration is a launcher-level env var set at deploy time. Dynamic mounting of new repos at run time still needs a provisioning API — deferred until a workflow requires it.

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

`harness status --json` now includes `failure_reason`, `failure_retryable`, `artifact_paths`, and `agent_session_ids`. `harness events` now accepts `--after-id <integer>` for incremental polling. See `specs/retired/cli.md` §`harness status` and §`harness events` for the full field reference. (`current_node` was also shipped here but removed in CAL-589: it derived from `node_started`, which the retired engine was the only producer of — it was always `null` under the verb model.)

### Ticket 3: Container packaging — separate-container deployment (Option B)

Define the Dockerfile and compose/task-definition shape for Option B deployment.

- Produce a harness container image with the harness binary and its dependencies; no Hermes code.
- Define a compose file (or ECS task definition) with both containers sharing a named workspace volume.
- Document the env var injection strategy for secret scoping (which secrets go to which container).
- ~~Add `HARNESS_WORKSPACE_ROOTS` allowlist enforcement to the CLI.~~ ✓ shipped ([CAL-584](https://linear.app/calibrate-coffee/issue/CAL-584)) — the "Ticket 3 survivor"; see the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Target repo allowlist. `harness/workspace.py` is the launcher prerequisite for Ticket 4.
- Acceptance: `docker compose up` starts both containers; Hermes can drive a harness run against a repo mounted on the shared volume.

### Ticket 4: Host launcher — narrow control socket for verb-container launch ([CAL-579](https://linear.app/calibrate-coffee/issue/CAL-579))

Build the host-side launcher chosen over DooD in the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology. Hermes drives verbs through a narrow control socket; the launcher constructs each `docker run` itself so the caller never specifies the mount, privilege, image, or env.

- Expose a control socket (not `/var/run/docker.sock`) offering only the harness verb operations: start / status / events / cancel / decision.
- Construct each verb container server-side; pick mounts from the `HARNESS_WORKSPACE_ROOTS` allowlist (depends on Ticket 3); inject scoped per-run credentials.
- One-shot sibling containers (max one container deep; no DinD); thin local form factor (e.g. `harness serve --local`).
- Acceptance: with only the control socket mounted, Hermes can run a verb end-to-end; a test asserts a caller-supplied host path / privilege flag is rejected (host-escape vector closed); a test asserts mounts outside `HARNESS_WORKSPACE_ROOTS` are rejected.

**Implemented** in `harness/launcher.py` + `harness/cli/serve.py` ([CAL-579](https://linear.app/calibrate-coffee/issue/CAL-579)). The launcher speaks newline-delimited JSON over an `AF_UNIX` socket (`harness serve --local`), exposing exactly `{start, status, events, cancel, decision}` and nothing else — an unknown op is refused before any `docker run`. `build_verb_argv()` constructs each launch server-side: the only caller-derived value entering the docker-option region is the *resolved* repo path (checked through `harness/workspace.py`'s allowlist), mounted at an identical host/container path (`-v <repo>:<repo> -w <repo>`); everything else the caller supplies lands after the image as harness-verb arguments, so `--privileged` / `-v /:/host` / a rogue image / a caller-set env are not expressible. Params are an allowlist per op (any extra key — `privileged`, `volumes`, `image`, `env`, …  — is rejected as `bad_params`), and per-run credentials are injected by name (`-e NAME`) so secret values never enter the argv. Every launch is `docker run --rm` — a one-shot, unprivileged sibling removed on exit. Covered by `tests/unit/test_launcher.py`, `tests/unit/test_cli_serve.py`, and the over-the-wire `tests/integration/test_launcher_socket.py`.

### Ticket 5: Hermes launch handle — decisions + contract, then end-to-end demo ([CAL-576](https://linear.app/calibrate-coffee/issue/CAL-576))

The thin launch handle (`claude … /harness run <ticket>`) plus the container-invocation topology the supersession header defers to this ticket. Split into the independently-buildable decisions/contract half and the end-to-end demo that depends on the launcher (Ticket 4) landing.

- **Path A — decisions + contract (recorded).** The three decision blocks (agent-runtime hosting + docker handle; headless vs. TTY; image roles) and the launch-handle contract (launch command, credential/worktree threading, read-only ledger readback) are recorded in the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology → *Launch handle and decision record*. This satisfies **AC-4** and the Design/Interface contract. Decision #3 (one image, two entrypoints) was settled by human call 2026-06-11; #1 and #2 were settled in the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology.
- **Shipped — end-to-end demo (AC-1/AC-2/AC-3), [CAL-585](https://linear.app/calibrate-coffee/issue/CAL-585).** A trigger launches a per-session agent runtime that drives `start → implement → review → close`, each verb a one-shot container spawned **outside** the agent runtime via the launcher, with context retained across verbs and the outcome read solely from the ledger. Unblocked by the `HARNESS_WORKSPACE_ROOTS` allowlist ([CAL-584](https://linear.app/calibrate-coffee/issue/CAL-584)) and the host launcher ([CAL-579](https://linear.app/calibrate-coffee/issue/CAL-579)). The Hermes-side test strategy (changes to Nous' agent are out of scope) was settled with the human 2026-06-11 as a **local stand-in** that issues `claude … /harness run <ticket>` and reads `harness status` / `events --json` read-only. As-built: the launcher now exposes the full `start`/`review`/`close` lifecycle over the socket; the two-entrypoint switch is built into the image (decision #3); the stand-in and its end-to-end demonstration live in `harness/trigger.py` and `tests/integration/test_hermes_demo.py`. See the live runtime-topology reference ([`../hermes-orchestration.md`](hermes-orchestration.md)) §Runtime topology → *As-built: launch handle end-to-end*.

---

## Notable constraints

- The harness is the sole writer to its SQLite DB. Hermes reads status via the CLI or file-reads on the DB; it does not execute raw SQL.
- Hermes must not embed workflow YAML or contract logic. Workflow authoring lives in the harness repo.
- The interface operations above are the only surface Hermes should use. Direct Python imports from the `harness` package by Hermes code are forbidden.
- This spec covers Hermes ↔ harness integration only. Harness-internal design (engine, nodes, dispatch) is unchanged and continues to follow `SPEC.md` and `specs/`.
