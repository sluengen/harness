"""#360 AC-5 — the real ``scripts/mutate.py`` over a real pytest run.

:mod:`tests.unit.test_mutate` drives the decision logic through the injected
runner seam, which proves the predicate but stubs the one thing the predicate
consumes: the set of node ids a suite actually reports. Everything downstream of
``pytest_runtest_logreport`` — the plugin, the child's environment, the
``PYTHONPATH`` that has to resolve ``-p _mutate_outcomes``, and pytest's own node
id spelling — is unexercised there.

So these tests build a **synthetic mini-project** in ``tmp_path`` and run
``mutate.py`` against it as a subprocess, with the two entries the acceptance
criteria name:

* a deliberate **no-op** (``return a + b`` → ``return b + a``), which must report
  as a failure of the entry, never as a survivor to shrug at;
* a deliberate **collection-breaker** (``def add(a, b):`` → ``def add(a, b:``),
  which must report as a failure of the entry, never as the kill it appears to
  be — this is the #336 direction that a containment rule cannot see.

Synthetic source rather than this repo's own tree, because the oracle has to be
provable against code whose expected outcome is known by construction. The tree
carries its own ``pytest.ini``, and the baseline's collected count is asserted
against it, since silently inheriting *this* repo's ``addopts`` / ``testpaths``
would make every assertion below meaningless.

Module-level ``subprocess`` puts this module in the ``integration`` tier
(``tests/_tiers.py``), which is the honest answer and is why it is a separate
module from the fast half.
"""

# size: declarative fixtures, not logic — roughly half this module is the source
# of the synthetic projects the assertions run against, and each is spelled out
# because the oracle is only trustworthy if the expected outcome is readable by
# construction. The extraction candidate is the #365 half (`_selection_project`
# and the liveness tests below), and it stays for a specific reason: it shares
# `_table`, `_entry`, `_run` and `_snapshot` with the #360 half, and splitting
# would either duplicate the TOML emitter — two spellings of the contract under
# test, which is the defect this repo keeps paying for — or make one test module
# import another's private helpers. When a third subject arrives, extract the
# emitters to a shared fixture module first, then split on that seam.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "mutate.py"
_PLUGIN = _REPO_ROOT / "scripts" / "_mutate_outcomes.py"
_VERIFY = _REPO_ROOT / "scripts" / "verify.sh"

_SENTINEL = "harness-360-synthetic-project"

_CALC = '''"""A three-function module with one test each."""


def add(a, b):
    return a + b


def sub(a, b):
    return a - b


def mul(a, b):
    return a * b
'''

_TESTS = '''import pytest

from calc import add, mul, sub


@pytest.mark.fast
def test_add():
    assert add(2, 3) == 5


def test_sub():
    assert sub(5, 3) == 2


def test_mul():
    assert mul(2, 3) == 6
'''

_INI = """[pytest]
markers =
    fast: the subset a selection can pick
"""


def _project(tmp_path: Path, *, tests: str = _TESTS) -> Path:
    """A self-contained pytest project whose outcomes are known by construction."""
    tree = tmp_path / "project"
    (tree / "tests").mkdir(parents=True)
    (tree / "calc.py").write_text(_CALC, encoding="utf-8")
    (tree / "tests" / "test_calc.py").write_text(tests, encoding="utf-8")
    (tree / "pytest.ini").write_text(_INI, encoding="utf-8")
    (tree / "MARKER.md").write_text(f"{_SENTINEL}\n", encoding="utf-8")
    (tree / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n",
        encoding="utf-8",
    )
    return tree


def _table(
    tmp_path: Path,
    *,
    entries: str,
    select: str = "[]",
    sentinel_text: str = _SENTINEL,
) -> Path:
    path = tmp_path / "table.toml"
    path.write_text(
        f"select = {select}\n"
        f'sentinel_file = "MARKER.md"\n'
        f'sentinel_text = "{sentinel_text}"\n'
        f"{entries}",
        encoding="utf-8",
    )
    return path


