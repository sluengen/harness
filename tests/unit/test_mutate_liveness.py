"""#365 — a surviving mutation must prove it changed behaviour.

#360 made the mutation harness's shared rules structural, and closed the
dangerous direction: an entry declares the tests it must kill and the observed
failure set is compared by **set equality**, so an over-killing
collection-breaker is ``mispredicted`` rather than the kill it appears to be.

What it left open, by an explicit design call, is telling an **inert** mutation
from a **weak guard**. Both report ``survived``, and the module said so: *"the
no-op direction is self-limiting — SURVIVED forces an investigation."* That is a
habit, not a mechanism, and #209 is what it costs. Mutating the gate's parallel
stage from ``-m "not docker"`` to ``tests/unit -m "not docker"`` is a real
textual change that lands exactly once and passes every refusal #360 has — but
``tests/integration/`` holds only docker-marked modules, so both spellings
collect the identical 4,826 tests. It changed nothing and reported SURVIVED.

The sharper cost was the other direction: that tick's adversarial review used a
no-op mutation as its evidence for a real BLOCKING finding. The finding was
right and its proof was invalid, independently. ``SURVIVED`` was an
unclassified result a reader was free to read as whichever meaning suited them.

So an entry may declare a **behavioural observable** — argv appended to this
interpreter, run inside the tree — and a survivor is classified by it:

* digests differ → ``survived``, rendered ``(LIVE)``. The genuinely weak guard.
* digests equal → ``inert``. A table defect, and its own exit code.
* no observable → ``survived``, rendered ``(UNPROVEN)``. Nothing has shown this
  mutation was live, so it is not evidence that the guard is weak.

These tests drive that fork through a stubbed ``Observer``, the seam that
mirrors #360's ``Runner``. The end-to-end proof — including AC-4's paired
fixture, where the discrimination claim is worth nothing against a stub — is in
:mod:`tests.unit.test_mutate_end_to_end`.

Its own module rather than more of :mod:`tests.unit.test_mutate`: that module's
recorded size decision is that #360's *acceptance matrix* reads as one surface,
and AC-5 requires its tests to keep passing **unmodified**, which a diff that
touches none of its lines states more plainly than a paragraph could.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import mutate  # noqa: E402

_SENTINEL = "harness-365-mini-tree"

_ADD = "tests/test_calc.py::test_add"
_GREEN = mutate.RunOutcome(
    ok=True,
    passed=frozenset({_ADD, "tests/test_calc.py::test_sub"}),
    failed=frozenset(),
    errored=frozenset(),
    collected=2,
    duration_s=0.5,
)


def _mini_tree(tmp_path: Path) -> Path:
    tree = tmp_path / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    (tree / "MARKER.md").write_text(f"the tree you meant: {_SENTINEL}\n", encoding="utf-8")
    target = tree / "pkg" / "calc.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    return tree


def _entry(
    *,
    ident: str = "e1",
    old: str = "a + b",
    new: str = "a - b",
    kills: str = f'["{_ADD}"]',
    observe: str | None = None,
) -> str:
    text = (
        "\n[[mutation]]\n"
        f'id = "{ident}"\n'
        'file = "pkg/calc.py"\n'
        f"old = '''{old}'''\n"
        f"new = '''{new}'''\n"
        f"kills = {kills}\n"
    )
    if observe is not None:
        text += f"observe = {observe}\n"
    return text


def _table(tmp_path: Path, mutations: str) -> mutate.MutationTable:
    path = tmp_path / "table.toml"
    path.write_text(
        'select = ["-m", "unit"]\n'
        'sentinel_file = "MARKER.md"\n'
        f'sentinel_text = "{_SENTINEL}"\n'
        f"{mutations}",
        encoding="utf-8",
    )
    return mutate.load_table(path)


class _StubRunner:
    def __init__(self, *outcomes: mutate.RunOutcome) -> None:
        self._queue = list(outcomes)

    def __call__(self, tree: Path, select: list[str]) -> mutate.RunOutcome:
        if not self._queue:
            raise AssertionError("the runner was called more times than queued")
        return self._queue.pop(0)


class _StubObserver:
    """Returns queued observations in order, recording the target's bytes at call time.

    ``seen`` is the same instrument :class:`tests.unit.test_mutate._StubRunner`
    uses: it is the only way to assert that the mutated observation really ran
    against the **mutated** tree, which no digest comparison can prove on its own.
    """

    def __init__(self, *observations: mutate.Observation, target: str = "pkg/calc.py") -> None:
        self._queue = list(observations)
        self._target = target
        self.calls = 0
        self.seen: list[bytes] = []

    def __call__(self, tree: Path, observe: tuple[str, ...]) -> mutate.Observation:
        self.calls += 1
        probe = tree / self._target
        self.seen.append(probe.read_bytes() if probe.exists() else b"")
        if not self._queue:
            raise AssertionError("the observer was called more times than queued")
        return self._queue.pop(0)


def _obs(
    out: bytes = b"same", *, ok: bool = True, returncode: int = 0, detail: str = ""
) -> mutate.Observation:
    return mutate.Observation(
        ok=ok, returncode=returncode, stdout=out, duration_s=0.1, detail=detail
    )


def _run(
    tmp_path: Path,
    tree: Path,
    table: mutate.MutationTable,
    observer: _StubObserver,
    *,
    mutated: mutate.RunOutcome | None = None,
    runs: int = 1,
) -> mutate.Report:
    """A green baseline, then ``runs`` identical mutated suite runs."""
    return mutate.run_plan(
        table,
        tree,
        runner=_StubRunner(_GREEN, *([mutated or _GREEN] * runs)),
        observer=observer,
        work_dir=tmp_path / "work",
    )


# ---------------------------------------------------------------------------
# AC-1 — an observable that produced identical output makes the entry `inert`.
# ---------------------------------------------------------------------------


def test_a_survivor_whose_observable_did_not_move_is_inert(tmp_path: Path) -> None:
    """The #209 shape: a real textual change that selects the identical set.

    The mutation lands, the suite stays green, and the observable — the one
    thing that can tell "the guard is weak" from "nothing happened" — comes back
    byte-identical. That is a table defect, and it gets its own outcome and its
    own exit code so it cannot be read as evidence against the guard.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(_obs(b"same"), _obs(b"same"), _obs(b"same"))

    report = _run(tmp_path, tree, table, observer)

    (result,) = report.results
    assert result.outcome == "inert"
    assert mutate.exit_code(report) == 4
    rendered = mutate.render(report)
    assert "INERT" in rendered
    assert "identical output on the pristine and mutated tree" in rendered
    assert "defect in entry `e1`" in rendered
    assert "not a weak guard" in rendered
    assert "RESULT: 1 entry is inert" in rendered


