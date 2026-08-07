"""#360 — the mutation harness's decision logic, driven through the runner seam.

Every tick that ships a new guard proves it by mutating the guarded code and
watching the guard die. The *table* is bespoke per tick; everything around it —
backup, landing, containment, the green-baseline precondition, and the
kill/survive determination — was rewritten from scratch each time, and that
shared part is where the bugs were:

* **#207** — an aggregate ``N passed`` assertion reported a kill that never
  happened, because one assert could fail two ways and its message lied in one.
* **#336** — four of twenty mutations were **no-ops that evaluated to the
  original value**. Each printed SURVIVED and each cost a re-derivation.

The dangerous direction is the other one: a mutation that breaks *collection*
reddens hundreds of unrelated tests and is recorded as a kill it never earned.

:mod:`mutate` answers both with one predicate — ``observed == kills``, set
equality on pytest node ids. A no-op's observed set is empty; a
collection-breaker's is a strict superset; neither equals the prediction. These
tests drive that predicate, and every refusal around it, through the injected
``Runner`` seam, so the whole decision layer is provable without spawning a
suite. The end-to-end proof over a real pytest run is
:mod:`tests.unit.test_mutate_end_to_end`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import mutate  # noqa: E402

_SENTINEL = "harness-360-mini-tree"


# ---------------------------------------------------------------------------
# Fixtures: a mini tree and a stub runner.
# ---------------------------------------------------------------------------


def _mini_tree(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    """A tree carrying the sentinel plus whatever targets a test names."""
    tree = tmp_path / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    (tree / "MARKER.md").write_text(
        f"this tree is the one you meant: {_SENTINEL}\n", encoding="utf-8"
    )
    for relpath, text in (files or {}).items():
        target = tree / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return tree


def _table_text(
    *,
    mutations: str,
    select: str = '["-m", "unit"]',
    sentinel_file: str = "MARKER.md",
    sentinel_text: str = _SENTINEL,
) -> str:
    return (
        f"select = {select}\n"
        f'sentinel_file = "{sentinel_file}"\n'
        f'sentinel_text = "{sentinel_text}"\n'
        f"{mutations}"
    )


def _entry(
    *,
    ident: str = "e1",
    file: str = "pkg/calc.py",
    old: str = "a + b",
    new: str = "a - b",
    kills: str = '["tests/test_calc.py::test_add"]',
    note: str = "addition must be addition",
) -> str:
    return (
        "\n[[mutation]]\n"
        f'id = "{ident}"\n'
        f'file = "{file}"\n'
        f"old = '''{old}'''\n"
        f"new = '''{new}'''\n"
        f"kills = {kills}\n"
        f'note = "{note}"\n'
    )


def _write_table(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "table.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _outcome(
    *,
    passed: set[str] | None = None,
    failed: set[str] | None = None,
    errored: set[str] | None = None,
    collected: int = 3,
    ok: bool = True,
    detail: str = "",
) -> mutate.RunOutcome:
    return mutate.RunOutcome(
        ok=ok,
        passed=frozenset(passed or set()),
        failed=frozenset(failed or set()),
        errored=frozenset(errored or set()),
        collected=collected,
        duration_s=0.5,
        detail=detail,
    )


_GREEN = _outcome(
    passed={
        "tests/test_calc.py::test_add",
        "tests/test_calc.py::test_sub",
        "tests/test_calc.py::test_mul",
    }
)


class _StubRunner:
    """Returns queued outcomes in order and records the tree it saw.

    ``seen`` captures the target's bytes **at the moment the runner is called**,
    which is how the tests assert that a mutation actually landed before the
    suite ran — the property no report line can prove on its own.
    """

    def __init__(self, *outcomes: mutate.RunOutcome, target: str = "pkg/calc.py") -> None:
        self._queue = list(outcomes)
        self._target = target
        self.seen: list[bytes] = []
        self.calls = 0

    def __call__(self, tree: Path, select: list[str]) -> mutate.RunOutcome:
        self.calls += 1
        probe = tree / self._target
        self.seen.append(probe.read_bytes() if probe.exists() else b"")
        if not self._queue:
            raise AssertionError("the runner was called more times than queued")
        return self._queue.pop(0)


def _plan(
    tmp_path: Path,
    *,
    mutations: str,
    runner: object,
    target_text: str = "def add(a, b):\n    return a + b\n",
    **kwargs: object,
) -> mutate.Report:
    tree = _mini_tree(tmp_path, {"pkg/calc.py": target_text})
    table = mutate.load_table(_write_table(tmp_path, _table_text(mutations=mutations)))
    return mutate.run_plan(table, tree, runner=runner, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-1 — one rule, both directions.
# ---------------------------------------------------------------------------


def test_a_no_op_mutation_is_a_failure_of_the_entry(tmp_path: Path) -> None:
    """A mutation that kills nothing fails the entry — it is never a pass.

    The #336 shape: the edit looked like a degradation and evaluated to the
    original value, so the suite stayed green.
    """
    runner = _StubRunner(_GREEN, _outcome(passed=set(_GREEN.passed)))

    report = _plan(tmp_path, mutations=_entry(), runner=runner)

    (result,) = report.results
    assert result.outcome == "survived"
    assert result.missing == frozenset({"tests/test_calc.py::test_add"})
    assert result.unexpected == frozenset()
    assert mutate.exit_code(report) == 1


def test_a_collection_breaker_is_a_failure_of_the_entry_not_a_kill(tmp_path: Path) -> None:
    """Over-kill fails the *same* comparison under-kill fails.

    This is the direction a containment rule ("the predicted test is among the
    failures") cannot see: the predicted test *is* in there, alongside every
    other test in the module. #336 recorded one such entry as a kill and only a
    manual re-run established it was genuine.
    """
    runner = _StubRunner(
        _GREEN,
        _outcome(
            errored={
                "tests/test_calc.py::test_add",
                "tests/test_calc.py::test_sub",
                "tests/test_calc.py::test_mul",
            },
            collected=0,
        ),
    )

    report = _plan(tmp_path, mutations=_entry(), runner=runner)

    (result,) = report.results
    assert result.outcome == "mispredicted"
    assert result.missing == frozenset()
    assert result.unexpected == frozenset(
        {"tests/test_calc.py::test_sub", "tests/test_calc.py::test_mul"}
    )
    assert mutate.exit_code(report) == 1


def test_an_exactly_predicted_kill_is_the_only_pass(tmp_path: Path) -> None:
    runner = _StubRunner(
        _GREEN,
        _outcome(
            passed={"tests/test_calc.py::test_sub", "tests/test_calc.py::test_mul"},
            failed={"tests/test_calc.py::test_add"},
        ),
    )

    report = _plan(tmp_path, mutations=_entry(), runner=runner)

    (result,) = report.results
    assert result.outcome == "killed"
    assert mutate.exit_code(report) == 0


def test_a_partial_kill_is_mispredicted(tmp_path: Path) -> None:
    """Predicting two and killing one is a defect of the entry, not a pass."""
    runner = _StubRunner(
        _GREEN,
        _outcome(failed={"tests/test_calc.py::test_add"}),
    )

    report = _plan(
        tmp_path,
        mutations=_entry(
            kills='["tests/test_calc.py::test_add", "tests/test_calc.py::test_sub"]'
        ),
        runner=runner,
    )

    (result,) = report.results
    assert result.outcome == "mispredicted"
    assert result.missing == frozenset({"tests/test_calc.py::test_sub"})
    assert mutate.exit_code(report) == 1


def test_a_disjoint_kill_is_mispredicted(tmp_path: Path) -> None:
    """Killing a different test than predicted is not a kill."""
    runner = _StubRunner(_GREEN, _outcome(failed={"tests/test_calc.py::test_sub"}))

    report = _plan(tmp_path, mutations=_entry(), runner=runner)

    (result,) = report.results
    assert result.outcome == "mispredicted"
    assert result.missing == frozenset({"tests/test_calc.py::test_add"})
    assert result.unexpected == frozenset({"tests/test_calc.py::test_sub"})


def test_a_runner_that_did_not_complete_is_errored_not_a_kill(tmp_path: Path) -> None:
    """A timeout kills every test in the selection; that is not evidence."""
    runner = _StubRunner(_GREEN, _outcome(ok=False, collected=0, detail="timeout"))

    report = _plan(tmp_path, mutations=_entry(), runner=runner)

    (result,) = report.results
    assert result.outcome == "errored"
    assert "timeout" in result.detail
    assert mutate.exit_code(report) == 1


def test_the_mutation_is_applied_before_the_suite_runs(tmp_path: Path) -> None:
    """Bind the verdict to the tree the runner saw, not to the report line.

    Without this, every outcome above would hold for a harness that reported
    verdicts while never writing anything.
    """
    runner = _StubRunner(_GREEN, _outcome(failed={"tests/test_calc.py::test_add"}))

    _plan(tmp_path, mutations=_entry(), runner=runner)

    baseline_text, mutated_text = (blob.decode("utf-8") for blob in runner.seen)
    assert "return a + b" in baseline_text
    assert "return a - b" in mutated_text


# ---------------------------------------------------------------------------
# AC-2 — landing and containment, checked before any write.
# ---------------------------------------------------------------------------


def test_old_absent_refuses_naming_zero_occurrences(tmp_path: Path) -> None:
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(tmp_path, mutations=_entry(old="a * b"), runner=runner)

    assert excinfo.value.reason == "landing"
    assert "0 occurrences" in str(excinfo.value)
    assert "e1" in str(excinfo.value)
    assert runner.calls == 0


def test_old_occurring_twice_refuses_with_its_own_message(tmp_path: Path) -> None:
    """Zero and two are distinct refusals — one assert that can fail two ways is #207."""
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(
            tmp_path,
            mutations=_entry(old="a + b"),
            runner=runner,
            target_text="def add(a, b):\n    return a + b\n\n\ndef also(a, b):\n    return a + b\n",
        )

    assert excinfo.value.reason == "landing"
    assert "2 occurrences" in str(excinfo.value)
    assert runner.calls == 0


def test_a_wrong_tree_is_refused_by_the_sentinel(tmp_path: Path) -> None:
    """The realistic accident: running a tick's table against the main checkout."""
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    (tree / "MARKER.md").write_text("some other checkout\n", encoding="utf-8")
    table = mutate.load_table(_write_table(tmp_path, _table_text(mutations=_entry())))
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.run_plan(table, tree, runner=runner)

    assert excinfo.value.reason == "containment"
    assert runner.calls == 0
    assert "return a + b" in (tree / "pkg" / "calc.py").read_text(encoding="utf-8")


def test_a_target_outside_the_tree_is_refused(tmp_path: Path) -> None:
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(tmp_path, mutations=_entry(file="../escape.py"), runner=runner)

    assert excinfo.value.reason == "containment"
    assert runner.calls == 0


def test_a_symlink_out_of_the_tree_is_refused_as_escaping(tmp_path: Path) -> None:
    """A symlink inside the tree can still point at the main checkout."""
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    outside = tmp_path / "outside.py"
    outside.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tree / "link.py").symlink_to(outside)
    table = mutate.load_table(
        _write_table(tmp_path, _table_text(mutations=_entry(file="link.py")))
    )
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.run_plan(table, tree, runner=runner)

    assert excinfo.value.reason == "containment"
    assert "outside the tree" in str(excinfo.value)
    assert runner.calls == 0
    assert outside.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_a_symlink_within_the_tree_is_refused_as_a_symlink(tmp_path: Path) -> None:
    """Refused on its own branch, and asserted by its own message.

    Distinct from the escaping case above, which the containment check already
    catches: here the bytes would land in a real in-tree file while the report
    named the link. Without the separate message assertion, one refusal could
    stand in for both and neither branch would be measured.
    """
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    (tree / "alias.py").symlink_to(tree / "pkg" / "calc.py")
    table = mutate.load_table(
        _write_table(tmp_path, _table_text(mutations=_entry(file="alias.py")))
    )
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.run_plan(table, tree, runner=runner)

    assert excinfo.value.reason == "containment"
    assert "symlink" in str(excinfo.value)
    assert runner.calls == 0


