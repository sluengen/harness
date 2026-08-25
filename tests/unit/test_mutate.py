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

# size: one surface's acceptance matrix — the kill/survive determination and every
# refusal that guards it. The refusals are the obvious split and are exactly what
# must not move: each is asserted against the same green-baseline and pristine-tree
# fixtures the determination uses, and the module's value is that the whole refusal
# matrix is readable beside the rule it protects. The split that does pay is
# already taken — the end-to-end half is its own module, divided on the tier
# boundary (`tests/_tiers.py`) rather than on subject matter.

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

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


@pytest.mark.parametrize(
    "boom",
    [RuntimeError("the runner crashed"), SystemExit(143)],
    ids=["exception", "sigterm"],
)
def test_the_work_dir_is_announced_before_the_first_write(
    tmp_path: Path, boom: BaseException
) -> None:
    """The backups are only recoverable by hand if their path was printed.

    A crash — or the ``SIGKILL`` no handler can catch — never reaches the
    report, so announcing the work dir from the report would print it in exactly
    the cases that do not need it and withhold it in the one that does. Asserted
    on a run that never returns a ``Report``, which is the only shape that can
    tell the two placements apart.
    """
    tree = _mini_tree(
        tmp_path,
        {
            "pkg/calc.py": "def add(a, b):\n    return a + b\n",
            "pkg/other.py": "LIMIT = 4",
            "pkg/third.py": "FLAG = True\n",
        },
    )
    work_dir = tmp_path / "work"
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
    captured = io.StringIO()

    with pytest.raises(type(boom)):
        mutate.run_plan(
            table, tree, runner=_RaisingRunner(boom), work_dir=work_dir, out=captured
        )

    assert str(work_dir) in captured.getvalue()
    assert (work_dir / "backup" / "pkg" / "calc.py").exists()


#: The one non-interpreter argv this module may build, as its three literal
#: elements: ``["node", <a name bound to the gate-marker helper>, "status"]``.
#: Stated as constants so each one can be sampled by a synthetic case below —
#: a predicate fed only production source is indistinguishable from a hardcoded
#: pass (#458), so every constant here has a case whose answer differs from this
#: tree's.
HELPER_RUNTIME = "node"
HELPER_QUERY = "status"

#: What a name must be bound to before it can fill the middle slot. The exemption
#: is **earned from the subject**, not granted to a name: the guard resolves the
#: module's own top-level assignments and admits only a name whose value is built
#: from this literal. Rename the constant and the guard follows it; re-point it at
#: another file and the exemption evaporates. There is no list to go stale in
#: either direction (#449 → #458, five findings).
HELPER_FILENAME = "gate-marker.js"


def _helper_names(tree: ast.Module) -> set[str]:
    """Top-level names bound to something built from ``HELPER_FILENAME``.

    Read off the assignment rather than matched by name, so
    ``GATE_MARKER_JS = str(PLUGIN_DIR / "gate-marker.js")`` resolves and a name
    that merely *looks* like a helper path does not. Top-level only: a local
    rebinding inside a function is not the module's declared constant.
    """
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        literals = {
            child.value
            for child in ast.walk(node.value)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        }
        if HELPER_FILENAME not in literals:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


#: The module whose calls this guard extracts. The canonical name is a member of
#: the module set below rather than the whole of it: ``subprocess.run(...)`` needs
#: no import to parse, and every synthetic case here is a fragment.
SPAWN_MODULE = "subprocess"


