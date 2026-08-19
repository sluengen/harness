"""The gate's toolchain preflight, and the rule that decides what it probes.

Admission (ADR 0017 D5): class (a) — ``scripts/verify.sh`` **executed** against
a stubbed toolchain, asserting the exit code and diagnostic the preflight
produces. Emphatically not (e): nothing here reads the shell's text. A text
guard over shell degrades in one direction — it can be defeated by a spelling it
does not know, and it constrains the file to the spellings it does
(``specs/architecture-principles.md`` → *CI logic lives in a script, not in a
`run:` block*, four tickets of evidence) — so the correspondence is held by
running the script instead.

The preflight (CAL-1160) refuses with the reserved exit 97 — *the gate could not
run*, distinct from a red tree — when a tool it needs is unrunnable. #478 added
``node`` to it by hand after a live breakage: the gate itself runs no node, but
the suite it runs executes the enforcement hooks (``hooks/*.js``) under node and
**skips** those tests when node is missing, so a broken node produced a green
gate whose marker claimed a tree verified while the hook guards the marker
exists to serve were never run.

#491 supplies the missing membership rule, recorded as a Decision in
``specs/architecture-principles.md``: **a binary enters the preflight exactly
when a test resolves it off ``PATH`` at run time**, derived from the tracked
test sources by :mod:`tests.unit._toolchain` rather than remembered. Three
directions hold it, and each fails on a different edit:

* **admitting** — every member of the derived set is probed, so a new
  ``shutil.which("shellcheck")`` anywhere in the suite fails here, naming
  shellcheck, until ``scripts/verify.sh`` probes it;
* **stale** — a probe for a binary nothing resolves fails, since the run with
  the whole derived set stubbed must not refuse;
* **completion** — no skip-shaped construct sits anywhere but in a function
  that resolves a binary, which is what makes the derived set the *whole* set.

Both operands read the **git index**: the corpus the set is derived from, and
the script that is executed. ``git write-tree`` certifies the index and the gate
marker is named after the tree it produces, so a guard reading working files
certifies bytes that may never be committed (#482). **Unstaged work is invisible
here** — ``git add`` first, which every failure message below repeats.

**Size, justified rather than drifted into.** This module is past `engineering`'s
500-line hard limit, and the alternative was worse in a way this repo has
already paid for. The three directions are one contract — the derived set, its
completion condition, and the executed correspondence — and each is the
non-vacuity companion of another: the derivation's synthetic cases are what stop
the tree-wide sweep being an absence assertion over an empty set, and the
completion condition is the only thing that makes the derived set *whole*.
Splitting them puts a guard in one file and the floor that keeps it honest in
another, which is the shape craft.md names in *A deletion pass that moves a
definition must move its killer*. The pure derivation is already extracted to
``tests/unit/_toolchain.py``; what is left here is assertions and the fixtures
they need.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests._gitutil import indexed_text
from tests.unit._prose import REPO_ROOT
from tests.unit._toolchain import (
    SkipSite,
    declared_binaries,
    declared_binaries_from_tree,
    skip_sites,
    skip_sites_from_tree,
)

#: The reserved code: *the gate could not run* — distinct from a red tree (1).
GATE_UNRUNNABLE_EXIT = 97

#: The line the preflight prints before refusing.
PRECONDITION_FAILED = "gate precondition failed"

#: The one constant in the stub set, and the reason it is safe. Without a ``uv``
#: on ``PATH`` every run exits 97 at the very first probe, so every case in the
#: admitting direction would pass for the wrong reason — a false kill across the
#: whole parametrization. It goes stale in the **failing** direction only: if
#: the gate ever launches a second binary directly, the stale-direction control
#: below exits 97 and goes red. It cannot go stale silently.
#:
#: What that refusal *says* was measured rather than assumed, because a
#: diagnostic is a claim (#487): with this name wrong — every declared binary
#: stubbed and no ``uv`` on ``PATH`` — the run exits 97 reporting ``'ruff' is
#: not runnable under 'uv run --extra dev'``. The refusal is loud, but it names
#: the first probe that could not launch rather than the launcher, so a reader
#: of a red stale direction has to come here for the reason.
LAUNCHER = "uv"

#: The tracked binaries the suite resolves off ``PATH``, read at collection.
DECLARED = sorted(declared_binaries_from_tree())

_STAGE_FIRST = (
    "these guards read the git index, not the working tree — run `git add -A` "
    "before re-running, or they are judging bytes you have already changed"
)


def _stub(bindir: Path, name: str, *, exit_code: int = 0) -> None:
    stub = bindir / name
    stub.write_text(f"#!/bin/sh\nexit {exit_code}\n")
    stub.chmod(0o755)


def _run_gate(tmp_path: Path, bindir: Path) -> subprocess.CompletedProcess[str]:
    """Run the **indexed** ``scripts/verify.sh`` with ``bindir`` as the whole ``PATH``.

    The script is written out of the index and executed from a temporary file,
    so the bytes under test are the bytes that would ship. Nothing from the
    environment reaches the command line; the stubs are fixed content written by
    this module.
    """
    script = tmp_path / "verify-from-index.sh"
    script.write_text(indexed_text("scripts/verify.sh"), encoding="utf-8")
    return subprocess.run(
        ["/bin/bash", str(script)],
        cwd=REPO_ROOT,
        env={"PATH": str(bindir)},
        capture_output=True,
        text=True,
        timeout=100,
    )


def _toolchain(
    tmp_path: Path,
    label: str,
    *,
    present: Iterable[str],
    broken: Iterable[str] = (),
) -> Path:
    """A ``PATH`` holding the launcher plus the named stubs, and nothing else."""
    bindir = tmp_path / f"bin-{label}"
    bindir.mkdir(parents=True, exist_ok=True)
    _stub(bindir, LAUNCHER)
    for name in present:
        _stub(bindir, name)
    for name in broken:
        _stub(bindir, name, exit_code=1)
    return bindir


def _refuses_for(proc: subprocess.CompletedProcess[str], name: str) -> bool:
    """Did this run refuse *and* name ``name`` as a delimited token?

    Delimited, so a probe whose diagnostic merely happens to contain the letters
    — ``git`` inside ``digital``, ``jq`` inside a path — is not read as naming
    the tool an operator has to install.
    """
    return (
        proc.returncode == GATE_UNRUNNABLE_EXIT
        and PRECONDITION_FAILED in proc.stderr
        and re.search(rf"\b{re.escape(name)}\b", proc.stderr) is not None
    )


def unprobed(
    tmp_path: Path,
    names: Iterable[str],
    *,
    universe: Iterable[str] | None = None,
) -> set[str]:
    """The members of ``names`` the preflight does **not** refuse to run without.

    For each name, the gate is executed with every other member of ``universe``
    stubbed and that one absent. The verdict is behavioural throughout — an exit
    code and a diagnostic — and the tree supplies only which names to try.

    ``universe`` defaults to ``names``; callers testing a synthetic name pass
    the real derived set as well, so the run isolates the name under test
    instead of refusing earlier for an unrelated missing tool.
    """
    names = sorted(names)
    stubs = set(universe) if universe is not None else set(names)
    return {
        name
        for name in names
        if not _refuses_for(
            _run_gate(tmp_path, _toolchain(tmp_path, f"without-{name}", present=stubs - {name})),
            name,
        )
    }


# --- Direction 1: a dependency with no probe -----------------------------------


def test_the_derived_set_is_live() -> None:
    """The floor, in its own function, where an empty derivation cannot delete it.

    A parametrization whose subject source derives to ``[]`` collects nothing
    and the run stays green (craft.md → *The empty subject set*, *The floor
    inside the parametrization*). Membership rather than cardinality, so a
    number does not need re-deriving every time the suite grows: ``node`` is the
    anchor because it is the instance the rule was written for, and a rename
    names itself here instead of quietly emptying every case below.
    """
    assert DECLARED, (
        "no binary was derived from the tracked test corpus, so every case "
        f"parametrized over it checks nothing — {_STAGE_FIRST}"
    )
    assert "node" in DECLARED, (
        f"the suite no longer resolves node off PATH (derived: {DECLARED}); if that "
        "is deliberate, the hook guards have found another way to run and this "
        "anchor moves with them — do not simply delete it"
    )


def test_the_preflight_probes_every_binary_the_suite_resolves(tmp_path: Path) -> None:
    """AC-2, over the real tree: the admitting direction of the correspondence.

    The set is derived, never listed, so a new ``shutil.which("shellcheck")``
    anywhere in ``tests/`` adds a case here on the commit that introduces it —
    and fails until ``scripts/verify.sh`` grows the probe. That is the drift the
    preflight could previously only lose: the suite admits a host dependency,
    the preflight never hears of it, and the gate goes green over tests that
    silently did not run.

    This is an absence assertion, so it cannot prove itself. Its companions are
    :func:`test_the_derived_set_is_live` (the subject set is not empty) and
    :func:`test_an_undeclared_binary_is_reported_by_the_checker` (the checker is
    not constant-empty).
    """
    missing = unprobed(tmp_path, DECLARED)

    assert missing == set(), (
        f"the suite resolves {sorted(missing)} off PATH, and scripts/verify.sh's "
        "toolchain preflight does not refuse to run without them. A resolved "
        "binary that is absent makes the tests depending on it skip — silently, "
        "so the gate writes a marker claiming a tree verified minus those "
        "guards. Add a probe to scripts/verify.sh that exits "
        f"{GATE_UNRUNNABLE_EXIT} and names the tool. ({_STAGE_FIRST}.)"
    )


def test_an_undeclared_binary_is_reported_by_the_checker(tmp_path: Path) -> None:
    """AC-2's synthetic case: the checker reports a name no probe covers.

    Deliberately **not** the ``node`` instance, which #478 already closed. A
    binary nothing in ``scripts/verify.sh`` probes must come back from the same
    :func:`unprobed` the assertion above calls — a control that re-implemented
    the predicate would measure the control (craft.md, first entry), and one
    that never runs the gate could not tell an unprobed binary from an empty
    checker.
    """
    invented = "shellcheck"
    assert invented not in DECLARED, (
        f"{invented} is now a real dependency of this suite, so it can no longer "
        "play the part of one the preflight has never heard of — pick another"
    )

    reported = unprobed(tmp_path, {invented}, universe={*DECLARED, invented})

    assert reported == {invented}, (
        f"scripts/verify.sh refused to run without {invented}, which nothing in "
        "the suite resolves — or the checker returned nothing at all, in which "
        "case the assertion above is an absence test over an empty answer"
    )


def _broken(tmp_path: Path, name: str) -> subprocess.CompletedProcess[str]:
    """The gate, run against a ``name`` that is present on ``PATH`` and unrunnable."""
    return _run_gate(
        tmp_path,
        _toolchain(tmp_path, f"broken-{name}", present=set(DECLARED) - {name}, broken=[name]),
    )


# The two properties the refusal owes are asserted in **separate** tests, not as
# two lines of one, because a test stops at its first failing assertion: written
# together, the edit that drops the tool's name from the diagnostic would never
# reach the naming assertion on a run whose exit code had already failed, and
# each obligation would hide the other (craft.md -> *Every prose obligation needs
# a pair with separate exclusive killers*). Mutating the reserved exit kills only
# the first; mutating the diagnostic kills only the second.


@pytest.mark.parametrize("name", DECLARED)
def test_a_broken_binary_is_the_same_infrastructure_failure(name: str, tmp_path: Path) -> None:
    """*Unrunnable* is not *absent*, and the preflight must not tell them apart.

    The distinct property, and the shape the #478 breakage actually had: node
    was installed and on ``PATH``, and could not execute — homebrew had moved
    ``simdjson`` to soname 33 while node stayed linked against 29. A probe
    written as an existence check (``command -v``) passes that and leaves the
    suite skipping. The reserved code is the whole point: a caller has to be
    able to tell *the gate could not run* from *the gate ran and the tree is
    red*.
    """
    proc = _broken(tmp_path, name)

    assert proc.returncode == GATE_UNRUNNABLE_EXIT, (
        f"a {name} that cannot answer --version left the gate exiting "
        f"{proc.returncode} rather than the reserved {GATE_UNRUNNABLE_EXIT}; the "
        f"probe must execute it, not merely find it on PATH. stderr: {proc.stderr!r}"
    )


@pytest.mark.parametrize("name", DECLARED)
def test_the_refusal_names_the_tool_an_operator_has_to_install(
    name: str, tmp_path: Path
) -> None:
    """A reserved exit with no name is a puzzle, not a diagnostic.

    The exit code says *the gate could not run*; only the message says what to
    install. Asserted on a delimited token, so a diagnostic that merely happens
    to contain the letters does not read as naming the tool.
    """
    proc = _broken(tmp_path, name)

    assert PRECONDITION_FAILED in proc.stderr, (
        f"a broken {name} produced no precondition diagnostic at all: {proc.stderr!r}"
    )
    assert re.search(rf"\b{re.escape(name)}\b", proc.stderr), (
        f"the preflight refused without naming {name}, so an operator is told the "
        f"gate could not run and not what to fix: {proc.stderr!r}"
    )


# --- Direction 2: a probe with no dependency -----------------------------------


def test_the_preflight_probes_nothing_the_suite_does_not_resolve(tmp_path: Path) -> None:
    """The stale direction, as a single behavioural observation.

    No allowlist is consulted: the whole derived set is present, so a preflight
    that refuses anyway is probing something no test resolves, and the gate's
    own diagnostic names it. No deletion can exercise this direction, which is
    why it is a separate observation rather than another case above.

    If a future change makes the **gate itself** launch a binary directly, this
    goes red for a legitimate reason. The fix is not to add a name here — that
    quietly recreates the allowlist this design exists to avoid. Route it
    through ``uv run``, or extend the membership rule deliberately and record
    why in the Decision this module implements.
    """
    bindir = _toolchain(tmp_path, "complete", present=DECLARED)

    proc = _run_gate(tmp_path, bindir)

    assert proc.returncode != GATE_UNRUNNABLE_EXIT, (
        "the preflight refused to run with every binary the suite resolves "
        f"({DECLARED}) present, so it probes something no test resolves: "
        f"{proc.stderr!r}"
    )
    assert PRECONDITION_FAILED not in proc.stderr, (
        f"the preflight reported a failed precondition anyway: {proc.stderr!r}"
    )
    assert proc.returncode == 0, (
        "the gate did not run to completion under a fully stubbed toolchain, so "
        "this direction observed nothing about the preflight — a script that "
        "exits before the preflight is even reached satisfies both assertions "
        f"above (measured at review). It exited {proc.returncode}. "
        f"stdout: {proc.stdout!r} stderr: {proc.stderr!r}"
    )


# --- Direction 3: the completion condition -------------------------------------


def _offenders(sites: Iterable[SkipSite]) -> list[SkipSite]:
    return [site for site in sites if not site.compliant]


def test_the_suite_reaches_the_host_only_where_it_declares_the_dependency() -> None:
    """What makes the derived set the *whole* set (ADR 0017 D5, class (a)).

    Suite hygiene, admitted on the precedent D5 names by name
    (``test_fixture_git_init_declares_its_branch.py``): the subject is
    executable test code and the property is that **the suite means the same
    thing on every host**. An undeclared skip makes a host without some binary
    run a different suite, silently, and the gate's marker cannot tell the
    difference — which is the class the #478 breakage was an instance of (51
    failures plus a collection error, mid-review).

    The exemption is earned from the subject: a skip is permitted where the same
    function resolves a binary, because that resolution is what puts the binary
    in the preflight. Every other conditional-execution mechanism — an
    ``importorskip``, a platform ``skipif``, a bare ``pytest.skip("slow")`` —
    fails here **wherever it sits outside such a function**, so the change
    introducing one answers the membership question in place rather than opening
    a hole nothing measures.

    **The rule is positional, not semantic**, and the difference is measured
    rather than left to the reader: it asks *where* a skip sits, never what its
    condition tests. A platform ``skipif`` decorating a function whose own body
    resolves a binary is therefore admitted — pinned below rather than asserted,
    because a residual nothing exercises is indistinguishable from a claim that
    it cannot happen.
    """
    sites = skip_sites_from_tree()
    offenders = _offenders(sites)

    assert offenders == [], "\n".join(
        ["the suite can decline to run in a place that declares no host dependency:"]
        + [f"  {site.why()}" for site in offenders]
    )


def test_the_completion_sweep_read_a_corpus_that_has_skips_in_it() -> None:
    """The floor under the sweep above: it read real code, and that code skips.

    ``assert offenders == []`` over an empty corpus is constant-true, and so is
    a sweep over a corpus with no skip-shaped construct in it at all (#467 — any
    "nothing in the tree does X" test owes a companion asserting the tree was
    actually read). Both floors are here: a named module is in the corpus, and
    the sweep found the ``_node()`` skips that are the reason the rule exists.
    """
    sites = skip_sites_from_tree()
    origins = {site.origin for site in sites}

    assert "tests/unit/test_gate_evidence_hook_scope.py" in origins, (
        f"the sweep read no skip in a module known to carry one (it saw {sorted(origins)}) "
        f"— {_STAGE_FIRST}"
    )
    assert any(site.declares for site in sites), (
        "no skip in the whole corpus sits beside a declared binary, so the "
        "compliant branch of this rule ran zero times and the sweep above is "
        "asserting over offenders it could not classify"
    )


_HYGIENE_CASES = (
    (
        "a skip beside its declaration is compliant",
        "import shutil\nimport pytest\n"
        "\n"
        "def _node():\n"
        '    node = shutil.which("node")\n'
        "    if node is None:\n"
        '        pytest.skip("node not available")\n'
        "    return node\n",
        [],
    ),
    (
        "a skip declaring nothing is an offender",
        "import pytest\n\ndef test_slow():\n    pytest.skip('too slow today')\n",
        ["pytest.skip"],
    ),
    (
        "an importorskip is another route to the host",
        "import pytest\n\ndef test_yaml():\n    pytest.importorskip('yaml')\n",
        ["pytest.importorskip"],
    ),
    (
        "a skipif decorator is read as well as a call",
        "import sys\nimport pytest\n"
        "\n"
        "@pytest.mark.skipif(sys.platform == 'win32', reason='posix only')\n"
        "def test_posix():\n"
        "    pass\n",
        ["pytest.mark.skipif"],
    ),
    (
        "an aliased pytest does not hide a skip",
        "import pytest as pt\n\ndef test_x():\n    pt.skip('nope')\n",
        ["pt.skip"],
    ),
    (
        "a bare imported skip does not hide one either",
        "from pytest import skip\n\ndef test_x():\n    skip('nope')\n",
        ["skip"],
    ),
    (
        "a module-scope skip declares nothing by construction",
        "import pytest\n\npytest.skip('whole module', allow_module_level=True)\n",
        ["pytest.skip"],
    ),
    (
        "a sibling function's declaration does not excuse it",
        "import shutil\nimport pytest\n"
        "\n"
        "def _node():\n"
        '    return shutil.which("node")\n'
        "\n"
        "def test_x():\n"
        "    pytest.skip('nope')\n",
        ["pytest.skip"],
    ),
    (
        "a locally defined skip is not pytest's",
        "def skip(reason):\n    return reason\n\ndef test_x():\n    skip('a helper')\n",
        [],
    ),
    (
        # The residual of a positional rule, pinned rather than described: this
        # skip is conditional on the platform and not on the binary beside it,
        # and it is admitted anyway. Narrowing it would mean classifying what a
        # condition *tests*, which no AST predicate does reliably.
        "a platform skipif on a function that itself resolves is admitted",
        "import shutil\nimport sys\nimport pytest\n"
        "\n"
        "@pytest.mark.skipif(sys.platform == 'win32', reason='posix only')\n"
        "def test_posix():\n"
        '    return shutil.which("node")\n',
        [],
    ),
    (
        # The fallback that bounds :mod:`tests.unit._toolchain`'s stated
        # derivation residual, pinned catching it (#487 — an excluded case whose
        # fallback is only asserted in a comment was never run). The resolution
        # here is invisible to `declared_binaries`, so the skip beside it
        # declares nothing and the completion condition refuses it.
        "a resolution the derivation cannot see leaves its skip an offender",
        "import shutil\nimport pytest\n"
        "\n"
        "def _tool():\n"
        "    resolve = shutil.which\n"
        '    found = resolve("shellcheck")\n'
        "    if found is None:\n"
        "        pytest.skip('shellcheck not available')\n"
        "    return found\n",
        ["pytest.skip"],
    ),
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [pytest.param(src, expected, id=name) for name, src, expected in _HYGIENE_CASES],
)
def test_the_completion_condition_answers_about_its_input(
    source: str, expected: list[str]
) -> None:
    """The sweep above is born green — every skip in this tree already complies.

    Born green is the test-first law's quietest failure mode (craft.md → *Born
    green*), so the predicate is exercised here on sources whose answer differs
    from this tree's: seven shapes it must refuse and two it must not. Every
    case calls the same :func:`skip_sites` the tree-wide sweep calls, so a change
    to how production classifies a site is a change to what every control
    measures.
    """
    assert [site.spelling for site in _offenders(skip_sites(source))] == expected


# --- The derivation: which binaries the suite resolves off PATH ----------------
#
# Fed only this repo's own tests, `declared_binaries` and a hardcoded set are
# indistinguishable, so every case below has an answer that **differs** from
# this tree's (craft.md -> pin the derivation, not the derived answer; #458).
# The names are deliberately binaries nothing here resolves.

_DERIVATION_CASES = (
    (
        "the attribute spelling",
        'import shutil\n\ntool = shutil.which("shellcheck")\n',
        {"shellcheck"},
    ),
    (
        "a from-import binds the bare name",
        'from shutil import which\n\ntool = which("ripgrep")\n',
        {"ripgrep"},
    ),
    (
        "an aliased module still resolves",
        'import shutil as sh\n\ntool = sh.which("ripgrep")\n',
        {"ripgrep"},
    ),
    (
        "an aliased function still resolves",
        'from shutil import which as _w\n\ntool = _w("ripgrep")\n',
        {"ripgrep"},
    ),
    (
        "nested scopes are read, not only the module body",
        "import shutil\n"
        "\n"
        "class Fixture:\n"
        '    tool = shutil.which("ripgrep")\n'
        "\n"
        "def go():\n"
        "    try:\n"
        '        found = shutil.which("shellcheck")\n'
        "    except OSError:\n"
        "        found = None\n"
        '    return [shutil.which("delta") for _ in range(1)] + [found]\n',
        {"ripgrep", "shellcheck", "delta"},
    ),
    (
        "a spawn site is deliberately not the key",
        'import subprocess\n\nsubprocess.run(["shellcheck", "-x"], check=True)\n',
        set(),
    ),
    (
        "a locally defined which is not shutil's",
        'def which(name):\n    return name\n\ntool = which("ripgrep")\n',
        set(),
    ),
    (
        "a module resolving nothing declares nothing",
        "import shutil\n\nprint(shutil.__name__)\n",
        set(),
    ),
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [pytest.param(src, expected, id=name) for name, src, expected in _DERIVATION_CASES],
)
def test_the_derivation_answers_about_its_input(source: str, expected: set[str]) -> None:
    """The membership rule, exercised on sources whose answer is not this tree's.

    A binary enters the preflight exactly when a test **resolves** it off
    ``PATH`` at run time. The spawn-site case is the scoping claim, stated as a
    test rather than a comment: keying on what the suite spawns derives a set
    that does not contain ``node`` at all (measured — ``node`` never appears as
    a literal ``argv[0]`` anywhere in ``tests/``), which is why that framing was
    rejected.
    """
    assert declared_binaries(source) == expected


@pytest.mark.parametrize(
    ("spelling", "source"),
    [
        ("TOOL", 'import shutil\n\nTOOL = "jq"\ntool = shutil.which(TOOL)\n'),
        ("{x}", 'import shutil\n\ndef go(x):\n    return shutil.which(f"{x}")\n'),
        ("no argument", "import shutil\n\ntool = shutil.which()\n"),
    ],
    ids=["a-name", "an-f-string", "no-argument"],
)
def test_a_binary_this_derivation_cannot_name_is_a_refusal(spelling: str, source: str) -> None:
    """An unclassified member fails rather than falling through.

    craft.md -> *A guard over an enumerable dimension must fail on an
    unclassified member*, and #490: a partial parser that goes **silent** on a
    spelling it does not know is worse than one that goes red, because the
    preflight would then be held against a set with a hole in it. The message
    must name the file, the line, and the spelling — an operator who cannot see
    which call refused will widen the derivation instead of the call.
    """
    with pytest.raises(AssertionError) as raised:
        declared_binaries(source, origin="tests/unit/test_made_up.py")

    message = str(raised.value)
    assert re.search(r"tests/unit/test_made_up\.py:\d+", message), message
    assert spelling in message, message