def test_a_relative_tree_path_is_not_mistaken_for_a_symlink(tmp_path: Path) -> None:
    """The obvious way to write the symlink check refuses every relative ``--tree``.

    Comparing the resolved target against the *unresolved* join makes them
    differ whenever the tree argument is relative or sits under a symlinked
    prefix — which on macOS is every ``tmp_path``. This is the shape that
    refused the harness's own first self-run.
    """
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    table = mutate.load_table(_write_table(tmp_path, _table_text(mutations=_entry())))
    runner = _StubRunner(_GREEN, _outcome(failed={"tests/test_calc.py::test_add"}))

    relative = Path(os.path.relpath(tree, Path.cwd()))
    report = mutate.run_plan(table, relative, runner=runner)

    assert [result.outcome for result in report.results] == ["killed"]


def test_landing_is_checked_for_the_whole_table_before_the_first_write(
    tmp_path: Path,
) -> None:
    """Entry 1 must not be written when entry 2 cannot land (AC-2 + AC-3)."""
    tree = _mini_tree(
        tmp_path,
        {"pkg/calc.py": "def add(a, b):\n    return a + b\n", "pkg/other.py": "LIMIT = 4\n"},
    )
    before = {
        path: path.read_bytes() for path in sorted(tree.rglob("*.py"))
    }
    table = mutate.load_table(
        _write_table(
            tmp_path,
            _table_text(
                mutations=_entry()
                + _entry(ident="e2", file="pkg/other.py", old="LIMIT = 99", new="LIMIT = 1")
            ),
        )
    )
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.run_plan(table, tree, runner=runner)

    assert excinfo.value.reason == "landing"
    assert "e2" in str(excinfo.value)
    assert runner.calls == 0
    assert {path: path.read_bytes() for path in sorted(tree.rglob("*.py"))} == before


