"""Tests for harness.engine.progress — terminal progress reporter (CAL-507).

Each test maps to one acceptance criterion:
1. node_started → prints "[wf] node_id         started\n"
2. node_completed with duration → prints "[wf] node_id         completed (0.1s)\n"
3. node_failed → prints "[wf] node_id         failed\n"
4. workflow_started (node_id=None) → prints "[wf] (workflow)       started\n"
5. workflow_completed → prints "[wf] (workflow)       completed (Xs)\n"
6. workflow_failed → prints "[wf] (workflow)       failed\n"
7. Unrelated event types (tool_called, state_changed) → no output
8. Duration formatting: <10s shows one decimal (1.2s), >=10s shows integer (892s)
9. Default file is sys.stderr
"""

from __future__ import annotations

import io
import sys

import pytest

from harness.engine.progress import ProgressReporter

_NODE_COL_WIDTH = 16


def _make(workflow_name: str = "build") -> tuple[ProgressReporter, io.StringIO]:
    buf = io.StringIO()
    reporter = ProgressReporter(workflow_name, file=buf)
    return reporter, buf


# ---------------------------------------------------------------------------
# AC1 — node_started
# ---------------------------------------------------------------------------


def test_node_started_prints_started_line() -> None:
    reporter, buf = _make("build")
    reporter("node_started", "setup", None)
    output = buf.getvalue()
    assert "[build]" in output
    assert "setup" in output
    assert "started" in output
    assert output.endswith("\n")


def test_node_started_format() -> None:
    reporter, buf = _make("build")
    reporter("node_started", "setup", None)
    line = buf.getvalue()
    # Label is left-padded to _NODE_COL_WIDTH
    expected = f"[build] {'setup':<{_NODE_COL_WIDTH}} started\n"
    assert line == expected


# ---------------------------------------------------------------------------
# AC2 — node_completed with duration
# ---------------------------------------------------------------------------


def test_node_completed_with_short_duration() -> None:
    """< 10 seconds → one decimal (e.g. 0.1s)."""
    reporter, buf = _make("build")
    reporter("node_completed", "setup", 100)  # 100 ms = 0.1s
    line = buf.getvalue()
    assert "completed" in line
    assert "0.1s" in line


def test_node_completed_format_short() -> None:
    reporter, buf = _make("build")
    reporter("node_completed", "setup", 100)
    line = buf.getvalue()
    expected = f"[build] {'setup':<{_NODE_COL_WIDTH}} completed (0.1s)\n"
    assert line == expected


def test_node_completed_with_long_duration() -> None:
    """≥ 10 seconds → integer (e.g. 892s, not 892.0s)."""
    reporter, buf = _make("build")
    reporter("node_completed", "implement", 892000)  # 892s
    line = buf.getvalue()
    assert "892s" in line
    assert "." not in line.split("(")[1]


def test_node_completed_format_long() -> None:
    reporter, buf = _make("build")
    reporter("node_completed", "implement", 892000)
    line = buf.getvalue()
    expected = f"[build] {'implement':<{_NODE_COL_WIDTH}} completed (892s)\n"
    assert line == expected


def test_node_completed_exactly_10s() -> None:
    """Exactly 10s boundary → integer (10s)."""
    reporter, buf = _make("build")
    reporter("node_completed", "step", 10000)
    line = buf.getvalue()
    assert "10s" in line
    assert "." not in line.split("(")[1]


# ---------------------------------------------------------------------------
# AC3 — node_failed
# ---------------------------------------------------------------------------


def test_node_failed_prints_failed_line() -> None:
    reporter, buf = _make("build")
    reporter("node_failed", "setup", None)
    line = buf.getvalue()
    assert "[build]" in line
    assert "setup" in line
    assert "failed" in line
    assert line.endswith("\n")


def test_node_failed_format() -> None:
    reporter, buf = _make("build")
    reporter("node_failed", "setup", None)
    line = buf.getvalue()
    expected = f"[build] {'setup':<{_NODE_COL_WIDTH}} failed\n"
    assert line == expected


# ---------------------------------------------------------------------------
# AC4 — workflow_started (node_id=None)
# ---------------------------------------------------------------------------


def test_workflow_started_uses_workflow_label() -> None:
    reporter, buf = _make("build")
    reporter("workflow_started", None, None)
    line = buf.getvalue()
    assert "(workflow)" in line
    assert "started" in line


def test_workflow_started_format() -> None:
    reporter, buf = _make("build")
    reporter("workflow_started", None, None)
    line = buf.getvalue()
    expected = f"[build] {'(workflow)':<{_NODE_COL_WIDTH}} started\n"
    assert line == expected


# ---------------------------------------------------------------------------
# AC5 — workflow_completed
# ---------------------------------------------------------------------------


def test_workflow_completed_with_duration() -> None:
    reporter, buf = _make("build")
    reporter("workflow_completed", None, 12000)  # 12s
    line = buf.getvalue()
    assert "completed" in line
    assert "12s" in line


def test_workflow_completed_format() -> None:
    reporter, buf = _make("build")
    reporter("workflow_completed", None, 5000)  # 5.0s
    line = buf.getvalue()
    expected = f"[build] {'(workflow)':<{_NODE_COL_WIDTH}} completed (5.0s)\n"
    assert line == expected


# ---------------------------------------------------------------------------
# AC6 — workflow_failed
# ---------------------------------------------------------------------------


def test_workflow_failed_prints_failed_line() -> None:
    reporter, buf = _make("build")
    reporter("workflow_failed", None, None)
    line = buf.getvalue()
    assert "(workflow)" in line
    assert "failed" in line


def test_workflow_failed_format() -> None:
    reporter, buf = _make("build")
    reporter("workflow_failed", None, None)
    line = buf.getvalue()
    expected = f"[build] {'(workflow)':<{_NODE_COL_WIDTH}} failed\n"
    assert line == expected


# ---------------------------------------------------------------------------
# AC7 — unrelated events produce no output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_type",
    [
        "tool_called",
        "tool_completed",
        "state_changed",
        "loop_iteration",
        "retry_attempted",
        "decision_requested",
        "decision_made",
        "decision_received",
        "decision_timeout",
        "decision_violation",
        "workflow_paused",
    ],
)
def test_non_lifecycle_event_produces_no_output(event_type: str) -> None:
    reporter, buf = _make("build")
    reporter(event_type, None, None)
    assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# AC8 — duration formatting edge cases
# ---------------------------------------------------------------------------


def test_duration_just_below_10s_shows_decimal() -> None:
    """9.9s → '9.9s' (one decimal)."""
    reporter, buf = _make("build")
    reporter("node_completed", "step", 9900)
    line = buf.getvalue()
    assert "9.9s" in line


def test_duration_zero_shows_decimal() -> None:
    """0ms → '0.0s'."""
    reporter, buf = _make("build")
    reporter("node_completed", "step", 0)
    line = buf.getvalue()
    assert "0.0s" in line


def test_duration_none_shows_zero() -> None:
    """None duration_ms → treated as 0ms."""
    reporter, buf = _make("build")
    reporter("node_completed", "step", None)
    line = buf.getvalue()
    assert "0.0s" in line


# ---------------------------------------------------------------------------
# AC9 — default file is sys.stderr
# ---------------------------------------------------------------------------


def test_default_file_is_stderr() -> None:
    reporter = ProgressReporter("wf")
    # Access the internal _file attribute to verify; we don't actually
    # write because stderr is shared in tests.
    assert reporter._file is sys.stderr
