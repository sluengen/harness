"""The cadence check runs on the release PR — and *only* there (#350).

``scripts/cadence.py check`` is the enforcing half of the cadence bounds the
gate only reports. If nothing ran it, the bounds would be advisory and the
release could ship over them; if it ran on *every* PR, it would be the gate
again under a new name and would rebuild the exact wedge #350 removed — five
unattended build ticks that shipped nothing because a release-cadence signal was
indistinguishable from a correctness one.

So both halves are pinned here, and the **condition** is the load-bearing one: a
test asserting only that some job runs ``cadence.py check`` would pass on the
regression that matters most.

The workflow is parsed as text (PyYAML is not a project dependency), matching
``tests/unit/test_ci_workflow_permissions.py``.

*Source:* #350.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The job that enforces the bounds, and the command it must run.
_JOB = "release-cadence:"
_COMMAND = "scripts/cadence.py check"

#: The release is the ``staging → main`` PR (RELEASING.md), so that is the only
#: event this job may fire on.
_CONDITION = "github.base_ref == 'main'"


def _ci_text() -> str:
    return _CI.read_text(encoding="utf-8")


def test_ci_declares_the_release_cadence_job() -> None:
    """A job exists to enforce the cadence bounds."""
    text = _ci_text()
    assert _JOB in text, (
        "ci.yml must declare a `release-cadence` job — without it the cadence "
        "bounds moved out of the gate by #350 are enforced nowhere and a "
        "release can ship over them."
    )
    assert _COMMAND in text, (
        f"the release-cadence job must run `{_COMMAND}` — `report` never fails, "
        "so a job running it would enforce nothing."
    )


def test_the_cadence_job_is_scoped_to_the_release_pr() -> None:
    """It fires on a PR into ``main``, never on an ordinary change.

    The regression this exists for: dropping the condition puts a cadence bound
    back in every change's path, which is #350 rebuilt in a new place.
    """
    text = _ci_text()
    assert _CONDITION in text, (
        f"the release-cadence job must be conditioned on `{_CONDITION}`. "
        "Unconditioned, it blocks every PR on accumulated repo state no single "
        "change caused or can fix — the wedge #350 removed."
    )

    lines = _ci_text().splitlines()
    job_at = next(i for i, line in enumerate(lines) if _JOB in line)
    command_at = next(i for i, line in enumerate(lines) if _COMMAND in line)
    condition_at = next(i for i, line in enumerate(lines) if _CONDITION in line)
    assert job_at < condition_at < command_at, (
        "the condition must belong to the release-cadence job that runs the "
        f"check (job at line {job_at + 1}, condition at {condition_at + 1}, "
        f"command at {command_at + 1})."
    )


def test_the_gate_job_does_not_run_the_cadence_check() -> None:
    """``lint-and-test`` runs the gate, and the gate never enforces cadence."""
    text = _ci_text()
    before_cadence_job = text.split(_JOB)[0]
    assert _COMMAND not in before_cadence_job, (
        "the correctness job must not run `cadence.py check` — that is the "
        "conflation #350 removed."
    )


def test_pull_request_trigger_covers_main() -> None:
    """The job's condition is unreachable unless the trigger fires for ``main``."""
    text = _ci_text()
    assert "pull_request:" in text
    trigger = text.split("pull_request:", 1)[1].split("\n\n", 1)[0]
    assert "main" in trigger, (
        "ci.yml's pull_request trigger must include `main`, or the "
        "release-cadence job never runs and its condition is dead code."
    )