# ---------------------------------------------------------------------------
# AC-3 — backups, and a mid-run failure that leaves the tree pristine.
# ---------------------------------------------------------------------------


class _RaisingRunner:
    """Green baseline, one honest entry, then an explosion on the second."""

    def __init__(self, boom: BaseException) -> None:
        self._boom = boom
        self.calls = 0

    def __call__(self, tree: Path, select: list[str]) -> mutate.RunOutcome:
        self.calls += 1
        if self.calls == 1:
            return _GREEN
        if self.calls == 2:
            return _outcome(failed={"tests/test_calc.py::test_add"})
        raise self._boom


@pytest.mark.parametrize(
    "boom",
    [RuntimeError("the runner crashed"), SystemExit(143)],
    ids=["exception", "sigterm"],
)
def test_a_failure_mid_run_leaves_every_target_byte_identical(
    tmp_path: Path, boom: BaseException
) -> None:
    """The load-bearing safety property: no target survives a crash mutated.

    Two shapes, because they unwind differently: an ordinary exception and the
    ``SystemExit`` a ``SIGTERM`` handler raises. Byte comparison rather than
    text: a CRLF target restored through ``read_text``/``write_text`` would come
    back with translated newlines and a text comparison would call that
    identical.
    """
    tree = _mini_tree(
        tmp_path,
        {
            "pkg/calc.py": "def add(a, b):\r\n    return a + b\r\n",
            "pkg/other.py": "LIMIT = 4",  # no trailing newline
            "pkg/third.py": "FLAG = True\n",
        },
    )
    before = {path: path.read_bytes() for path in sorted(tree.rglob("*.py"))}
    table = mutate.load_table(
        _write_table(
            tmp_path,
            _table_text(
                mutations=_entry()
                + _entry(ident="e2", file="pkg/other.py", old="LIMIT = 4", new="LIMIT = 1")
                + _entry(ident="e3", file="pkg/third.py", old="FLAG = True", new="FLAG = False")
            ),
        )
    )
    runner = _RaisingRunner(boom)

    with pytest.raises(type(boom)):
        mutate.run_plan(table, tree, runner=runner)

    assert runner.calls == 3, "the crash must land inside the mutation loop"
    assert {path: path.read_bytes() for path in sorted(tree.rglob("*.py"))} == before


