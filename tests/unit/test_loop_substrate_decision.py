"""CAL-930 — correct the loop substrate: always-on local is the default.

*Source:* corrects CAL-908 (WS3 of `harden-loop-layer`). CAL-908 shipped a
GitHub Actions workflow as the *primary* cloud substrate for the harness's own
loop. That default is wrong on cost and fit:

* the repo is **private** → Actions minutes are metered (~2,000/month free tier);
* the loop is a long-lived agent run (~30–90 min per ticket), not a ~24s CI gate
  — Actions bills the whole wall-clock, so nightly runs would eat/blow the budget;
* Actions is built for short CI jobs, not multi-hour interactive agent sessions;
* the four-loops operating model already had loops running as Claude cloud
  Routines, not GH Actions;
* **always-on local** (`harness-work-pull` → `/harness routine build`) already
  works at zero marginal cost and is the active path.

So the recorded decision is corrected: always-on local is the **default**; a
cloud path stays documented as *optional* via a Claude routine (billed as Claude
usage), explicitly **not** GitHub Actions; and the GH Actions workflow is deleted.
The **per-target-repo gate rule** from CAL-908 is retained (it is substrate-
independent and still true).

This module replaces `test_cloud_loop_workflow.py` (which pinned the now-deleted
workflow). It guards the corrected record.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "harness-loop.yml"
ADR = REPO_ROOT / "specs" / "decisions" / "0001-cloud-runnable-harness-loop.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
HARNESS_CMD = REPO_ROOT / "commands" / "harness.md"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


# --- The mis-fit artifact is gone -------------------------------------------


def test_github_actions_workflow_deleted() -> None:
    """The GH Actions loop workflow is removed — it was the wrong substrate."""
    assert not WORKFLOW.exists(), (
        "the GitHub Actions loop workflow must be deleted: a private repo meters "
        "Actions minutes and the loop is a long agent run, not a cheap CI gate"
    )


# --- The ADR records the corrected decision ---------------------------------


def test_adr_present() -> None:
    """The decision record still exists (reframed, not removed)."""
    assert ADR.exists(), "the substrate decision must remain recorded in the ADR"


def test_adr_defaults_to_always_on_local() -> None:
    """The ADR records always-on local as the default substrate."""
    low = _read(ADR).lower()
    assert "always-on" in low or "always on" in low, (
        "ADR must name always-on local as the default"
    )
    assert "local" in low and "default" in low, (
        "ADR must record local as the default loop substrate"
    )
    assert "harness-work-pull" in low, (
        "ADR must name the working local trigger (harness-work-pull)"
    )


def test_adr_rejects_github_actions_on_cost() -> None:
    """The ADR records *why* GH Actions was rejected: private-repo minute cost."""
    low = _read(ADR).lower()
    assert "github actions" in low or "gh actions" in low, (
        "ADR must name GitHub Actions as the rejected substrate"
    )
    assert "minute" in low, (
        "ADR must record the Actions-minute cost as the rejection reason"
    )
    assert "private" in low, (
        "ADR must note the repo is private (why minutes are metered)"
    )


def test_adr_cloud_option_is_claude_routine_not_actions() -> None:
    """The optional cloud path is a Claude routine, not GitHub Actions."""
    low = _read(ADR).lower()
    assert "routine" in low, (
        "ADR must document the optional cloud path as a Claude routine"
    )


def test_adr_retains_per_target_repo_gate_rule() -> None:
    """The substrate-independent per-target-repo gate rule survives the reframe."""
    low = _read(ADR).lower()
    assert "per-target" in low or "per target" in low or "target repo" in low, (
        "ADR must retain the per-target-repo rule"
    )
    assert "xcode" in low or "macos" in low, (
        "ADR must retain the concrete Xcode/macOS gate constraint"
    )
    assert "gate" in low, "ADR must retain the target's-gate framing"


# --- CONTEXT.md reflects the corrected decision -----------------------------


def test_context_does_not_reference_deleted_workflow() -> None:
    """CONTEXT.md no longer points at the deleted workflow.

    Guard on the workflow *file* (``harness-loop.yml``), not the bare
    ``harness-loop`` substring — the latter also appears in the ADR filename
    ``0001-cloud-runnable-harness-loop.md``, which is still referenced.
    """
    text = _read(CONTEXT)
    assert "harness-loop.yml" not in text, (
        "CONTEXT.md must not reference the deleted harness-loop.yml workflow"
    )
    assert ".github/workflows/harness-loop" not in text, (
        "CONTEXT.md must not point at the deleted workflow path"
    )


def test_context_reflects_local_default() -> None:
    """CONTEXT.md records local-as-default scheduling and still names the ADR."""
    low = _read(CONTEXT).lower()
    assert "local" in low and ("schedul" in low or "loop" in low), (
        "CONTEXT.md must record the local-default scheduling decision"
    )
    text = _read(CONTEXT)
    assert "specs/decisions/" in text and "0001" in text, (
        "CONTEXT.md decisions index must still name ADR 0001"
    )


# --- Routine command coherence ----------------------------------------------


def test_routine_command_does_not_reference_deleted_workflow() -> None:
    """commands/harness.md no longer points at the deleted workflow."""
    assert "harness-loop.yml" not in _read(HARNESS_CMD), (
        "the routine command must not reference the deleted workflow file"
    )


def test_routine_command_not_cloud_out_of_scope_absolute() -> None:
    """The command still does not reassert 'cloud out of scope' as an absolute.

    Always-on local is the default, but a Claude-routine cloud path remains
    possible — so the old absolute must not creep back.
    """
    assert "Cloud execution is out of scope" not in _read(HARNESS_CMD), (
        "a Claude-routine cloud path remains possible; do not reassert the "
        "'cloud out of scope' absolute"
    )
