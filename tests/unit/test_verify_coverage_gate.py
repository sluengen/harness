"""CAL-1015 — the verification gate enforces a coverage floor.

``pytest-cov`` is a dev dependency but the gate once ran plain ``pytest``, so
line coverage could silently erode change over change. The floor is wired into
the one gate every merge and release runs (``scripts/verify.sh``). The
behavioural half of the criterion — *the current suite clears the floor* — is
proven by running ``scripts/verify.sh`` itself; this guard pins the *wiring*, so
the floor cannot be quietly dropped back to plain pytest. The value is asserted
exactly, so a stray ``--cov-fail-under`` with no number would not satisfy it.

**#435 re-anchored this on the single surviving stage.** #358 had split the gate
into ``-m docker`` (serial) then ``-m "not docker"`` (parallel) sharing one
coverage data file, which made the floor a claim about a *union* and needed three
extra wiring assertions: every stage measuring the same package, exactly one
stage omitting ``--cov-append`` and it first, exactly one carrying the floor and
it last. ADR 0015 retires the container, so every docker-marked test is gone and
the gate runs one stage. Those three union assertions describe a partition that
no longer exists and went with it; what survives is the part that never depended
on the partition — the argv parse, its controls, the measured tree, and the floor
itself. The subject moved from ``--cov=harness`` to ``--cov=scripts``: ``scripts/``
is the only executable code the repo still owns.

*Source:* CAL-1015 (review-finding, 2026-07-06 5-dimension assessment); widened
by #358, narrowed by #435.
"""

from __future__ import annotations

import re
import shlex

from tests.unit._prose import REPO_ROOT

VERIFY = REPO_ROOT / "scripts" / "verify.sh"

#: The floor the gate enforces, set just under the coverage measured at the
#: time it was last raised. A ratchet, not a target: raise it when coverage
#: rises. 79 at the #435 teardown; 82 since #436 added ``scripts/gate_marker.py``
#: with tests that actually exercise it (measured 82.12%).
COVERAGE_FLOOR = 82

#: The tree coverage is measured over — the only executable code the repo owns
#: since ADR 0015 deleted the ``harness`` package.
COVERAGE_TARGET = "--cov=scripts"


def pytest_commands() -> list[str]:
    """Every pytest invocation line (non-comment) in ``scripts/verify.sh``, in order.

    The gate runs pytest through ``uv run … pytest …`` commands; return them all
    in source order, so assertions bind to the real invocations rather than to a
    comment that merely mentions pytest, and so a stage cannot escape a check by
    not being the first one. Fails loudly if none exists.
    """
    commands = [
        line for line in VERIFY.read_text().splitlines() if _is_pytest_invocation(line)
    ]
    assert commands, "scripts/verify.sh must run pytest via `uv run … pytest`"
    return commands


def _is_pytest_invocation(line: str) -> bool:
    """Whether *line* is a real ``uv run … pytest …`` command.

    Matched on **argv shape**, not on substrings, because both cheap tests have a
    false positive in this very file: the xdist preflight's error message
    mentions ``'pytest-xdist'`` *and* ``'uv run --extra dev'`` inside a quoted
    string, so a ``"pytest" in line and "uv run" in line`` test reads it as a
    second gate stage.

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

    This is the defect the argv parse was written against, kept as an executable
    case because the real file currently contains exactly such a line (the xdist
    preflight's error message) and a future reword would silently retire the
    evidence. Both samples contain the substrings ``pytest`` and ``uv run``; only
    one is a command.
    """
    command = "uv run --extra dev pytest -n auto --cov=scripts"

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
    coverage assertions would then measure — nor a second real stage slip in
    unnoticed, which is what would put the floor back on a partial population.
    """
    commands = pytest_commands()
    assert all(cmd.strip().startswith("uv run") for cmd in commands), (
        f"a non-command line was parsed as a gate stage: {commands!r}"
    )
    assert len(commands) == 1, (
        f"scripts/verify.sh runs one pytest stage since #435 retired the docker "
        f"partition; parsed {len(commands)}: {commands!r}. If a second stage is "
        f"reintroduced, the union assertions #435 removed come back with it."
    )


def test_gate_measures_the_scripts_tree() -> None:
    """The pytest stage scopes coverage to ``scripts/``.

    Without it the floor would be measured over whatever pytest happened to
    import, which is not a population anyone chose.
    """
    for command in pytest_commands():
        assert COVERAGE_TARGET in command, (
            f"every pytest stage in scripts/verify.sh must pass "
            f"{COVERAGE_TARGET} — the only executable tree the repo still owns "
            f"(CAL-1015, #435):\n  {command.strip()}"
        )


def test_gate_typechecks_the_one_surviving_python_tree() -> None:
    """The mypy stage names ``scripts``, the only Python tree left.

    The twin of :func:`test_gate_measures_the_scripts_tree`. #435 pointed this
    stage at ``scripts templates``; v5 chunk 3 moved the last Python out of
    ``templates/`` (``generate_codex_artifacts.py`` → ``scripts/``, per the
    plugin-shaped-guidance proposal), so the stage names exactly ``scripts`` —
    a lingering ``templates`` target would make mypy fail on a directory with
    no Python files, and a dropped stage would leave the tree untyped. The
    spine's ``commands.typecheck`` promises the same target.
    """
    stages = [
        line.strip()
        for line in VERIFY.read_text().splitlines()
        if line.strip().startswith("uv run") and " mypy " in f" {line} "
    ]
    assert len(stages) == 1, f"expected exactly one mypy stage; found {stages}"
    tokens = shlex.split(stages[0])
    assert tokens[tokens.index("mypy") + 1 :] == ["scripts"], (
        f"scripts/verify.sh's mypy stage must typecheck exactly `scripts` — the "
        f"only Python tree the repo still owns (v5 chunk 3):\n  {stages[0]}"
    )


def test_gate_enforces_the_coverage_floor() -> None:
    """Exactly one stage carries the floor, with the expected value."""
    commands = pytest_commands()
    carrying = [cmd for cmd in commands if "--cov-fail-under" in cmd]
    assert len(carrying) == 1, (
        f"exactly one pytest stage must carry --cov-fail-under; found "
        f"{len(carrying)}. None drops the floor entirely; more than one would "
        f"grade a partial population (CAL-1015)."
    )
    match = re.search(r"--cov-fail-under=(\d+)", carrying[0])
    assert match is not None, (
        "scripts/verify.sh's pytest step must pass --cov-fail-under=<N> so the "
        "gate fails when coverage drops below the floor (CAL-1015)."
    )
    assert int(match.group(1)) == COVERAGE_FLOOR, (
        f"the coverage floor must be {COVERAGE_FLOOR}; found "
        f"--cov-fail-under={match.group(1)}. The floor is a ratchet — raise both "
        f"homes together when coverage rises (CAL-1015)."
    )