def test_every_entry_runs_against_the_pristine_file(tmp_path: Path) -> None:
    """Two entries on one file: entry 2 sees the original, not entry 1's residue."""
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "X = 1\nY = 2\n"})
    before = (tree / "pkg" / "calc.py").read_bytes()
    table = mutate.load_table(
        _write_table(
            tmp_path,
            _table_text(
                mutations=_entry(old="X = 1", new="X = 9")
                + _entry(ident="e2", old="Y = 2", new="Y = 9")
            ),
        )
    )
    runner = _StubRunner(
        _GREEN,
        _outcome(failed={"tests/test_calc.py::test_add"}),
        _outcome(failed={"tests/test_calc.py::test_add"}),
    )

    mutate.run_plan(table, tree, runner=runner)

    _, first, second = (blob.decode("utf-8") for blob in runner.seen)
    assert first == "X = 9\nY = 2\n"
    assert second == "X = 1\nY = 9\n"
    assert (tree / "pkg" / "calc.py").read_bytes() == before


def test_backups_are_written_to_the_work_dir(tmp_path: Path) -> None:
    """A hard kill is recoverable by hand from the printed work dir."""
    work_dir = tmp_path / "work"
    runner = _StubRunner(_GREEN, _outcome(failed={"tests/test_calc.py::test_add"}))

    report = _plan(tmp_path, mutations=_entry(), runner=runner, work_dir=work_dir)

    backup = work_dir / "backup" / "pkg" / "calc.py"
    assert report.work_dir == work_dir
    assert backup.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_the_module_spawns_only_python_never_git() -> None:
    """Restoration reads from backups; nothing in this module shells out to git.

    Structural rather than remembered: every ``subprocess`` call the module can
    build is asserted to start its argv with ``sys.executable``. ``git checkout``
    is the revert that cost #163 forty minutes of finished work, and the rule
    against it only holds if nothing here can reach git at all.
    """
    import ast

    source = (_REPO_ROOT / "scripts" / "mutate.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
    ]
    assert calls, "expected at least one subprocess call to constrain"
    for call in calls:
        argv = call.args[0]
        assert isinstance(argv, ast.List), ast.dump(argv)
        head = argv.elts[0]
        assert isinstance(head, ast.Attribute) and head.attr == "executable", (
            "the only binary scripts/mutate.py may spawn is this interpreter — "
            f"found {ast.dump(head)}"
        )