def _spawn_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The names ``tree``'s own imports bind to :data:`SPAWN_MODULE`.

    Returns ``(module names, called names)``: names standing for the module, so
    ``import subprocess as sp`` makes ``sp.run(...)`` a spawn, and names bound
    directly, so ``from subprocess import Popen as spawn`` makes ``spawn(...)``
    one. Earned from the import in the same shape :func:`_helper_names` earns the
    helper from its assignment — a name is a spawn because of what it was bound
    to, never because of what it is called, so ``from pkg.jobs import run`` is not
    one and there is no list of function names to go stale (#490).

    Every name a ``from subprocess import`` binds counts when called, including
    one that spawns nothing (``TimeoutExpired``). That over-reports in the loud
    direction — a false offender is a red test naming its line — and it needs no
    enumeration of which members of the module spawn.

    A star import binds whatever ``subprocess.__all__`` names, so that is what it
    contributes here — asked of the module rather than transcribed, which is the
    same earned-from-the-subject shape and leaves nothing to go stale. The
    spelling is refused in ``scripts/`` by ruff (F403/F405, measured) before this
    guard ever runs; it is read anyway, because a predicate that goes silent on a
    legal spelling of its subject is a hole rather than strictness (#484/#487).

    Imports anywhere, not top level only: an import inside a function binds a
    working spawn just as well, and unlike the helper constant there is nothing
    here that a local rebinding could weaken.
    """
    modules = {SPAWN_MODULE}
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == SPAWN_MODULE:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == SPAWN_MODULE:
            for alias in node.names:
                if alias.name == "*":
                    called |= set(subprocess.__all__)
                else:
                    called.add(alias.asname or alias.name)
    return modules, called


def subprocess_calls(tree: ast.Module) -> list[ast.Call]:
    """Every call in ``tree`` that spawns through :data:`SPAWN_MODULE`.

    Every spelling an import can bind: ``subprocess.run(...)``, an aliased
    ``sp.run(...)``, and a bare ``run(...)`` or ``Popen(...)`` off a
    ``from``-import, aliased, plain, or by ``*``. A predicate that reads one
    spelling of a shape its subject may legally write is a hole, not strictness
    (#484/#487).

    Split out from the offender predicate so the non-vacuity floor can assert the
    scan *found* something: a guard whose extractor silently returned ``[]`` would
    satisfy "nothing spawns anything" having read nothing at all (#467).
    """
    modules, called = _spawn_names(tree)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name) and func.value.id in modules:
                calls.append(node)
        elif isinstance(func, ast.Name) and func.id in called:
            calls.append(node)
    return calls


def _is_interpreter_argv(argv: ast.expr | None) -> bool:
    """``[sys.executable, …]`` — this module running its own interpreter."""
    if not isinstance(argv, ast.List) or not argv.elts:
        return False
    head = argv.elts[0]
    return isinstance(head, ast.Attribute) and head.attr == "executable"


def _is_helper_query_argv(argv: ast.expr | None, helpers: set[str]) -> bool:
    """Exactly ``["node", <helper name>, "status"]`` and nothing else.

    Three elements, not "starts with": a fourth element is a different command,
    and the length is what stops ``["node", HELPER, "status", "--write"]`` from
    inheriting the exemption.
    """
    if not isinstance(argv, ast.List) or len(argv.elts) != 3:
        return False
    runtime, helper, verb = argv.elts
    return (
        isinstance(runtime, ast.Constant)
        and runtime.value == HELPER_RUNTIME
        and isinstance(helper, ast.Name)
        and helper.id in helpers
        and isinstance(verb, ast.Constant)
        and verb.value == HELPER_QUERY
    )


def unpermitted_spawns(source: str, origin: str = "<source>") -> list[str]:
    """Every subprocess argv in ``source`` this module is not permitted to build.

    One function, called by the tree-wide assertion **and** by every synthetic
    case, so a change to how production is scanned is a change to what every
    control measures (craft.md → *A positive control must exercise the predicate,
    not re-implement it*).
    """
    tree = ast.parse(source, filename=origin)
    helpers = _helper_names(tree)
    offenders: list[str] = []
    for call in subprocess_calls(tree):
        argv = call.args[0] if call.args else None
        if _is_interpreter_argv(argv) or _is_helper_query_argv(argv, helpers):
            continue
        spelling = "no argv" if argv is None else ast.unparse(argv)
        offenders.append(f"{origin}:{call.lineno}: {spelling}")
    return offenders


def test_the_module_spawns_only_this_interpreter_and_one_read_only_query() -> None:
    """Restoration reads from backups; nothing here can reach git to revert.

    ``git checkout -- .`` is the revert that cost #163 forty minutes of finished
    work, and the rule against it only holds if no call that spawns through
    ``subprocess`` under any name its own ``import`` statements bind — which is
    what :func:`subprocess_calls` derives — can build an argv that reaches git
    destructively.

    What that does not cover, named rather than implied, because a scope stated
    as *everything* is the claim that goes false first. A shell reached without
    ``subprocess`` at all, of which ``os.system("git checkout -- .")`` is the
    short spelling: enumerating ``os``'s spawn surface would take an allowlist
    with both a stale and an admitting direction, this repo's most repeated defect
    class (#449 → #458), and ruff refuses that line in ``scripts/`` today (S605
    and S607, measured) though a ``# noqa`` suppresses it as this module already
    suppresses S603. And a spawner reached under a name no ``import`` statement
    bound — ``sp = subprocess`` rebound by assignment, or a module fetched through
    ``importlib`` — which is where following the name stops being a question a
    predicate over text can answer.

    #500 widened the permission by exactly one shape, and the widening is stated as a
    shape rather than as a name. The gate lock has to reach the gate-marker
    convention, which ADR 0018 moved into Node; the alternative was a fourth
    Python parser of ``HARNESS_GATE_MARKER_MAX_AGE_SECONDS``. Naming ``node``
    would not protect the property this guard exists for — ``node -e`` runs
    anything. Naming the exact three-element argv does, because ``status`` is
    read-only by construction and every drift toward power fails the shape. The
    only widening direction left is a deliberate edit to this predicate, which is
    the loud one.

    Reads the **working file** on purpose: that keeps this guard inside
    ``scripts/mutate.py``'s own mutation instrument, which edits working files.
    """
    source = (REPO_ROOT / "scripts" / "mutate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert subprocess_calls(tree), "expected at least one subprocess call to constrain"
    assert _helper_names(tree), (
        "scripts/mutate.py declares no top-level name built from "
        f"{HELPER_FILENAME!r}, so the middle slot of the permitted argv can never "
        "match and this guard has degraded to 'only the interpreter' without "
        "saying so"
    )
    assert unpermitted_spawns(source, "scripts/mutate.py") == []


#: Synthetic sources whose answers **differ from this tree's**: one per constant
#: in the permission half, one per import spelling in the extraction half. Fed
#: only production source, a shape matcher and a hardcoded pass are
#: indistinguishable (#458), and a corpus that spells a shape one way never shows
#: an extractor the spellings it misses (#484/#487).
_PREAMBLE = 'HELPER = str(PLUGIN_DIR / "gate-marker.js")\n'

_SPAWN_CASES: list[tuple[str, str, bool]] = [
    ("interpreter", 'subprocess.run([sys.executable, "-c", "x"])', True),
    ("helper-status", f'{_PREAMBLE}subprocess.run(["node", HELPER, "status"], cwd=t)', True),
    ("helper-write", f'{_PREAMBLE}subprocess.run(["node", HELPER, "write"])', False),
    ("helper-plus-flag", f'{_PREAMBLE}subprocess.run(["node", HELPER, "status", "-f"])', False),
    ("node-eval", 'subprocess.run(["node", "-e", "require(0)"])', False),
    ("other-runtime", f'{_PREAMBLE}subprocess.run(["deno", HELPER, "status"])', False),
    (
        "other-file",
        'HELPER = str(PLUGIN_DIR / "other.js")\nsubprocess.run(["node", HELPER, "status"])',
        False,
    ),
    (
        "locally-bound-helper",
        'def go():\n    HELPER = "gate-marker.js"\n    subprocess.run(["node", HELPER, "status"])',
        False,
    ),
    ("git-checkout", 'subprocess.run(["git", "checkout", "--", "."])', False),
    ("non-literal-argv", "subprocess.run(argv)", False),
    (
        "aliased-module",
        'import subprocess as sp\nsp.run(["git", "checkout", "--", "."])',
        False,
    ),
    (
        "from-import",
        'from subprocess import run\nrun(["git", "checkout", "--", "."])',
        False,
    ),
    (
        "from-import-aliased",
        'from subprocess import Popen as spawn\nspawn(["git", "checkout", "--", "."])',
        False,
    ),
    (
        "star-import",
        'from subprocess import *\nrun(["git", "checkout", "--", "."])',
        False,
    ),
    (
        "aliased-module-helper-status",
        f'import subprocess as sp\n{_PREAMBLE}sp.run(["node", HELPER, "status"])',
        True,
    ),
    (
        "same-name-from-another-module",
        'from pkg.jobs import run\nrun(["git", "checkout", "--", "."])',
        True,
    ),
]


@pytest.mark.parametrize(
    ("source", "permitted"),
    [(source, permitted) for _, source, permitted in _SPAWN_CASES],
    ids=[name for name, _, _ in _SPAWN_CASES],
)
def test_the_spawn_predicate_admits_only_the_two_shapes(source: str, permitted: bool) -> None:
    """The predicate's own acceptance matrix, over sources this tree does not hold.

    Two halves, because a source can read as permitted either by being judged so
    or by never being extracted at all.

    *Permission.* Each offender row samples one constant: ``helper-write`` and
    ``helper-plus-flag`` sample the ``status`` verb and the argv length,
    ``node-eval`` samples the requirement that the middle slot be a *name*,
    ``other-runtime`` samples ``node``, ``other-file`` and
    ``locally-bound-helper`` sample how the helper name is earned, and
    ``git-checkout`` samples the class the whole rule exists for.

    *Extraction.* ``aliased-module``, ``from-import``, ``from-import-aliased``
    and ``star-import`` carry that same ``git checkout -- .`` in the spellings a
    bare ``subprocess.<attr>`` match cannot see. ``aliased-module-helper-status``
    holds the exemption open through one of them, so the widening cannot buy its
    coverage by condemning the one permitted shape. And
    ``same-name-from-another-module`` differs from ``from-import`` in nothing but
    the module the name came from, which is what separates a name earned from an
    import from a name matched by spelling (#490).
    """
    offenders = unpermitted_spawns(source, "<synthetic>")

    assert (offenders == []) is permitted, offenders


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


@pytest.mark.parametrize(
    "select",
    ['["-n", "auto"]', '["-nauto"]', '["--numprocesses=4"]', '["--dist", "loadfile"]'],
    ids=["separate", "joined", "long-equals", "dist"],
)
def test_a_parallel_selection_is_refused(tmp_path: Path, select: str) -> None:
    """The plugin's sets are per-interpreter, so xdist would report every entry green.

    Four spellings, because refusing only the obvious one leaves the hole open:
    the flag a tick is most likely to copy is whichever spelling the gate uses.
    """
    with pytest.raises(mutate.RefusalError) as excinfo:
        mutate.load_table(
            _write_table(tmp_path, _table_text(mutations=_entry(), select=select))
        )

    assert excinfo.value.reason == "table"
    assert "xdist" in str(excinfo.value)


@pytest.mark.parametrize(
    "select",
    ['["-m", "unit or guard"]', '["tests/unit/test_mutate.py"]', '["-k", "not slow"]'],
    ids=["marker", "path", "keyword"],
)
def test_an_ordinary_selection_is_not_mistaken_for_a_parallel_one(
    tmp_path: Path, select: str
) -> None:
    """The negative control: the refusal must discriminate, not just fire.

    ``-k`` and a path both start with characters the naive check could catch,
    and a predicate that refused them would make the harness unusable for the
    selections the ticket exists to support.
    """
    table = mutate.load_table(
        _write_table(tmp_path, _table_text(mutations=_entry(), select=select))
    )

    assert table.select == tuple(json.loads(select))


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