def test_a_survivor_whose_observable_moved_is_a_live_survivor(tmp_path: Path) -> None:
    """The other half of the pair: the guard genuinely failed to notice.

    Same outcome token as before this change — a weak guard is still
    ``survived`` — but now it is the *only* thing ``SURVIVED`` can mean once an
    observable is declared, which is what makes it usable as evidence.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(_obs(b"same"), _obs(b"same"), _obs(b"moved"))

    report = _run(tmp_path, tree, table, observer)

    (result,) = report.results
    assert result.outcome == "survived"
    assert mutate.exit_code(report) == 1
    assert "SURVIVED (LIVE)" in mutate.render(report)


def test_a_survivor_with_no_observable_is_reported_unproven(tmp_path: Path) -> None:
    """AC-2 — a survivor nobody has shown to be live is not presentable as evidence.

    The outcome token and the exit code are deliberately unchanged (AC-5 pins
    both in :mod:`tests.unit.test_mutate`); what changes is that the report now
    says the mutation is unproven and names what to add.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry())
    observer = _StubObserver()

    report = _run(tmp_path, tree, table, observer)

    (result,) = report.results
    assert result.outcome == "survived"
    assert mutate.exit_code(report) == 1
    rendered = mutate.render(report)
    assert "SURVIVED (UNPROVEN)" in rendered
    assert "unproven: entry `e1` declares no `observe`" in rendered
    assert "observe = [" in rendered, "the advisory must name what to add"
    assert observer.calls == 0