# ---------------------------------------------------------------------------
# AC-4 — the baseline precondition.
# ---------------------------------------------------------------------------


def test_a_red_baseline_refuses_naming_the_failing_tests(tmp_path: Path) -> None:
    runner = _StubRunner(
        _outcome(
            passed={"tests/test_calc.py::test_add"},
            failed={"tests/test_calc.py::test_sub"},
            errored={"tests/test_calc.py::test_mul"},
        )
    )

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(tmp_path, mutations=_entry(), runner=runner)

    assert excinfo.value.reason == "baseline"
    message = str(excinfo.value)
    assert "tests/test_calc.py::test_sub" in message
    assert "tests/test_calc.py::test_mul" in message


def test_a_red_baseline_refuses_before_any_write(tmp_path: Path) -> None:
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    before = (tree / "pkg" / "calc.py").read_bytes()
    table = mutate.load_table(_write_table(tmp_path, _table_text(mutations=_entry())))
    runner = _StubRunner(_outcome(failed={"tests/test_calc.py::test_sub"}))

    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.run_plan(table, tree, runner=runner)

    # Pin *which* rule refused. Without this the test passes on a harness that
    # dropped the baseline check entirely: the prediction check downstream would
    # then refuse this same table (its node id is absent from an empty passed
    # set), leaving the tree untouched for the wrong reason.
    assert excinfo.value.reason == "baseline"
    assert (tree / "pkg" / "calc.py").read_bytes() == before


