"""CAL-908 — make the harness's own loop cloud-runnable + record the per-repo gate rule.

*Source:* ``specs/proposals/harden-loop-layer.md`` (WS3, decision C2); CAL-908.
Origin: the *Loop Engineering* field study, §VII.C/D ("laptops get their lids
closed" — the overnight sweep belongs in the cloud).

WS3 is the close-out of the harden-loop-layer proposal. WS1 (CAL-906, the
spend-breakers) and WS2 (CAL-907, the de-drifted skill-based routine) landed
first; WS3 wires the harness's **own** Build/Quality loop onto a cloud schedule.
The proposal's corrected finding is that this is a *secrets-wiring + engine-
selection* job, not a re-architecture: the full gate already runs green on
``ubuntu-latest`` in CI, the verbs run in-process off the native ``harness``
entry point, and the only Mac-local pieces are credential *sourcing* — each
becomes a standard cloud secret.

This module is the structural guard for the WS3 deliverables. It does not (and
cannot, from a repo tick) prove a live cloud run — that requires the operator to
provision the three secrets and dispatch once. It pins the *versioned* artifacts
so they cannot silently drift or regress:

* **AC — cloud schedule, credentials as secrets.** A versioned GitHub Actions
  workflow runs the loop on a ``schedule:`` cron (plus ``workflow_dispatch`` for
  the operator's on-demand first run), on ``ubuntu-latest`` (the CI-proven gate
  substrate), reading every credential from ``secrets.*`` and never hardcoding
  one. Proven by :func:`test_workflow_present`,
  :func:`test_workflow_scheduled_and_dispatchable`,
  :func:`test_workflow_runs_on_ubuntu`,
  :func:`test_workflow_reads_credentials_from_secrets`,
  :func:`test_workflow_hardcodes_no_secret`.
* **AC — Claude review engine, clean-clone reconciled via Linear-keyed
  reclamation.** The cloud loop selects the Claude engine (never ``--engine
  codex``, whose ``~/.codex`` subscription auth does not travel as a secret) and
  runs the Linear-keyed reclaim pre-flight so a fresh clone with no local DB
  reconciles. Proven by :func:`test_workflow_uses_claude_engine`,
  :func:`test_workflow_installs_harness_natively`,
  :func:`test_workflow_runs_linear_keyed_reclaim_preflight`.
* **AC — ADR records the decision + the per-target-repo gate rule.** A
  ``specs/decisions/`` ADR (the first one) records: cloud for the harness's own
  loop, the secrets/engine setup, and — loudly — that cloud-viability is set by
  the *target repo's* gate (an Xcode/macOS-bound target stays local or on a
  macOS runner). Proven by :func:`test_adr_present`,
  :func:`test_adr_records_secrets_and_engine`,
  :func:`test_adr_states_per_target_repo_gate_rule`.
* **AC — CONTEXT.md reflects the decision (no longer local-only / "out of
  scope").** Proven by :func:`test_context_reflects_cloud_decision`,
  :func:`test_context_decisions_index_names_adr`.
* **Coherence — the routine command's local-trigger note is reconciled.** The
  old "Cloud execution is out of scope" absolute is replaced by the distinction
  the decision draws: the Docker-wrapper regime is local-trigger, but the
  harness's own loop has a cloud path (native install + secrets). Proven by
  :func:`test_routine_command_reconciles_cloud_path`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-loop.yml"
ADR = REPO_ROOT / "specs" / "decisions" / "0001-cloud-runnable-harness-loop.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
HARNESS_CMD = REPO_ROOT / "commands" / "harness.md"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


# --- The cloud workflow: scheduled, credentialed by secrets -----------------


def test_workflow_present() -> None:
    """The versioned cloud-deployment artifact exists in the repo."""
    assert WORKFLOW.exists(), (
        "the harness's own loop must be cloud-runnable via a versioned workflow "
        f"at {WORKFLOW.relative_to(REPO_ROOT)}"
    )


def test_workflow_scheduled_and_dispatchable() -> None:
    """Fires on a cron schedule (the overnight sweep) and by manual dispatch.

    ``schedule:`` is the autonomous overnight trigger; ``workflow_dispatch``
    lets the operator run the first, demonstrating run on demand.
    """
    text = _read(WORKFLOW)
    assert "schedule:" in text, "workflow must carry a schedule: (cron) trigger"
    assert re.search(r"-\s*cron:", text), "schedule must define a cron entry"
    assert "workflow_dispatch:" in text, (
        "workflow must be manually dispatchable so the operator can run the "
        "first demonstrating run without waiting for the cron"
    )


def test_workflow_runs_on_ubuntu() -> None:
    """Runs on ubuntu-latest — the exact substrate CI already proves green."""
    text = _read(WORKFLOW)
    assert "ubuntu-latest" in text, (
        "the cloud loop must run on ubuntu-latest (the CI-proven Linux gate), "
        "not a macOS runner — the harness's own gate has no Xcode/macOS deps"
    )


def test_workflow_reads_credentials_from_secrets() -> None:
    """Every credential is sourced from ``secrets.*`` (the cloud-secret model)."""
    text = _read(WORKFLOW)
    # LINEAR_API_KEY and the Claude auth token both flow from secrets, replacing
    # the Mac-local .env / Keychain sourcing.
    assert "secrets.LINEAR_API_KEY" in text, (
        "LINEAR_API_KEY must come from a repo secret, not .env, in the cloud"
    )
    assert re.search(r"secrets\.(CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY)", text), (
        "the Claude auth token must come from a repo secret "
        "(CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY)"
    )


def test_workflow_hardcodes_no_secret() -> None:
    """No literal credential is committed — secrets flow only through ``secrets.*``."""
    text = _read(WORKFLOW)
    # A real Linear key is `lin_api_...`; a real Anthropic key is `sk-ant-...`.
    assert "lin_api_" not in text, "no literal Linear key may be committed"
    assert "sk-ant-" not in text, "no literal Anthropic key may be committed"


def test_workflow_installs_harness_natively() -> None:
    """The cloud loop installs the harness via its native entry point (no Docker).

    The proposal's load-bearing correction: the verbs run in-process off the
    ``uv``-installed console script, so the cloud path needs no Docker-in-Docker
    and no ``~/bin/harness`` wrapper.
    """
    text = _read(WORKFLOW)
    assert "uv " in text or "uv\n" in text, "workflow must use uv to install/run"
    assert "harness" in text, "workflow must install/run the native harness entry point"


def test_workflow_uses_claude_engine() -> None:
    """The cloud loop uses the Claude review engine, never Codex.

    Codex's ``~/.codex`` subscription auth does not travel as a cloud secret and
    is bwrap-blocked in-container anyway (CAL-866); the cloud loop must not force
    ``--engine codex``.
    """
    text = _read(WORKFLOW)
    assert "--engine codex" not in text, (
        "the cloud loop must not select the Codex engine — its ~/.codex auth "
        "does not travel as a secret; the Claude engine is the cloud default"
    )
    assert "claude" in text.lower(), (
        "the workflow must name the Claude engine/agent it drives the loop with"
    )


def test_workflow_runs_linear_keyed_reclaim_preflight() -> None:
    """A fresh clone with no local DB reconciles via the Linear-keyed sweep.

    The routine's Step 0 reclaim sweep keys entirely on Linear, so it works in
    the fresh-clone / no-local-DB cloud regime. The workflow must run it (either
    directly via the CLI or by driving ``/harness routine build``, which runs it
    as Step 0).
    """
    text = _read(WORKFLOW)
    assert "reclaim" in text or "routine build" in text, (
        "the cloud loop must run the Linear-keyed reclaim pre-flight (directly, "
        "or via /harness routine build whose Step 0 is that sweep)"
    )
    assert "--project" in text or "routine build" in text, (
        "the reclaim sweep is keyed on the Linear project (--project) so it "
        "reconciles without a local ledger"
    )


# --- The ADR: decision + the per-target-repo gate rule ----------------------


def test_adr_present() -> None:
    """The first specs/decisions ADR exists."""
    assert ADR.exists(), (
        "WS3 must record the decision in a specs/decisions/ ADR (the first one)"
    )


def test_adr_records_secrets_and_engine() -> None:
    """The ADR records the secrets/engine setup for the cloud loop."""
    text = _read(ADR).lower()
    assert "linear_api_key" in text, "ADR must name the LINEAR_API_KEY secret"
    assert "claude" in text and "engine" in text, (
        "ADR must record that the cloud loop uses the Claude review engine"
    )
    assert "secret" in text, "ADR must record the cloud-secret credential model"


def test_adr_states_per_target_repo_gate_rule() -> None:
    """The ADR states — loudly — the per-target-repo gate constraint.

    'The harness runs its own loop in the cloud' must NOT be read as 'the harness
    runs any repo in the cloud'. A target whose gate needs Xcode/macOS tooling
    stays local or on a macOS runner.
    """
    text = _read(ADR).lower()
    assert "per-target" in text or "per target" in text or "target repo" in text, (
        "ADR must state that cloud-viability is per-target-repo"
    )
    assert "xcode" in text or "macos" in text, (
        "ADR must give the concrete constraint: an Xcode/macOS-bound target's "
        "gate keeps it local or on a macOS runner"
    )
    assert "gate" in text, "ADR must frame the constraint as set by the target's gate"


# --- CONTEXT.md reflects the decision ---------------------------------------


def test_context_reflects_cloud_decision() -> None:
    """CONTEXT.md no longer frames scheduling as local-only / out of scope.

    AC-5: scheduling is no longer silent or 'empty by design' — CONTEXT records
    that the harness's own loop runs on a cloud schedule.
    """
    text = _read(CONTEXT)
    low = text.lower()
    assert "cloud" in low and "schedule" in low, (
        "CONTEXT.md must record the cloud-schedule decision for the own loop"
    )
    assert "harness-loop.yml" in text or "harness-loop" in text, (
        "CONTEXT.md must point at the versioned cloud workflow"
    )


def test_context_decisions_index_names_adr() -> None:
    """The Decisions index points at the new ADR rather than saying none exists."""
    text = _read(CONTEXT)
    assert "specs/decisions/" in text, (
        "CONTEXT.md decisions index must reference specs/decisions/"
    )
    assert "0001" in text or "cloud-runnable-harness-loop" in text, (
        "CONTEXT.md decisions index must name the first ADR"
    )


# --- Routine command coherence ----------------------------------------------


def test_routine_command_reconciles_cloud_path() -> None:
    """commands/harness.md no longer asserts cloud execution is out of scope.

    The old absolute ('Cloud execution is out of scope') is now false for the
    harness's own loop. The command must draw the distinction the decision makes:
    the local Docker-wrapper regime is local-trigger, but the harness's own loop
    has a cloud path (native install + secrets), and point at the ADR/workflow.
    """
    text = _read(HARNESS_CMD)
    assert "Cloud execution is out of scope" not in text, (
        "the out-of-scope absolute contradicts the WS3 decision — reconcile it"
    )
    low = text.lower()
    assert "cloud" in low, "the routine command must address the cloud path"
    assert "harness-loop" in text or "specs/decisions/" in text or "adr" in low, (
        "the routine command must point at the cloud workflow / ADR"
    )