def test_a_360_era_table_spawns_no_observable_at_all(tmp_path: Path) -> None:
    """AC-5, as a behaviour rather than a claim: no `observe` anywhere costs nothing.

    An entry that *kills* is manifestly live, so it is never asked for a second
    witness either — and a table written before #365 has no witness to ask.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(ident="honest"))
    observer = _StubObserver()
    killed = mutate.RunOutcome(
        ok=True,
        passed=frozenset({"tests/test_calc.py::test_sub"}),
        failed=frozenset({_ADD}),
        errored=frozenset(),
        collected=2,
        duration_s=0.4,
    )

    report = _run(tmp_path, tree, table, observer, mutated=killed)

    (result,) = report.results
    assert result.outcome == "killed"
    assert mutate.exit_code(report) == 0
    assert observer.calls == 0
    assert "RESULT: honest" in mutate.render(report)


@pytest.mark.parametrize(
    ("label", "mutated"),
    [
        (
            "killed",
            mutate.RunOutcome(
                ok=True,
                passed=frozenset({"tests/test_calc.py::test_sub"}),
                failed=frozenset({_ADD}),
                errored=frozenset(),
                collected=2,
                duration_s=0.4,
            ),
        ),
        (
            "mispredicted",
            mutate.RunOutcome(
                ok=True,
                passed=frozenset(),
                failed=frozenset({_ADD, "tests/test_calc.py::test_sub"}),
                errored=frozenset(),
                collected=2,
                duration_s=0.4,
            ),
        ),
    ],
    ids=["killed", "mispredicted"],
)
def test_an_entry_that_killed_something_is_never_asked_for_a_witness(
    tmp_path: Path, label: str, mutated: mutate.RunOutcome
) -> None:
    """A narrow probe must not get to downgrade a real kill to `inert`.

    Both entries here declare an observable that would digest identically. If
    the observable ran on them, each would be reclassified — and the harness
    would be letting the witness decide a case the failure set already settled.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(_obs(b"same"), _obs(b"same"))

    report = _run(tmp_path, tree, table, observer, mutated=mutated)

    (result,) = report.results
    assert result.outcome == label
    # Two calls: the pristine determinism pair, and nothing on the mutated tree.
    assert observer.calls == 2


# ---------------------------------------------------------------------------
# AC-3 — the observable is itself checked, on the pristine tree.
# ---------------------------------------------------------------------------


def test_a_nondeterministic_observable_is_refused(tmp_path: Path) -> None:
    """Otherwise it "differs" against every mutation and certifies them all live.

    That is the unguarded degree of freedom #360 refused a blast-radius
    threshold for, arriving through the new stage.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import time; print(time.time())"]'))
    observer = _StubObserver(_obs(b"tick-one"), _obs(b"tick-two"))

    with pytest.raises(mutate.RefusalError) as excinfo:
        _run(tmp_path, tree, table, observer)

    assert excinfo.value.reason == "observable"
    message = str(excinfo.value)
    assert "e1" in message
    assert "import time; print(time.time())" in message, "the argv is what to re-run"
    assert "tick-one" not in message and "tick-two" not in message


def test_a_nondeterministic_observable_refuses_before_any_write(tmp_path: Path) -> None:
    tree = _mini_tree(tmp_path)
    before = (tree / "pkg" / "calc.py").read_bytes()
    table = _table(tmp_path, _entry(observe='["-c", "import random; print(random.random())"]'))
    observer = _StubObserver(_obs(b"one"), _obs(b"two"))

    with pytest.raises(mutate.RefusalError):
        _run(tmp_path, tree, table, observer)

    assert (tree / "pkg" / "calc.py").read_bytes() == before


def test_an_observable_already_failing_on_the_pristine_tree_is_refused(tmp_path: Path) -> None:
    """A broken probe breaks identically on both trees, so every entry reads `inert`.

    A wrong verdict that accuses the table, delivered with confidence — the
    green-baseline rule, applied to the observable.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "raise SystemExit(3)"]'))
    observer = _StubObserver(_obs(b"", returncode=3))

    with pytest.raises(mutate.RefusalError) as excinfo:
        _run(tmp_path, tree, table, observer)

    assert excinfo.value.reason == "observable"
    message = str(excinfo.value)
    assert "exited 3" in message
    # Distinct from the nondeterminism message, so the two branches cannot be
    # satisfied by one "it refuses" assertion.
    assert "not deterministic" not in message


def test_an_unrunnable_observable_is_infrastructure_not_a_refusal(tmp_path: Path) -> None:
    """Exit 3, the same split :func:`_check_baseline` already makes."""
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(_obs(ok=False))

    with pytest.raises(mutate.RunnerUnavailableError) as excinfo:
        _run(tmp_path, tree, table, observer)

    assert "pristine tree" in str(excinfo.value)


def test_a_mistyped_prediction_refuses_before_the_observable_stage(tmp_path: Path) -> None:
    """Ordering: the cheaper table defect must not be paid for at observable prices."""
    tree = _mini_tree(tmp_path)
    table = _table(
        tmp_path,
        _entry(kills='["tests/test_calc.py::test_typo"]', observe='["-c", "print(1)"]'),
    )
    observer = _StubObserver()

    with pytest.raises(mutate.RefusalError) as excinfo:
        _run(tmp_path, tree, table, observer)

    assert excinfo.value.reason == "prediction"
    assert observer.calls == 0