def test_a_selection_collecting_nothing_refuses(tmp_path: Path) -> None:
    """Otherwise every entry survives identically and the table looks wrong."""
    runner = _StubRunner(_outcome(collected=0))

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(tmp_path, mutations=_entry(), runner=runner)

    assert excinfo.value.reason == "baseline"
    assert "collected 0" in str(excinfo.value)


def test_a_prediction_absent_from_the_baseline_refuses(tmp_path: Path) -> None:
    """A mistyped node id is a table defect, not a survivor."""
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(
            tmp_path,
            mutations=_entry(kills='["tests/test_calc.py::test_typo"]'),
            runner=runner,
        )

    assert excinfo.value.reason == "prediction"
    assert "tests/test_calc.py::test_typo" in str(excinfo.value)


def test_a_baseline_the_runner_could_not_complete_is_not_a_refusal(tmp_path: Path) -> None:
    """An unrunnable pytest is infrastructure (exit 3), not a red baseline (exit 2)."""
    runner = _StubRunner(_outcome(ok=False, collected=0, detail="pytest not found"))

    with pytest.raises(mutate.RunnerUnavailableError):
        _plan(tmp_path, mutations=_entry(), runner=runner)


# ---------------------------------------------------------------------------
# Table validation — the invariants that need no suite run.
# ---------------------------------------------------------------------------


def test_a_textually_identical_mutation_is_refused(tmp_path: Path) -> None:
    """The one no-op catchable without running anything."""
    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.load_table(
            _write_table(tmp_path, _table_text(mutations=_entry(old="a + b", new="a + b")))
        )

    assert excinfo.value.reason == "table"
    assert "e1" in str(excinfo.value)


def test_a_duplicate_entry_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.load_table(
            _write_table(tmp_path, _table_text(mutations=_entry() + _entry(old="a - b")))
        )

    assert excinfo.value.reason == "table"
    assert "e1" in str(excinfo.value)


def test_an_entry_predicting_no_kills_is_refused(tmp_path: Path) -> None:
    """An entry with nothing to prove cannot fail, so it must not be writable."""
    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.load_table(_write_table(tmp_path, _table_text(mutations=_entry(kills="[]"))))

    assert excinfo.value.reason == "table"
    assert "e1" in str(excinfo.value)


def test_a_table_with_no_mutations_is_refused(tmp_path: Path) -> None:
    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.load_table(_write_table(tmp_path, _table_text(mutations="")))

    assert excinfo.value.reason == "table"


def test_a_table_missing_the_sentinel_is_refused(tmp_path: Path) -> None:
    """Containment is not optional — a table cannot decline to declare a tree."""
    text = f'select = ["-m", "unit"]\nsentinel_file = "MARKER.md"\n{_entry()}'
    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.load_table(_write_table(tmp_path, text))

    assert excinfo.value.reason == "table"
    assert "sentinel_text" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Reporting and selection.
# ---------------------------------------------------------------------------


