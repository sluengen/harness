"""``harness serve`` starts and stops the maintenance scheduler (#310, AC-1).

A separate module from ``test_cli_serve.py`` for the reason that file's sibling
gives: the subject here is *the wiring line*, not the socket.

**Why this module exists at all.** #408 is an open finding of exactly this
shape: deleting ``broker.start()`` from ``serve_command`` leaves 79 tests green,
because the socket tests call ``build_server`` (which starts no thread) and the
thread tests drive the broker object directly, so nothing observes the one line
that connects them. The sweep must not repeat it, which means a test that drives
``serve_command`` itself rather than either half.

The instrument is not only this test: before handoff the ``scheduler.start()``
line is physically deleted, the suite is run, and the surviving count is
recorded. A count that does not drop means the test is wrong.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app, serve
from harness.maintenance.sweep import MaintenanceScheduler

runner = CliRunner()


class _SpyScheduler:
    """Records the two calls the wiring is supposed to make."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _StubServer:
    """A server that returns from ``serve_forever`` at once."""

    def __init__(self) -> None:
        self.served = 0
        self.closed = 0

    def serve_forever(self) -> None:
        self.served += 1

    def server_close(self) -> None:
        self.closed += 1


def test_serve_command_starts_and_stops_the_sweep_scheduler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wiring line, observed from the command that owns it.

    Driving ``serve_command`` — not ``build_server``, and not the scheduler
    object — is the whole point: a host that constructs a scheduler and never
    starts it sweeps nothing, forever, with every other test in this ticket
    still green.
    """
    spy = _SpyScheduler()
    stub = _StubServer()
    monkeypatch.setattr(
        serve, "build_server", lambda **_kwargs: (stub, None, spy)
    )

    result = runner.invoke(app, ["serve", "--socket", str(tmp_path / "c.sock")])

    assert result.exit_code == 0, result.output
    # The floor: without it, a command that raised before ever reaching the
    # listener would leave `started == 0` and this test would report a wiring
    # defect that is really a fixture defect.
    assert stub.served == 1, "the command never reached its serve loop"
    assert spy.started == 1, (
        "`serve` built a maintenance scheduler and never started it — the host "
        "would run forever without sweeping anything"
    )
    assert spy.stopped == 1, (
        "`serve` never stopped the sweep thread; the `finally` that owns "
        "shutdown must reach it"
    )


def test_the_scheduler_is_stopped_even_when_the_serve_loop_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``stop`` lives in the ``finally``, not after the loop.

    Without this, a ``stop()`` placed on the happy path alone satisfies the test
    above while leaving the thread running through every abnormal exit.
    """
    spy = _SpyScheduler()
    stub = _StubServer()

    def boom() -> None:
        raise KeyboardInterrupt

    stub.serve_forever = boom  # type: ignore[method-assign]
    monkeypatch.setattr(serve, "build_server", lambda **_kwargs: (stub, None, spy))

    result = runner.invoke(app, ["serve", "--socket", str(tmp_path / "c.sock")])

    assert result.exit_code == 0, result.output
    assert spy.stopped == 1


def test_build_server_returns_a_scheduler_bound_to_the_server_and_roots(
    tmp_path: Path,
) -> None:
    """The production constructor produces the object the wiring starts.

    Paired with the test above: one proves the line is called, this proves the
    thing it is called on is real. Either alone is satisfiable by a stub.
    """
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".harness").mkdir(parents=True)
    socket_dir = Path(tempfile.mkdtemp(prefix="hs", dir="/tmp"))
    try:
        built: tuple[Any, Any, Any] = serve.build_server(
            socket_path=socket_dir / "c.sock",
            roots=[tmp_path.resolve()],
            image="harness:dev",
            log=lambda _line: None,
        )
        server, _broker, scheduler = built
        try:
            assert isinstance(scheduler, MaintenanceScheduler)
            assert scheduler._server is server
            assert scheduler.repos() == [repo.resolve()], (
                "the scheduler must sweep the roots the server serves, not a "
                "second repo list"
            )
        finally:
            server.server_close()
    finally:
        shutil.rmtree(socket_dir, ignore_errors=True)