def test_one_observable_shared_by_two_entries_is_probed_once(tmp_path: Path) -> None:
    """Dedup is by argv: two entries sharing a probe pay two runs total, not four."""
    tree = _mini_tree(tmp_path)
    table = _table(
        tmp_path,
        _entry(ident="a", old="a + b", new="a - b", observe='["-c", "import pkg.calc"]')
        + _entry(ident="b", old="def add", new="def added", observe='["-c", "import pkg.calc"]'),
    )
    observer = _StubObserver(
        _obs(b"same"), _obs(b"same"), _obs(b"same"), _obs(b"moved")
    )

    report = _run(tmp_path, tree, table, observer, runs=2)

    assert [result.outcome for result in report.results] == ["inert", "survived"]
    # 2 determinism runs for the one distinct argv + 1 mutated run per survivor.
    assert observer.calls == 4


# ---------------------------------------------------------------------------
# The mutated observation: when it runs, against what, and what it may not say.
# ---------------------------------------------------------------------------


def test_the_mutated_observation_runs_against_the_mutated_tree(tmp_path: Path) -> None:
    """The property no digest comparison can prove about itself.

    An observable run after the restore would digest the pristine tree and
    report every entry ``inert`` — the failure mode that looks exactly like a
    working harness.
    """
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(_obs(b"same"), _obs(b"same"), _obs(b"moved"))

    _run(tmp_path, tree, table, observer)

    assert b"a - b" in observer.seen[-1], "the observable saw `new` on disk"
    assert b"a + b" in observer.seen[0], "the determinism runs saw the pristine tree"
    assert (tree / "pkg" / "calc.py").read_bytes() == b"def add(a, b):\n    return a + b\n"


def test_a_mutated_observation_that_could_not_complete_is_errored_never_inert(
    tmp_path: Path,
) -> None:
    """Reading a missing measurement as a measurement of nothing is the lie to avoid."""
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(
        _obs(b"same"), _obs(b"same"), _obs(ok=False, detail="timed out after 900s")
    )

    report = _run(tmp_path, tree, table, observer)

    (result,) = report.results
    assert result.outcome == "errored"
    assert "timed out after 900s" in result.detail
    assert "<python> -c import pkg.calc" in result.detail
    assert mutate.exit_code(report) == 1


def test_a_raising_observer_leaves_the_tree_restored(tmp_path: Path) -> None:
    """The restore ``finally`` covers the new call too, not only the runner's."""
    tree = _mini_tree(tmp_path)
    before = (tree / "pkg" / "calc.py").read_bytes()
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))

    class _Raising(_StubObserver):
        def __call__(self, tree: Path, observe: tuple[str, ...]) -> mutate.Observation:
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("boom")
            return _obs(b"same")

    with pytest.raises(RuntimeError):
        _run(tmp_path, tree, table, _Raising())

    assert (tree / "pkg" / "calc.py").read_bytes() == before


def test_no_observable_output_reaches_the_rendered_report(tmp_path: Path) -> None:
    """A report is pasted into a ticket; a probe's output is not bounded evidence."""
    tree = _mini_tree(tmp_path)
    table = _table(tmp_path, _entry(observe='["-c", "import pkg.calc"]'))
    observer = _StubObserver(
        _obs(b"PRISTINE-SECRET"), _obs(b"PRISTINE-SECRET"), _obs(b"MUTATED-SECRET")
    )

    rendered = mutate.render(_run(tmp_path, tree, table, observer))

    assert "PRISTINE-SECRET" not in rendered
    assert "MUTATED-SECRET" not in rendered
    assert "SURVIVED (LIVE)" in rendered


# ---------------------------------------------------------------------------
# Table shape — refused by ``load_table``, so ``check`` catches it for free.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "observe",
    ["[]", '"python -c print(1)"', "[1]", '[""]', "42"],
    ids=["empty", "shell-string", "non-string", "empty-string", "scalar"],
)
def test_a_malformed_observable_is_refused_at_table_load(tmp_path: Path, observe: str) -> None:
    """A shell string is refused rather than split — splitting it is the first
    step toward reaching a second binary, which is the thing that must stay
    unreachable from this module."""
    with pytest.raises(mutate.RefusalError) as excinfo:
        _table(tmp_path, _entry(observe=observe))

    assert excinfo.value.reason == "table"
    assert "e1" in str(excinfo.value)


def test_the_digest_is_length_prefixed_so_streams_cannot_collide() -> None:
    """``("a", "b")`` and ``("ab", "")`` are different observations."""
    split = mutate.Observation(ok=True, stdout=b"a", stderr=b"b")
    joined = mutate.Observation(ok=True, stdout=b"ab", stderr=b"")

    assert split.digest != joined.digest


def test_the_digest_covers_the_return_code() -> None:
    """A probe whose only signal is its exit status still witnesses a mutation."""
    quiet_ok = mutate.Observation(ok=True, returncode=0)
    quiet_bad = mutate.Observation(ok=True, returncode=1)

    assert quiet_ok.digest != quiet_bad.digest