def test_the_report_names_every_entry_its_outcome_and_its_note(tmp_path: Path) -> None:
    runner = _StubRunner(
        _GREEN,
        _outcome(passed=set(_GREEN.passed)),
        _outcome(failed={"tests/test_calc.py::test_sub"}),
    )
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "X = 1\nY = 2\n"})
    table = mutate.load_table(
        _write_table(
            tmp_path,
            _table_text(
                mutations=_entry(old="X = 1", new="X = 9", note="X must be one")
                + _entry(ident="e2", old="Y = 2", new="Y = 9", note="Y must be two")
            ),
        )
    )

    report = mutate.run_plan(table, tree, runner=runner)
    rendered = mutate.render(report)

    assert "SURVIVED" in rendered
    assert "MISPREDICTED" in rendered
    assert "X must be one" in rendered
    assert "Y must be two" in rendered
    assert "tests/test_calc.py::test_sub" in rendered
    # Collected counts sit beside the baseline's, so #336's 0.25s-against-0.70s
    # tell is on the line rather than in the operator's head.
    assert "collected" in rendered
    # The summary counts entries that did not kill. Asserted here because the
    # ``honest`` branch is asserted elsewhere, and a render that printed
    # "honest" unconditionally would otherwise satisfy both.
    assert "RESULT: 2 entries did not kill as predicted" in rendered


def test_the_report_of_an_all_killed_table_says_honest(tmp_path: Path) -> None:
    runner = _StubRunner(_GREEN, _outcome(failed={"tests/test_calc.py::test_add"}))

    report = _plan(tmp_path, mutations=_entry(), runner=runner)

    assert "RESULT: honest" in mutate.render(report)
    assert mutate.exit_code(report) == 0


def test_the_selection_reaches_the_runner(tmp_path: Path) -> None:
    """The table's ``select`` is what the suite runs — the #336 fast-tier affordance."""
    seen: list[list[str]] = []

    def runner(tree: Path, select: list[str]) -> mutate.RunOutcome:
        seen.append(list(select))
        return _GREEN if len(seen) == 1 else _outcome(failed={"tests/test_calc.py::test_add"})

    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    table = mutate.load_table(
        _write_table(
            tmp_path,
            _table_text(mutations=_entry(), select='["-m", "unit or guard"]'),
        )
    )

    mutate.run_plan(table, tree, runner=runner)

    assert seen == [["-m", "unit or guard"], ["-m", "unit or guard"]]


def test_only_restricts_the_entries_run_but_not_the_baseline(tmp_path: Path) -> None:
    runner = _StubRunner(_GREEN, _outcome(failed={"tests/test_calc.py::test_add"}))
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "X = 1\nY = 2\n"})
    table = mutate.load_table(
        _write_table(
            tmp_path,
            _table_text(
                mutations=_entry(old="X = 1", new="X = 9")
                + _entry(ident="e2", old="Y = 2", new="Y = 9")
            ),
        )
    )

    report = mutate.run_plan(table, tree, runner=runner, only=("e2",))

    assert [result.mutation.id for result in report.results] == ["e2"]
    assert runner.calls == 2


def test_main_maps_a_refusal_to_exit_2_and_names_the_reason(tmp_path: Path) -> None:
    """Every refusal above reaches a caller as exit 2, whatever raised it.

    The unit tests assert *which* rule refused; this asserts the mapping from
    that to the process's answer. Without it, ``main`` could swallow a
    ``RefusalError`` into a clean exit and every one of them would still pass.
    """
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    table = _write_table(tmp_path, _table_text(mutations=_entry() + _entry(old="a - b")))

    code = mutate.main(["check", "--table", str(table), "--tree", str(tree)])

    assert code == 2


def test_main_exits_0_on_a_table_that_lands(tmp_path: Path) -> None:
    """The control for the test above: ``check`` is not a refusal machine."""
    tree = _mini_tree(tmp_path, {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    table = _write_table(tmp_path, _table_text(mutations=_entry()))

    assert mutate.main(["check", "--table", str(table), "--tree", str(tree)]) == 0


def test_only_naming_an_unknown_entry_is_refused(tmp_path: Path) -> None:
    runner = _StubRunner(_GREEN)

    with pytest.raises(mutate.RefusalError) as excinfo:
        _plan(tmp_path, mutations=_entry(), runner=runner, only=("nope",))

    assert excinfo.value.reason == "table"
    assert "nope" in str(excinfo.value)
