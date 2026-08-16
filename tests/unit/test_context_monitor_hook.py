"""#457 AC-3 / AC-6 — the context monitor's threshold and its per-repo state.

``hooks/context-monitor.js`` estimates context usage from the session
transcript's size and warns before the agent loses state. Until #457 nothing had
ever run it: like the other two advisory hooks it was covered only by the
cross-cutting structural guards, all of which pass on a monitor whose thresholds
never fire. A warning that never fires and a warning that fires correctly produce
the same green suite.

The thresholds are **read from the hook**, not restated here, so a case is
expressed as "just over ``WARN``" rather than as a byte count that silently stops
meaning that when the budget is retuned (``craft.md`` → *Exercise the production
path, not merely a production constant*). Tuning ``CONTEXT_BUDGET`` moves every
fixture in this module with it.

AC-6 is the second half. The monitor's state file — the tool-use counter and the
last level it reported — was a fixed name in the machine-wide temp directory, so
two sessions in two checkouts shared one counter: the second session inherited
the first's level, saw no rising edge, and stayed silent about a context that was
already critical. :func:`test_two_sessions_do_not_share_one_threshold_state`
measures that, and :func:`test_the_same_session_is_not_warned_on_every_tool_use`
is its control — scoping the state must not turn the rising-edge report into a
warning on every single tool call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "context-monitor.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _thresholds() -> dict[str, float]:
    """``CONTEXT_BUDGET``, ``WARN`` and ``CRITICAL``, read from the hook.

    ``require()``ing the hook does not run it — the entry point is guarded by
    ``require.main === module`` — so these are the shipped values.
    """
    proc = subprocess.run(
        [
            _node(),
            "-e",
            "const h = require(process.env.HOOK_PATH);"
            "process.stdout.write(JSON.stringify({"
            "CONTEXT_BUDGET: h.CONTEXT_BUDGET, WARN: h.WARN,"
            " CRITICAL: h.CRITICAL, EVERY: h.EVERY}))",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "HOOK_PATH": str(_HOOK)},
    )
    assert proc.returncode == 0, f"could not read the hook's thresholds: {proc.stderr}"
    values: dict[str, float] = json.loads(proc.stdout)
    return values


def _transcript_at(path: Path, fraction: float) -> Path:
    """A transcript file sized so the hook reads it as ``fraction`` of budget.

    The hook's estimate is ``(bytes / 4) / CONTEXT_BUDGET``, so the inverse is
    the fixture. Derived rather than hardcoded: a retuned budget must move the
    fixture, not silently reclassify it.
    """
    limits = _thresholds()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * int(fraction * 4 * limits["CONTEXT_BUDGET"]))
    return path


def _run(session_dir: Path, transcript: Path, *, tmpdir: Path) -> str:
    """Run the monitor for one tool use in ``session_dir``; return its advisory.

    ``session_dir`` is the process working directory, which is what scopes the
    state file; ``tmpdir`` is where that file lands, and callers measuring the
    scoping share one between sessions the way a real machine does.
    """
    payload = {"tool_name": "Read", "transcript_path": str(transcript)}
    proc = subprocess.run(
        [_node(), str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(session_dir),
        env={**os.environ, "TMPDIR": str(tmpdir)},
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    return str(json.loads(proc.stdout).get("additionalContext", ""))


@pytest.fixture
def session(tmp_path: Path) -> tuple[Path, Path]:
    """A session directory and an isolated temp directory for its state."""
    where = tmp_path / "session"
    where.mkdir()
    state = tmp_path / "machine-tmp"
    state.mkdir()
    return where, state


# --- AC-3: the threshold fires, and only above itself -------------------------


def test_the_thresholds_this_module_reads_are_live() -> None:
    """Floor: the hook really exports usable thresholds.

    Every fixture below is derived from these numbers. If the read degraded to
    zeros, every transcript would be "above critical" and the negative control
    would be the only case still saying anything — so the floor is what keeps
    the positive cases from passing for the wrong reason.
    """
    limits = _thresholds()

    assert limits["CONTEXT_BUDGET"] > 0, f"the context budget is not usable: {limits}"
    assert 0 < limits["WARN"] < limits["CRITICAL"] < 1, (
        f"the two thresholds no longer bracket a warn band: {limits}"
    )


def test_a_transcript_past_the_warn_threshold_warns(
    session: tuple[Path, Path], tmp_path: Path
) -> None:
    """Just inside the warn band: the advisory fires, and not at critical."""
    where, state = session
    limits = _thresholds()
    transcript = _transcript_at(
        tmp_path / "t.jsonl", (limits["WARN"] + limits["CRITICAL"]) / 2
    )

    advisory = _run(where, transcript, tmpdir=state)

    assert "[CONTEXT" in advisory, f"no advisory in the warn band; got {advisory!r}"
    assert "Getting full" in advisory, (
        f"the warn band must produce the warn message, not the critical one; got {advisory!r}"
    )


def test_a_transcript_past_the_critical_threshold_says_so(
    session: tuple[Path, Path], tmp_path: Path
) -> None:
    """The two levels are distinguishable, or the second one carries nothing.

    A monitor that reported the same text at both levels would pass a bare
    "warned" assertion at either, and the whole point of the upper threshold is
    that it says something different: stop or hand off, rather than finish the
    current unit of work.
    """
    where, state = session
    limits = _thresholds()
    transcript = _transcript_at(tmp_path / "t.jsonl", limits["CRITICAL"] + 0.05)

    advisory = _run(where, transcript, tmpdir=state)

    assert "Critical" in advisory, (
        f"a transcript past the critical threshold did not report critically; got {advisory!r}"
    )


def test_a_transcript_below_the_threshold_is_silent(
    session: tuple[Path, Path], tmp_path: Path
) -> None:
    """The negative control: a monitor that warned unconditionally would pass
    both cases above, and be noise on every tool call from the first minute."""
    where, state = session
    limits = _thresholds()
    transcript = _transcript_at(tmp_path / "t.jsonl", limits["WARN"] / 2)

    assert _run(where, transcript, tmpdir=state) == "", (
        "the monitor warned about a transcript well under the warn threshold"
    )


def test_a_missing_transcript_is_silent(session: tuple[Path, Path], tmp_path: Path) -> None:
    """The second negative control, on the input the hook cannot read.

    A session whose transcript path does not resolve yields no estimate at all.
    Reporting on it would mean warning about context usage that was never
    measured — an unmeasured claim in the model's own context.
    """
    where, state = session

    assert _run(where, tmp_path / "absent.jsonl", tmpdir=state) == ""


# --- AC-6: the state is scoped to the session's repository --------------------


def test_two_sessions_do_not_share_one_threshold_state(tmp_path: Path) -> None:
    """Two checkouts, one machine temp directory, both past the threshold.

    The state file carries the *last level reported*, and the report is on a
    rising edge. Sharing it means the second session inherits a level it never
    reached, sees no rise, and says nothing — about a context that is already
    critical. Silence is the failure mode, which is why nothing surfaced it.
    """
    shared = tmp_path / "machine-tmp"
    shared.mkdir()
    limits = _thresholds()
    transcript = _transcript_at(tmp_path / "t.jsonl", limits["CRITICAL"] + 0.05)
    first = tmp_path / "checkout-a"
    first.mkdir()
    second = tmp_path / "checkout-b"
    second.mkdir()

    warned_first = _run(first, transcript, tmpdir=shared)
    warned_second = _run(second, transcript, tmpdir=shared)

    assert "Critical" in warned_first, (
        f"the first session drew no warning, so the second proves nothing; got {warned_first!r}"
    )
    assert "Critical" in warned_second, (
        "a second session in another checkout was silenced by the first "
        f"session's threshold state; got {warned_second!r}"
    )


def test_the_same_session_is_not_warned_on_every_tool_use(
    session: tuple[Path, Path], tmp_path: Path
) -> None:
    """The control for the case above: scoping must not delete the debounce.

    Removing the state entirely would pass the scoping test perfectly — every
    session warns, always — and turn a rising-edge nudge into a line appended to
    every single tool result.
    """
    where, state = session
    limits = _thresholds()
    transcript = _transcript_at(tmp_path / "t.jsonl", limits["CRITICAL"] + 0.05)

    first = _run(where, transcript, tmpdir=state)
    second = _run(where, transcript, tmpdir=state)

    assert "Critical" in first, f"the first tool use drew no warning; got {first!r}"
    assert second == "", (
        f"the monitor repeated itself with no rise in level; got {second!r}. It "
        "reports on a rising edge and then at intervals — a nudge on every tool "
        "use is one that gets uninstalled."
    )
