"""CAL-1015 — the verification gate enforces a coverage floor.

``pytest-cov`` is a dev dependency but the gate ran plain ``pytest``, so line
coverage could silently erode change over change. This wires the floor into the
one gate every merge and release runs (``scripts/verify.sh``): the pytest step
measures the ``harness`` package and fails below ``--cov-fail-under=90`` (90
leaves headroom below the 91% baseline measured 2026-07-06).

The behavioural half of the acceptance criterion — *the current suite passes the
gate* — is proven by running ``scripts/verify.sh`` itself, which now measures
coverage on every invocation; this guard pins the *wiring* so the floor cannot
be silently dropped back to plain pytest (the flags must survive on the pytest
commands, and the floor value is asserted exactly, so a stray ``--cov-fail-under``
with no number would not satisfy it).

**Widened for #358.** The gate now runs *two* pytest stages — ``-m docker``
serially, then ``-m "not docker"`` across the host's cores — sharing one coverage
data file. That makes the floor a claim about a **union** rather than about one
run, so the wiring this module pins grew three parts:

* every stage measures ``--cov=harness``;
* exactly one stage omits ``--cov-append``, and it is **first** — that omission
  *is* the erase, so there is no separate ``coverage erase`` step to forget;
* exactly one stage carries ``--cov-fail-under``, and it is **last** — so the
  floor is evaluated on the union of both stages, which is the same measured
  population the single serial run had (AC-4).

The behavioural proof that combining actually preserves the total — rather than
the wiring merely looking right — is ``test_coverage_combine_equivalence.py``.

Before #358 this module's helper returned only the *first* ``uv run … pytest``
line. Left that way it would have silently checked the docker stage and ignored
the stage that carries the floor, so the helper is now plural and public;
``test_verify_parallel_tiers.py`` imports it rather than re-deriving the parse,
so a mutation to it is visible in both modules (#327).

*Source:* CAL-1015 (review-finding, 2026-07-06 5-dimension assessment); widened
by #358.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "scripts" / "verify.sh"

#: The floor the gate enforces. Chosen below the 91% baseline to leave headroom.
COVERAGE_FLOOR = 90


def pytest_commands() -> list[str]:
    """Every pytest invocation line (non-comment) in ``scripts/verify.sh``, in order.

    The gate runs pytest through ``uv run … pytest …`` commands; return them all
    in source order, so assertions bind to the real invocations rather than to a
    comment that merely mentions pytest, and so a stage cannot escape a check by
    not being the first one. Fails loudly if none exists.

    Public because ``test_verify_parallel_tiers.py`` asserts the *partition* over
    the same parse this module asserts the *coverage wiring* over. One parser,
    two callers — a second inline copy is how a control stops discriminating
    (#327).
    """
    commands = [
        line
        for line in VERIFY.read_text().splitlines()
        if _is_pytest_invocation(line)
    ]
    assert commands, "scripts/verify.sh must run pytest via `uv run … pytest`"
    return commands


def _is_pytest_invocation(line: str) -> bool:
    """Whether *line* is a real ``uv run … pytest …`` command.

    Matched on **argv shape**, not on substrings, because both cheap tests have a
    false positive in this very file: the xdist preflight's error message
    mentions ``'pytest-xdist'`` *and* ``'uv run --extra dev'`` inside a quoted
    string, so a ``"pytest" in line and "uv run" in line`` test reads it as a
    third gate stage. Before #358 that was latent — with one real invocation the
    old helper returned ``lines[0]`` and happened to be right; with the message
    added it would have silently checked an ``echo``.

    So: the statement must *begin* ``uv run``, and ``pytest`` must appear as its
    own token once the line is split the way a shell splits it.
    """
    stripped = line.strip()
    if stripped.startswith("#") or not stripped.startswith("uv run"):
        return False
    try:
        tokens = shlex.split(stripped, comments=True)
    except ValueError:  # unbalanced quotes — not a command we can read
        return False
    return "pytest" in tokens


def test_the_parser_reads_argv_not_substrings() -> None:
    """Control: prose mentioning pytest is not mistaken for a gate stage.

    This is the defect the plural helper was written against, kept as an
    executable case because the real file currently contains exactly such a line
    (the xdist preflight's error message) and a future reword would silently
    retire the evidence. Both samples contain the substrings ``pytest`` and
    ``uv run``; only one is a command.
    """
    command = "uv run --extra dev pytest -m docker --cov=harness"

    # Each rejected sample isolates one half of the predicate: neither half is
    # redundant, and a mutation to either must be visible here. Without both, the
    # two conditions cover for each other and a degradation of one survives.
    rejected = {
        # `pytest` only inside a quoted string → caught by the argv-token half.
        # (The live file has one of these: the xdist preflight's error message.)
        "quoted-substring": (
            "  echo \"gate precondition failed: 'pytest-xdist' is not importable "
            "under 'uv run --extra dev'\" >&2"
        ),
        # `pytest` IS a bare token, but the statement is not a `uv run` command →
        # caught only by the startswith half.
        "bare-token-not-a-command": "  echo uv run pytest",
        # Starts with `uv run`, but pytest appears only inside an argument → caught
        # only by the argv-token half.
        "uv-run-but-not-pytest": 'uv run --extra dev python -c "import pytest"',
    }
    for name, sample in rejected.items():
        assert "pytest" in sample and "uv run" in sample, (
            f"sample {name!r} must carry both substrings, or it does not "
            f"distinguish the argv parse from the cheap containment test"
        )
        assert not _is_pytest_invocation(sample), (
            f"{name!r} is not a gate pytest stage: {sample!r}"
        )
    assert _is_pytest_invocation(command)


def test_the_gates_own_preflight_message_is_not_read_as_a_stage() -> None:
    """The control above, bound to the real file rather than to a sample.

    Pins that the live ``scripts/verify.sh`` yields exactly the stages the gate
    runs, so a reworded message cannot quietly add a phantom stage that the
    coverage assertions would then measure.
    """
    commands = pytest_commands()
    assert all(cmd.strip().startswith("uv run") for cmd in commands), (
        f"a non-command line was parsed as a gate stage: {commands!r}"
    )
    assert len(commands) == 2, (
        f"scripts/verify.sh runs two pytest stages since #358; parsed "
        f"{len(commands)}: {commands!r}"
    )


def test_gate_measures_the_harness_package() -> None:
    """Every pytest stage scopes coverage to the ``harness`` package.

    Asserted over all stages: a stage that dropped ``--cov=harness`` would
    contribute no arcs to the shared data file, silently shrinking the population
    the floor is measured on rather than failing.
    """
    for command in pytest_commands():
        assert "--cov=harness" in command, (
            f"every pytest stage in scripts/verify.sh must pass --cov=harness so "
            f"the coverage floor measures the whole harness package across the "
            f"partition (CAL-1015, #358):\n  {command.strip()}"
        )


def test_gate_enforces_the_coverage_floor() -> None:
    """Exactly one stage carries the floor, with the expected value."""
    commands = pytest_commands()
    carrying = [cmd for cmd in commands if "--cov-fail-under" in cmd]
    assert len(carrying) == 1, (
        f"exactly one pytest stage must carry --cov-fail-under; found "
        f"{len(carrying)}. Two would fail the first stage on a partial "
        f"population; none would drop the floor entirely (CAL-1015, #358)."
    )
    match = re.search(r"--cov-fail-under=(\d+)", carrying[0])
    assert match is not None, (
        "scripts/verify.sh's pytest step must pass --cov-fail-under=<N> so the "
        "gate fails when coverage drops below the floor (CAL-1015)."
    )
    assert int(match.group(1)) == COVERAGE_FLOOR, (
        f"the coverage floor must be {COVERAGE_FLOOR} (90 leaves headroom below "
        f"the 91% baseline); found --cov-fail-under={match.group(1)} (CAL-1015)."
    )


def test_the_floor_is_evaluated_on_the_last_stage() -> None:
    """The floor measures the union, so it must run after every contributing stage.

    On any earlier stage it would fail the gate on a partial population — the
    coverage equivalent of grading before the work is handed in (#358 AC-4).
    """
    commands = pytest_commands()
    assert "--cov-fail-under" in commands[-1], (
        "the coverage floor must be carried by the *last* pytest stage, so it is "
        "evaluated on the union of every stage's arcs rather than on a partial "
        f"population (#358 AC-4). Last stage:\n  {commands[-1].strip()}"
    )


def test_exactly_the_first_stage_resets_the_coverage_data() -> None:
    """One stage omits ``--cov-append``, and it is the first.

    That omission is what erases a stale ``.coverage`` from an earlier session,
    so no run of the gate can inherit a line it did not execute. A second
    non-appending stage would instead *discard* the first stage's arcs, lowering
    the measured total behind a floor that still looked correctly wired — which is
    precisely the "subtly wrong combine" AC-4 names.
    """
    commands = pytest_commands()
    resetting = [i for i, cmd in enumerate(commands) if "--cov-append" not in cmd]
    assert resetting == [0], (
        f"exactly the first pytest stage must omit --cov-append (it is the erase); "
        f"stages omitting it: {resetting} of {len(commands)} (#358 AC-4)."
    )