def _entry(
    *,
    ident: str,
    old: str,
    new: str,
    kills: str,
    note: str = "",
    file: str = "calc.py",
    observe: str | None = None,
) -> str:
    """The emitted TOML is byte-identical for a caller that passes neither of the
    two #365 keyword defaults, which is what keeps AC-5's "unmodified" true of
    every test above."""
    text = (
        "\n[[mutation]]\n"
        f'id = "{ident}"\n'
        f'file = "{file}"\n'
        f"old = '''{old}'''\n"
        f"new = '''{new}'''\n"
        f"kills = {kills}\n"
        f'note = "{note}"\n'
    )
    if observe is not None:
        text += f"observe = {observe}\n"
    return text


def _run(
    mode: str,
    table: Path,
    tree: Path,
    tmp_path: Path,
    *extra: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real script the way a tick runs it.

    ``env`` defaults to inheriting, which is what every caller but one wants.
    The exception is the bytecode-cache test: this module is itself often run
    *under* a mutation harness, whose own ``PYTHONPYCACHEPREFIX`` would
    propagate into the child and silently supply the very defence that test
    exists to exercise.
    """
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            mode,
            "--table",
            str(table),
            "--tree",
            str(tree),
            "--work-dir",
            str(tmp_path / "work"),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=env,
    )


def _snapshot(tree: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in sorted(tree.rglob("*")) if path.is_file()}


_ADD = "tests/test_calc.py::test_add"


# ---------------------------------------------------------------------------
# The three outcomes, end to end.
# ---------------------------------------------------------------------------


def test_an_honest_mutation_kills_exactly_its_prediction(tmp_path: Path) -> None:
    """The only path to exit 0 — and the control the other two are read against.

    Without this, "everything reports as a failure of the entry" would satisfy
    the no-op and collection-breaker assertions below just as well.
    """
    tree = _project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="honest",
            old="return a + b",
            new="return a - b",
            kills=f'["{_ADD}"]',
            note="addition must be addition",
        ),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "honest" in result.stdout
    assert "KILLED" in result.stdout
    assert "RESULT: honest" in result.stdout
    # Binds the announcement to the *default* stream. The unit test proves it
    # happens before the first write; without this, it could go anywhere.
    assert f"work dir: {tmp_path / 'work'}" in result.stdout


def test_a_no_op_mutation_reports_as_a_failure_of_the_entry(tmp_path: Path) -> None:
    """``a + b`` → ``b + a`` evaluates to the original value, so nothing dies.

    The #336 class, in its purest form: the edit *looks* like a degradation.
    """
    tree = _project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="commuted",
            old="return a + b",
            new="return b + a",
            kills=f'["{_ADD}"]',
            note="the entry claims addition is order-sensitive, and it is not",
        ),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "commuted" in result.stdout
    assert "SURVIVED" in result.stdout
    assert "KILLED" not in result.stdout
    assert f"predicted but survived: {_ADD}" in result.stdout


def test_a_collection_breaking_mutation_reports_as_a_failure_of_the_entry(
    tmp_path: Path,
) -> None:
    """Breaking the module's syntax is over-kill, not proof.

    The predicted test *is* among the casualties, so a containment rule would
    certify this as a kill. Set equality does not: the observed set carries the
    collector's node id, which no prediction naming tests can equal.
    """
    tree = _project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="broken-syntax",
            old="def add(a, b):",
            new="def add(a, b:",
            kills=f'["{_ADD}"]',
            note="this is not a degradation, it is a syntax error",
        ),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "broken-syntax" in result.stdout
    assert "MISPREDICTED" in result.stdout
    assert "KILLED" not in result.stdout
    assert "collection broken" in result.stdout
    assert f"predicted but survived: {_ADD}" in result.stdout


def test_the_tree_is_pristine_after_every_entry(tmp_path: Path) -> None:
    """Three entries, two of them defective, and the tree comes back byte-identical."""
    tree = _project(tmp_path)
    before = _snapshot(tree)
    table = _table(
        tmp_path,
        entries=_entry(ident="honest", old="return a + b", new="return a - b", kills=f'["{_ADD}"]')
        + _entry(ident="commuted", old="return a * b", new="return b * a", kills=f'["{_ADD}"]')
        + _entry(ident="broken", old="def sub(a, b):", new="def sub(a, b:", kills=f'["{_ADD}"]'),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert _snapshot(tree) == before


# ---------------------------------------------------------------------------
# Preconditions, against a real suite.
# ---------------------------------------------------------------------------


def test_a_red_baseline_refuses_naming_the_failing_test(tmp_path: Path) -> None:
    """AC-4, end to end: a pre-existing red is never read as a kill."""
    tree = _project(
        tmp_path, tests=_TESTS.replace("assert sub(5, 3) == 2", "assert sub(5, 3) == 9")
    )
    before = _snapshot(tree)
    table = _table(
        tmp_path,
        entries=_entry(ident="honest", old="return a + b", new="return a - b", kills=f'["{_ADD}"]'),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "refused (baseline)" in result.stderr
    assert "tests/test_calc.py::test_sub" in result.stderr
    assert _snapshot(tree) == before


def test_the_baseline_uses_the_synthetic_projects_own_config(tmp_path: Path) -> None:
    """Three tests collected, not this repo's several thousand.

    The silent failure this rules out: a child pytest that resolved *this*
    repo's ``pyproject.toml`` would run the harness suite, and every assertion in
    this module would be measuring the wrong thing.
    """
    tree = _project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(ident="honest", old="return a + b", new="return a - b", kills=f'["{_ADD}"]'),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed, 3 collected" in result.stdout


def test_the_tables_selection_reaches_the_child_pytest(tmp_path: Path) -> None:
    """``select`` is a real pytest selection, not decoration.

    The #336 affordance the ticket asks for: a tick mutates against
    ``-m "unit or guard"`` rather than the whole suite. Measured by the count
    the baseline reports — one marked test out of three.
    """
    tree = _project(tmp_path)
    table = _table(
        tmp_path,
        select='["-m", "fast"]',
        entries=_entry(ident="honest", old="return a + b", new="return a - b", kills=f'["{_ADD}"]'),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed, 1 collected" in result.stdout
    assert '[-m fast]' in result.stdout


def test_a_wrong_tree_is_refused_before_the_baseline_runs(tmp_path: Path) -> None:
    """A wrong ``--tree`` costs a refusal, not a suite run and not a mutation."""
    tree = _project(tmp_path)
    before = _snapshot(tree)
    table = _table(
        tmp_path,
        sentinel_text="a-sentinel-this-tree-does-not-carry",
        entries=_entry(ident="honest", old="return a + b", new="return a - b", kills=f'["{_ADD}"]'),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "refused (containment)" in result.stderr
    assert _snapshot(tree) == before


def test_check_validates_without_running_or_writing_anything(tmp_path: Path) -> None:
    """The cheap loop: get a table to land before spending a baseline."""
    tree = _project(tmp_path)
    before = _snapshot(tree)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="nowhere", old="return a / b", new="return a // b", kills=f'["{_ADD}"]'
        ),
    )

    result = _run("check", table, tree, tmp_path)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "refused (landing)" in result.stderr
    assert "0 occurrences" in result.stderr
    assert _snapshot(tree) == before
    assert not (tmp_path / "work").exists()


def _poison_bytecode(tree: Path) -> Path:
    """Plant a ``__pycache__`` entry for ``calc.py`` whose code says ``add`` is 999.

    The header claims the *real* source's ``(mtime, size)``, which is the whole
    of CPython's staleness test — so an interpreter that consults the in-tree
    cache loads this instead of the file on disk.
    """
    import importlib.util
    import marshal
    import struct

    source = tree / "calc.py"
    stat = source.stat()
    code = compile(_CALC.replace("return a + b", "return 999"), str(source), "exec")
    cache = Path(importlib.util.cache_from_source(str(source)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    header = importlib.util.MAGIC_NUMBER + struct.pack(
        "<III", 0, int(stat.st_mtime) & 0xFFFFFFFF, stat.st_size & 0xFFFFFFFF
    )
    cache.write_bytes(header + marshal.dumps(code))
    return cache


def test_a_stale_bytecode_cache_cannot_mask_a_same_size_mutation(tmp_path: Path) -> None:
    """The mutation most likely to be masked is the most ordinary one.

    CPython validates a ``.pyc`` on the source's ``(mtime, size)``, and a
    mutation is very often exactly the same size as what it replaced —
    ``a + b`` -> ``a - b``. Written inside one clock second, an in-tree
    ``__pycache__`` then serves the *unmutated* module: the entry reports
    SURVIVED having never run, which is the #336 failure arriving from the
    infrastructure rather than from the table. ``PYTHONPYCACHEPREFIX`` points
    the child at a fresh cache outside the tree, so the source on disk is what
    runs.

    The first half is the positive control, and it is what stops this test
    passing for the wrong reason: a malformed poison would be *ignored* by both
    interpreters, and the harness assertion alone would certify nothing.
    """
    tree = _project(tmp_path)
    poison = _poison_bytecode(tree)

    control = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert control.returncode != 0, (
        "the planted cache must actually be loaded by a default interpreter, "
        f"or this test proves nothing: {control.stdout}"
    )
    # Bound to the mechanism, not merely to a red exit: exactly the one test
    # whose function the poison rewrites must be the one that fails.
    assert "1 failed, 2 passed" in control.stdout, control.stdout
    assert "test_add" in control.stdout, control.stdout
    assert poison.exists()

    table = _table(
        tmp_path,
        entries=_entry(
            ident="same-size",
            old="return a + b",
            new="return a - b",
            kills=f'["{_ADD}"]',
        ),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "KILLED" in result.stdout


def test_an_unrunnable_selection_exits_3_not_2(tmp_path: Path) -> None:
    """Infrastructure and a red tree are different answers.

    A pytest that never starts says nothing about the tree, so it must not be
    reported as the refusal that means "your baseline is red" — an operator who
    conflated the two would go looking for a failing test that does not exist.
    Driven by a real usage error, so the plugin genuinely never writes its file.
    """
    tree = _project(tmp_path)
    before = _snapshot(tree)
    table = _table(
        tmp_path,
        select='["--no-such-pytest-flag"]',
        entries=_entry(ident="honest", old="return a + b", new="return a - b", kills=f'["{_ADD}"]'),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 3, result.stdout + result.stderr
    assert "runner unavailable" in result.stderr
    assert _snapshot(tree) == before


# ---------------------------------------------------------------------------
# Integration points the ticket puts out of scope.
# ---------------------------------------------------------------------------


def test_verify_does_not_run_mutate() -> None:
    """A build-time instrument, never a gate stage (#360 "Out of scope").

    Mutation is how a new guard is *proven while it is written*; running it in
    the gate would mean every change paying for every past tick's table.
    """
    body = _VERIFY.read_text(encoding="utf-8")

    assert "mutate.py" not in body, (
        "scripts/verify.sh must not run scripts/mutate.py — mutation is a "
        "build-time instrument, not a verification stage (#360)."
    )


@pytest.mark.parametrize(
    ("module", "forbidden"),
    [(_PLUGIN, "mutate"), (_SCRIPT, "_mutate_outcomes")],
    ids=["plugin-does-not-import-harness", "harness-does-not-import-plugin"],
)
def test_the_plugin_and_the_harness_do_not_import_each_other(
    module: Path, forbidden: str
) -> None:
    """The plugin runs in the child with only ``scripts/`` on ``PYTHONPATH``.

    A shared import would work from this checkout and fail under any other
    invocation — the failure mode that only shows up once someone else runs it.
    """
    import ast

    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for name in (alias.name for alias in node.names)
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert forbidden not in imported, f"{module.name} must not import {forbidden}"


# ---------------------------------------------------------------------------
# #365 — the paired fixture that discriminates `inert` from `survived`.
# ---------------------------------------------------------------------------

_SEL = '''"""A selection over one corpus — #209 reduced to three strings."""

CORPUS = ["alpha", "alpha_beta", "beta"]


def chosen():
    return sorted(n for n in CORPUS if n.startswith("alpha"))
'''

#: Deliberately weak: it constrains the *shape* of the answer and nothing about
#: which names are in it, so both mutations below sail past it. That is the
#: point — the fixture needs a guard that notices neither, so the only thing
#: separating the two entries is whether the mutation was live.
_SEL_TESTS = '''from sel import chosen


def test_chosen_is_sorted():
    assert chosen() == sorted(chosen())
'''

_CHOSEN_IS_SORTED = "tests/test_sel.py::test_chosen_is_sorted"
_OBSERVE = '''["-c", "import sel; print(*sel.chosen(), sep=chr(10))"]'''


def _selection_project(tmp_path: Path) -> Path:
    """A corpus, a selection over it, and one guard too weak to see either change.

    Its own project rather than a module added to :func:`_project`, whose
    collected counts are asserted verbatim by the tests above.
    """
    tree = tmp_path / "selection"
    (tree / "tests").mkdir(parents=True)
    (tree / "sel.py").write_text(_SEL, encoding="utf-8")
    (tree / "tests" / "test_sel.py").write_text(_SEL_TESTS, encoding="utf-8")
    (tree / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tree / "MARKER.md").write_text(f"{_SENTINEL}\n", encoding="utf-8")
    (tree / "conftest.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n",
        encoding="utf-8",
    )
    return tree


def test_inert_and_live_survivors_are_told_apart_by_one_observable(tmp_path: Path) -> None:
    """AC-4 — two entries differing *only* in whether the mutation changed behaviour.

    One table, one guard, one observable, one invocation, so "they differ only
    in that" is a fact about the fixture rather than a claim in a docstring. Two
    unrelated fixtures would not show the check discriminates.

    Over ``["alpha", "alpha_beta", "beta"]``:

    * ``equivalent`` — ``startswith("alpha")`` → ``not startswith("beta")``
      selects the identical two names. A real textual change that lands exactly
      once and passes every refusal #360 has, and it changed nothing. This is
      tick #209's ``-m "not docker"`` → ``tests/unit -m "not docker"`` in
      miniature: two selections over one corpus that collect the same set.
    * ``live`` — ``startswith("alpha")`` → ``startswith("b")`` selects ``beta``.
      The guard stays green, so the guard really is weak.

    Before #365 both printed SURVIVED and a reader was free to take either for
    whichever meaning suited them.
    """
    tree = _selection_project(tmp_path)
    table = _table(
        tmp_path,
        entries=(
            _entry(
                ident="equivalent",
                file="sel.py",
                old='n.startswith("alpha")',
                new='not n.startswith("beta")',
                kills=f'["{_CHOSEN_IS_SORTED}"]',
                observe=_OBSERVE,
            )
            + _entry(
                ident="live",
                file="sel.py",
                old='n.startswith("alpha")',
                new='n.startswith("b")',
                kills=f'["{_CHOSEN_IS_SORTED}"]',
                observe=_OBSERVE,
            )
        ),
    )

    result = _run("run", table, tree, tmp_path)
    report = result.stdout

    assert result.returncode == 4, report + result.stderr
    equivalent, live = _entry_lines(report, "equivalent", "live")
    assert "INERT" in equivalent, report
    assert "SURVIVED (LIVE)" in live, report
    # Each word attached to its own entry, not merely both present somewhere.
    assert "INERT" not in live and "SURVIVED" not in equivalent, report
    assert "RESULT: 1 entry is inert" in report


def test_a_survivor_with_no_observable_is_unproven_end_to_end(tmp_path: Path) -> None:
    """AC-2 over the real script: same outcome, same exit code, a named remedy.

    Read against the paired fixture above, this is what makes ``(UNPROVEN)``
    load-bearing: the *same* inert mutation, with the observable removed, can no
    longer be reported as a survivor at all.
    """
    tree = _selection_project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="equivalent",
            file="sel.py",
            old='n.startswith("alpha")',
            new='not n.startswith("beta")',
            kills=f'["{_CHOSEN_IS_SORTED}"]',
        ),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "SURVIVED (UNPROVEN)" in result.stdout
    assert "declares no `observe`" in result.stdout
    assert "observe = [" in result.stdout
    assert "INERT" not in result.stdout


def test_a_nondeterministic_observable_is_refused_end_to_end(tmp_path: Path) -> None:
    """AC-3 over a genuinely nondeterministic probe, not a contrived one.

    A clock always "differs", so without this refusal it would certify every
    mutation in the table as live — the report reading strongest exactly when it
    measured least.
    """
    tree = _selection_project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="clock",
            file="sel.py",
            old='n.startswith("alpha")',
            new='n.startswith("b")',
            kills=f'["{_CHOSEN_IS_SORTED}"]',
            observe='''["-c", "import time; print(time.time_ns())"]''',
        ),
    )
    before = _snapshot(tree)

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "refused (observable)" in result.stderr
    assert "clock" in result.stderr
    assert "not deterministic" in result.stderr
    assert _snapshot(tree) == before


def test_the_observable_really_runs_against_the_mutated_tree(tmp_path: Path) -> None:
    """The `live` verdict is worthless unless the probe saw ``new`` on disk.

    Proven the only way a black-box run can: the probe prints the mutated source
    itself, so an observable running after the restore would digest the pristine
    text and the entry would report ``inert`` instead.
    """
    tree = _selection_project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="reads-source",
            file="sel.py",
            old='n.startswith("alpha")',
            new='n.startswith("b")',
            kills=f'["{_CHOSEN_IS_SORTED}"]',
            observe='''["-c", "print(open('sel.py').read())"]''',
        ),
    )

    result = _run("run", table, tree, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "SURVIVED (LIVE)" in result.stdout
    assert _snapshot(tree)[tree / "sel.py"] == _SEL.encode("utf-8")


def _entry_lines(report: str, *idents: str) -> list[str]:
    """The report block belonging to each entry — id line plus its advisories.

    Without this split, "both words appear in the output" would pass on a
    harness that printed them against the wrong entries.
    """
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in report.splitlines():
        head = line.split(" ", 1)[0]
        if head in idents and not line.startswith(" "):
            current = head
            blocks[current] = []
        elif not line.startswith(" "):
            current = None
        if current:
            blocks[current].append(line)
    missing = [ident for ident in idents if ident not in blocks]
    assert not missing, f"no report block for {missing} in:\n{report}"
    return ["\n".join(blocks[ident]) for ident in idents]


def test_an_import_based_observable_sees_a_same_size_mutation(tmp_path: Path) -> None:
    """The staleness trap #360 met in the runner, arriving at the new spawn site.

    ``"alpha"`` → ``"betaX"`` is exactly the same number of bytes, so CPython's
    ``(mtime, size)`` validation would accept a ``.pyc`` compiled from the
    *pristine* module if one were written into the tree. An observable that
    imports would then digest identically and the entry would report ``INERT``
    — a live mutation dismissed as a table defect, which is the one verdict this
    stage must never invent. :class:`PythonObserver` redirects
    ``PYTHONPYCACHEPREFIX`` per run, so the import compiles from the source on
    disk and the tree gets no ``__pycache__`` written into it either.

    The corpus holds no name starting with ``betaX``, so the selection empties
    while the shape guard stays green: live, and unnoticed.

    The child's ``PYTHONPYCACHEPREFIX`` is **cleared deliberately**. Inheriting
    it made this test pass for the wrong reason — when this module runs under a
    mutation harness, that harness's own prefix propagates down and supplies the
    defence, so deleting the line under test changed nothing and the entry
    reported SURVIVED. Clearing it is what makes the assertion measure
    :class:`PythonObserver`'s own behaviour rather than an inherited variable.
    """
    tree = _selection_project(tmp_path)
    table = _table(
        tmp_path,
        entries=_entry(
            ident="same-size",
            file="sel.py",
            old='n.startswith("alpha")',
            new='n.startswith("betaX")',
            kills=f'["{_CHOSEN_IS_SORTED}"]',
            observe=_OBSERVE,
        ),
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPYCACHEPREFIX"}
    env.pop("PYTHONDONTWRITEBYTECODE", None)

    result = _run("run", table, tree, tmp_path, env=env)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "SURVIVED (LIVE)" in result.stdout
    assert "INERT" not in result.stdout
    assert not list(tree.rglob("__pycache__")), "the observable left droppings in the tree"
