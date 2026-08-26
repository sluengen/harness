"""#436 / #500 — the gate-marker contract, pinned by execution across three copies.

The marker **path** is computed in three places (``scripts/gate-marker.js``,
``hooks/push-target-guard.js``, ``hooks/gate-evidence-guard.js``) and the **tree**
in two (the writer and the Stop hook). Drift there is silent and total: a hook
that computes a slightly different path finds no marker, ever, and denies or
blocks every time — or, worse, computes a slightly different tree and finds a
marker that covers something else.

Three cheap duplicated implementations beat one shared ``hooks/lib/`` module here,
and the reason is structural rather than aesthetic:
``test_hooks_fail_open_is_loud.py`` and ``test_hooks_module_type.py`` both scan
``hooks/*.js`` **non-recursively**, so a ``lib/`` subdirectory would be a silent
hole in those guards; and a shared module's own load failure would disarm both
enforcement hooks at once. An equivalence test that *executes* all three catches
the drift those guards would miss, and adds no new failure mode of its own.

**What #500 changed, and what it cost.** ADR 0018 moved the writer from Python
into Node, so all three copies are now one language in two adjacent directories.
What this module loses is nothing it ever had: the risk it exists for is that
three separate *copies of one algorithm* drift, and the divergences it protects
against — ``realpathSync`` versus ``Path.resolve``, ``path.join`` versus ``/``, a
digits-only regex versus ``int()`` — were always copy-level rather than
language-level. What it gains is a new hazard, because "merge these three, they
are the same language now" is an obvious refactor and would turn every
equivalence here into ``assert x == x``. Two answers, both below:

* every equivalence carries an **independently constructed oracle** beside it, so
  "all three agree" cannot be satisfied by all three being wrong; and
* :func:`test_the_three_implementations_stay_textually_independent` asserts that
  no literal ``require`` in the three resolves to another, read out of the git
  index and resolved the way Node resolves it.

**Honest limit, stated because a reader will otherwise assume more.** These three
copies were not written blind and this module does not claim they were. What it
holds is that an edit to one is caught the moment it makes the three disagree,
which is the property that has value.

Acceptance criteria:

* **AC-1** — ``verify.sh`` actually invokes the writer, after the stage that can
  turn the tree red. This is the one link an executing test cannot cover (a full
  gate inside the gate is not viable), so it is a text guard over the shipped
  script. :func:`test_verify_writes_the_marker_on_its_success_path`.
* **AC-2** — the marker path agrees between all three, in a real repository,
  including from a linked worktree, and agrees with a construction this module
  performs. :func:`test_every_implementation_computes_the_same_marker_path`.
* **AC-3** — the tree oid agrees between the writer and the Stop hook, in a
  repository with a **dirty** working tree — the case where a naive
  ``HEAD^{tree}`` would silently pass an equivalence computed on a clean one.
  :func:`test_the_writer_and_the_stop_hook_compute_the_same_tree`.
* **AC-4** — the freshness bound agrees, and agrees with a hand-written table.
  Three parsers of one environment variable is exactly the shape that drifts.
  :func:`test_every_implementation_reads_the_same_freshness_bound`.
* **AC-5** — *retired with its subjects* (ADR 0017 D1): the registry-membership
  and process-doc assertions that published the mechanism died with
  ``registry.yaml`` and the process doc. The plugin ships ``hooks/`` wholesale,
  and the spine's Enforcement section is where a repo now learns the hooks exist.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import indexed_text
from tests.unit._gate_marker_runner import install_internal_gate
from tests.unit._prose import REPO_ROOT

VERIFY = REPO_ROOT / "scripts" / "verify.sh"
WRITER = REPO_ROOT / "scripts" / "gate-marker.js"
STOP_HOOK = REPO_ROOT / "hooks" / "gate-evidence-guard.js"
PUSH_HOOK = REPO_ROOT / "hooks" / "push-target-guard.js"

#: The three copies of the contract. Named rather than globbed: the advisory
#: hooks read no marker, so a glob would demand exports they have no business
#: carrying.
IMPLEMENTATIONS = (WRITER, PUSH_HOOK, STOP_HOOK)

#: Repo-relative, for the index reads. Derived from the tuple above so the two
#: cannot drift apart.
INDEXED = tuple(path.relative_to(REPO_ROOT).as_posix() for path in IMPLEMENTATIONS)

#: The bound each spelling must produce, written out by hand rather than derived
#: from any implementation. An equivalence with no out-of-family reference is
#: satisfied by three implementations that are wrong together; this table is that
#: reference. ``+60`` and `` 60 `` are here because they are exactly where the
#: retired Python parser and the two JavaScript ones disagreed — ``int()``
#: accepted both, the digits-only regex accepts neither — and no case sampled
#: either spelling while that divergence existed.
EXPECTED_BOUND = {
    "": 86400,
    "0": 86400,
    "-5": 86400,
    "soon": 86400,
    "60s": 86400,
    "+60": 86400,
    " 60 ": 86400,
    "60": 60,
    "900": 900,
}

MAX_AGE_ENV = "HARNESS_GATE_MARKER_MAX_AGE_SECONDS"
DEFAULT_MAX_AGE_SECONDS = 86400

#: A ``require`` of a string literal, in all three of JavaScript's literal
#: spellings. Both quote spellings because the subject's own files are the first
#: corpus a source predicate has to accept (#484/#487), and the backtick spelling
#: because a substitution-free template literal is an ordinary string that Node
#: resolves identically — nothing in this tree or in a formatter would stop a
#: refactor writing one. The template branch stops at any ``$``, which
#: over-excludes deliberately: it drops ``require(`./${name}`)``, computed and
#: beyond any predicate over text, and with it a template literal carrying a bare
#: ``$``, which this therefore does not read. The quoted branches keep ``$``, so
#: the narrowing is confined to the spelling that earns it.
REQUIRE = re.compile(
    r"""require\s*\(\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|`(?P<template>[^`$]*)`)\s*\)"""
)


def _specifiers(source: str) -> list[str]:
    """Every literal ``require`` specifier in ``source``, in file order.

    Exactly one of the three literal groups matches per ``require``; the others
    are ``None``. Tested for ``None`` rather than for truth, so an empty
    specifier — ``require("")`` — is still extracted and classified.
    """
    return [
        next(group for group in match.groups() if group is not None)
        for match in REQUIRE.finditer(source)
    ]


def _resolution_candidates(specifier: str, relative: str) -> set[Path]:
    """The paths Node could resolve ``specifier`` to that a subject can occupy.

    Node's CommonJS resolver tries a relative specifier ``X`` first as a file —
    ``X``, then ``X.js``, ``X.json``, ``X.node`` — and then as a directory,
    through ``X/package.json``'s ``main`` or else ``X/index.*``. Every member of
    :data:`IMPLEMENTATIONS` is a ``.js`` file, so the three arms below are the
    ones that can name one; ``X.json`` and ``X.node`` cannot equal a ``.js`` path.
    Nothing kills the ``index.js`` arm today, because no subject is named
    ``index.js`` — it is carried because it is what Node does, not because a case
    reaches it.

    That leaves one spelling deliberately unfollowed, named here rather than left
    for a reader to discover: ``require("../hooks")`` where ``hooks/package.json``
    declares a ``main`` pointing at a subject. Reaching a subject that way takes
    an edit to a manifest that today carries the module-type pin alone, and
    nothing here forbids that edit.

    Comparing the specifier as a literal path instead — the shape this replaced —
    misses every extensionless require, which is the idiomatic spelling of exactly
    the convergence refactor the caller exists to forbid.
    """
    base = (REPO_ROOT / relative).parent.joinpath(specifier).resolve()
    return {base, Path(f"{base}.js"), base / "index.js"}


def _reaches(relative: str, source: str, builtins: set[str]) -> tuple[list[str], list[str]]:
    """Classify ``source``'s literal requires as read from the file ``relative``.

    Returns ``(cross, installed)``: the specifiers that resolve to another of
    :data:`IMPLEMENTATIONS`, and the bare specifiers that are not Node builtins.
    One function, so the controls below judge the same predicate the real corpus
    is judged by rather than a restatement of it.
    """
    subjects = {path.resolve() for path in IMPLEMENTATIONS}
    cross: list[str] = []
    installed: list[str] = []
    for specifier in _specifiers(source):
        if specifier.startswith((".", "/")):
            if _resolution_candidates(specifier, relative) & subjects:
                cross.append(f"{relative} -> {specifier}")
            continue
        if specifier.removeprefix("node:") not in builtins:
            installed.append(f"{relative} -> {specifier}")
    return cross, installed


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


@pytest.fixture
def dirty_repo(tmp_path: Path) -> Path:
    """A repository with a commit *and* uncommitted work.

    Dirty on purpose: a clean worktree makes the temp-index tree and
    ``HEAD^{tree}`` the same object, so an equivalence measured there would pass
    against a Stop hook that had degraded to reading ``HEAD^{tree}`` — which is
    precisely the mutation this module has to kill.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "first")
    (root / "b.txt").write_text("uncommitted\n")
    return root


def _call(module: Path, expression: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    """Evaluate ``expression`` against ``module``'s exports, in ``cwd``.

    ``require``ing any of the three does not run it — each guards its entry point
    with ``require.main === module`` — so this reads the real shipped
    implementation rather than a restatement of it. One helper drives all three,
    which is what makes them comparable at all.
    """
    script = (
        "const h = require(process.env.HOOK_PATH);"
        f"process.stdout.write(String({expression}));"
    )
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {}), "HOOK_PATH": str(module)},
    )
    assert proc.returncode == 0, (
        f"{module.name} could not evaluate {expression!r} (rc={proc.returncode}): "
        f"{proc.stderr.strip()}"
    )
    return proc.stdout.strip()


def _oracle_marker_path(repo: Path, tree: str) -> Path:
    """Where the marker must live, constructed by this module.

    Not a re-implementation of an algorithm — it is the literal constant the whole
    design pins, spelled out once so "all three agree" cannot be satisfied by all
    three agreeing on the wrong directory.
    """
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).resolve() / "harness" / "gate" / f"{tree}.json"


# --- AC-1 ---------------------------------------------------------------------


def test_verify_writes_the_marker_on_its_success_path() -> None:
    """The one link no executing test can cover.

    Running ``verify.sh`` inside the suite would be a full gate inside the gate.
    Its marker-writing half is the part under test, and it is reached only if
    every stage above it passed — ``set -e`` is what makes "after pytest" mean
    "only when the tree is green".

    Read out of the git **index**, like the other text guard in this module: a
    tree *staging* a ``verify.sh`` without the runner delegation, while the correct file
    sits unstaged on disk, passes a working-file read at the moment
    ``git write-tree`` certifies the broken one (#482).
    """
    source = indexed_text(VERIFY.relative_to(REPO_ROOT).as_posix())
    invocation = "exec node scripts/gate-marker.js run"

    assert invocation in source, (
        "scripts/verify.sh does not delegate to the gate-marker runner, so a green "
        "gate leaves no evidence and both enforcement hooks refuse everything "
        f"(or, if they fall open, enforce nothing). Add `{invocation}` to the "
        "success path."
    )
    assert source.index(invocation) < source.index("pytest -n"), (
        "the public gate must delegate before it enters the internal stages; the "
        "runner, not this shell path, owns successful marker emission."
    )


# --- AC-2 ---------------------------------------------------------------------


@pytest.mark.parametrize("module", IMPLEMENTATIONS, ids=lambda p: p.name)
def test_every_implementation_computes_the_same_marker_path(
    module: Path, dirty_repo: Path
) -> None:
    """A copy that computes a different path finds no marker, ever.

    Held against a construction this module performs rather than against one of
    the three, because with the writer no longer in another language there is no
    out-of-family reference left inside the set.
    """
    tree = "0" * 40

    answer = _call(module, f'h.markerPath("{tree}", process.cwd())', dirty_repo)

    assert answer == str(_oracle_marker_path(dirty_repo, tree))


@pytest.mark.parametrize("module", IMPLEMENTATIONS, ids=lambda p: p.name)
def test_the_marker_path_agrees_from_a_linked_worktree(
    module: Path, dirty_repo: Path, tmp_path: Path
) -> None:
    """The gate may run in a detached gate worktree while the claim is made in the
    build worktree. All three resolve the *common* directory, so all three find
    the same marker — the property that makes that workflow safe rather than
    lucky."""
    linked = tmp_path / "linked"
    _git(dirty_repo, "worktree", "add", "-q", "--detach", str(linked))
    tree = "0" * 40

    answer = _call(module, f'h.markerPath("{tree}", process.cwd())', linked)

    assert answer == str(_oracle_marker_path(dirty_repo, tree))


# --- AC-3 ---------------------------------------------------------------------


def test_the_writer_and_the_stop_hook_compute_the_same_tree(dirty_repo: Path) -> None:
    """The equivalence that carries the most weight.

    The Stop hook's whole value over "did someone run a gate lately" is that it
    reads the tree *including uncommitted work*. If it drifted to ``HEAD^{tree}``
    it would still find markers, still allow, and silently stop distinguishing a
    verified tree from one edited afterwards.

    No constructed oracle here, deliberately: computing a temp-index tree in the
    assertion would be re-implementing the arithmetic under test. The floor below
    is what stands in for one — it proves the fixture is dirty, so the
    equivalence cannot be satisfied by two implementations that both degraded to
    ``HEAD^{tree}``.
    """
    from_writer = _call(WRITER, "h.currentTree(process.cwd())", dirty_repo)
    from_hook = _call(STOP_HOOK, "h.currentTree(process.cwd())", dirty_repo)

    assert from_hook == from_writer
    assert from_hook != _git(dirty_repo, "rev-parse", "HEAD^{tree}"), (
        "the fixture is not dirty, so this equivalence would also hold for an "
        "implementation that merely read HEAD^{tree} — the fixture is wrong"
    )


@pytest.mark.parametrize("module", (WRITER, STOP_HOOK), ids=lambda p: p.name)
def test_computing_the_tree_leaves_the_index_alone(module: Path, dirty_repo: Path) -> None:
    """Both compute a tree on paths that run constantly — the Stop hook on every
    candidate stop, the writer on every gate run. Doing that in the real index
    would stage the session's work behind its back."""
    before = _git(dirty_repo, "status", "--porcelain")
    assert before, "the fixture is clean, so this comparison measures nothing"

    _call(module, "h.currentTree(process.cwd())", dirty_repo)

    assert _git(dirty_repo, "status", "--porcelain") == before


# --- AC-4 ---------------------------------------------------------------------


@pytest.mark.parametrize("module", IMPLEMENTATIONS, ids=lambda p: p.name)
@pytest.mark.parametrize("value", sorted(EXPECTED_BOUND))
def test_every_implementation_reads_the_same_freshness_bound(
    module: Path, value: str, dirty_repo: Path
) -> None:
    """Three parsers of one environment variable is the shape that drifts.

    The degenerate values are the point: an unusable bound must read as *unset* in
    all three, because "never fresh" wedges every session and "always fresh"
    disarms the bound. Each answer is held against
    :data:`EXPECTED_BOUND` — a hand-written table — rather than against a fourth
    call to one of the three.
    """
    answer = _call(module, "h.maxAgeSeconds()", dirty_repo, env={MAX_AGE_ENV: value})

    assert int(answer) == EXPECTED_BOUND[value]


def test_the_expected_bounds_are_not_one_constant() -> None:
    """The floor under the table above.

    A table whose every entry is the default would be satisfied by an
    implementation that ignored the variable entirely, and every case would still
    pass. Membership rather than cardinality, so growing the table does not
    require re-deriving a number.
    """
    assert DEFAULT_MAX_AGE_SECONDS in set(EXPECTED_BOUND.values())
    assert {value for value in EXPECTED_BOUND.values() if value != DEFAULT_MAX_AGE_SECONDS}, (
        "every expected bound is the default, so this table cannot tell a parser "
        "that reads the variable from one that ignores it"
    )


@pytest.mark.parametrize("module", IMPLEMENTATIONS, ids=lambda p: p.name)
def test_the_unset_freshness_bound_agrees(module: Path, dirty_repo: Path) -> None:
    """The default path, exercised with the variable genuinely absent rather than
    set to the empty string — a distinction ``process.env`` makes and the
    parametrized case above cannot express."""
    env = {key: value for key, value in os.environ.items() if key != MAX_AGE_ENV}
    script = (
        "const h = require(process.env.HOOK_PATH);"
        "process.stdout.write(String(h.maxAgeSeconds()));"
    )
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=dirty_repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**env, "HOOK_PATH": str(module)},
    )

    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip()) == DEFAULT_MAX_AGE_SECONDS


# --- the marker the readers read is the one the writer wrote ------------------


@pytest.mark.parametrize("module", (PUSH_HOOK, STOP_HOOK), ids=lambda p: p.name)
def test_a_reader_finds_the_marker_the_production_writer_produced(
    module: Path, dirty_repo: Path
) -> None:
    """The anti-vacuity spine of this whole change, stated once here.

    Every allow-path test in the two hook suites produces its marker by running
    ``node scripts/gate-marker.js run`` — the production runner — never by
    hand-authoring a file. This test is the reason that works: the path the writer
    chose and the path the reader looks in are the same string, measured rather
    than assumed.
    """
    install_internal_gate(dirty_repo)
    proc = subprocess.run(
        [_node(), str(WRITER), "run"],
        cwd=dirty_repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    tree = _call(STOP_HOOK, "h.currentTree(process.cwd())", dirty_repo)
    marker = _call(module, f'h.markerPath("{tree}", process.cwd())', dirty_repo)

    assert Path(marker).exists(), (
        f"{module.name} looks for the marker at {marker}, which the production "
        f"writer did not create. It wrote: {proc.stdout.strip()!r}"
    )
    assert json.loads(Path(marker).read_text())["tree"] == tree


# --- the floor that stops this module becoming a tautology --------------------


def _builtin_modules() -> set[str]:
    """Node's own list of built-in modules, asked of Node rather than restated.

    A hand-listed set is an allowlist with both a stale and an admitting
    direction; ``module.builtinModules`` is the runtime's own answer and moves
    with it.
    """
    proc = subprocess.run(
        [_node(), "-e", "process.stdout.write(require('module').builtinModules.join(','))"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return {name for name in proc.stdout.split(",") if name}


def test_the_three_implementations_stay_textually_independent() -> None:
    """No literal ``require`` in the three resolves to another, or to a package.

    Two hazards in one assertion, both created by #500. The convergence hazard:
    with all three in one language, ``require``ing a shared copy is an obvious
    refactor, and it would turn every equivalence above into ``assert x == x``
    while leaving this module green. The dependency hazard: the writer is a gate
    precondition, so a package it needed would be a gate that can fail for reasons
    unrelated to the tree — AC-2's "without consumer-installed packages".

    Read out of the git **index**, because the subject is what a fresh clone and a
    hydrating consumer receive; a guard over the on-disk file passes on the
    machine that wrote it (#484).

    The rule is *not* "no relative require": ``hooks/push-target-guard.js``
    legitimately requires ``./git-push-guard.js``, its shell parser, and a
    predicate its own subject already refutes is a defect rather than strictness
    (#484/#487). The rule is that no relative require **resolves** to another of
    the three — through the resolver arms :func:`_resolution_candidates` carries,
    because ``require("../hooks/push-target-guard")`` names that file exactly as
    the suffixed spelling does and a literal-path comparison sees only one of
    them.

    What it does not cover, stated so no reader takes it for more: only literal
    specifiers, so a computed ``require(name)`` escapes, as does a template
    literal carrying a bare ``$``; only ``require``, so a dynamic ``import()``
    escapes; and, of the resolver, everything but the arms
    :func:`_resolution_candidates` names. The convergence refactor this exists to
    catch is written as a plain literal, which is why the residue is worth
    naming rather than chasing.

    Floored on both sides (#467/#486): the corpus must be all three files, and
    each must yield at least one ``require``, so a broken extractor cannot report
    "no cross-requires" over nothing. Neither half of the predicate fires
    positively here — a tree with a cross-require, or with a dependency, is the
    failure — so each half's killers live elsewhere: the cross half's in
    :func:`test_the_independence_predicate_catches_each_cross_require_spelling`,
    the dependency half's in
    :func:`test_the_independence_predicate_reports_an_installed_package`.
    """
    builtins = _builtin_modules()
    assert builtins, "Node reported no built-in modules, so the membership test is vacuous"

    cross: list[str] = []
    installed: list[str] = []
    for relative in INDEXED:
        source = indexed_text(relative)
        assert _specifiers(source), (
            f"no require(<literal>) was found in {relative}, so this guard read "
            "nothing there — the extractor, not the tree, is what changed"
        )
        found_cross, found_installed = _reaches(relative, source, builtins)
        cross += found_cross
        installed += found_installed

    assert cross == [], (
        "one copy of the gate-marker contract now requires another, which makes "
        f"every equivalence in this module true by construction: {cross}"
    )
    assert installed == [], (
        "these files require something outside Node's standard library, so the "
        f"gate now depends on an install step to run at all: {installed}"
    )


#: One cross-require per row, as ``(reading file, specifier, quote character)``.
#: Every specifier here was resolved with ``require.resolve`` from the reading
#: file's own directory and landed on another of the three, so every row must be
#: reported. Rows exist per spelling rather than per subject: a literal-path
#: comparison against the subjects' ``.js`` names passes the extensionless rows,
#: which is the defect this table exists for.
CROSS_SPELLINGS = (
    ("scripts/gate-marker.js", "../hooks/push-target-guard.js", '"'),
    ("scripts/gate-marker.js", "../hooks/push-target-guard", '"'),
    ("scripts/gate-marker.js", "../hooks/gate-evidence-guard", "'"),
    ("scripts/gate-marker.js", "../hooks/gate-evidence-guard", "`"),
    ("hooks/push-target-guard.js", "../scripts/gate-marker", '"'),
    ("hooks/gate-evidence-guard.js", "./push-target-guard", '"'),
)


@pytest.mark.parametrize(("relative", "specifier", "quote"), CROSS_SPELLINGS)
def test_the_independence_predicate_catches_each_cross_require_spelling(
    relative: str, specifier: str, quote: str
) -> None:
    """The killers for the predicate above, one per spelling.

    The real corpus carries no cross-require — it must not — so nothing in
    :func:`test_the_three_implementations_stay_textually_independent` makes the
    **cross** half of its predicate fire, and a predicate that never fires reads
    exactly like a tree that never offends. (Its dependency half is in the same
    position, and :func:`test_the_independence_predicate_reports_an_installed_package`
    is where that one fires.) These rows feed the same
    :func:`_reaches` the real corpus is judged by, so they measure the shipped
    predicate rather than a restatement of it.

    Each row asserts the entry names **its own** specifier, not merely that
    something was reported: a shared message would let one row's kill stand in
    for another's (#489).
    """
    source = f"const shared = require({quote}{specifier}{quote});\n"

    cross, installed = _reaches(relative, source, _builtin_modules())

    assert cross == [f"{relative} -> {specifier}"], (
        f"require({quote}{specifier}{quote}) in {relative} resolves to another "
        "copy of the contract and was not reported"
    )
    assert installed == [], (
        f"a relative specifier was classified as an installed package: {installed}"
    )


def test_the_independence_predicate_reports_an_installed_package() -> None:
    """The killer for the dependency half, which no row above reaches.

    Every :data:`CROSS_SPELLINGS` row asserts ``installed == []``, and so does the
    real corpus, so nothing else in this module makes that half fire: an
    extractor or a membership test that had stopped classifying anything would
    report "no consumer-installed packages" having judged nothing, and read
    exactly like a tree that carries none (craft.md → *A positive control must
    exercise the predicate, not re-implement it*). Fed to the same
    :func:`_reaches` the real corpus is judged by, for the same reason the rows
    above are.

    Two samples, each with its own message (#489): a bare specifier Node has no
    builtin for must be reported, and a builtin must not — without the second, a
    predicate that reported every bare specifier would pass here while condemning
    the three files' own ``node:`` requires. ``cross`` stays empty in both, so the
    two halves cannot stand in for each other.
    """
    relative = INDEXED[0]
    builtins = _builtin_modules()

    cross, installed = _reaches(relative, 'const _ = require("lodash");\n', builtins)

    assert installed == [f"{relative} -> lodash"], (
        "a bare specifier that is not a Node builtin was not reported as a "
        f"consumer-installed package: {installed}"
    )
    assert cross == [], f"a bare specifier was classified as a cross-require: {cross}"

    cross, installed = _reaches(relative, 'const fs = require("node:fs");\n', builtins)

    assert installed == [], f"a Node builtin was reported as an installed package: {installed}"
    assert cross == [], f"a builtin specifier was classified as a cross-require: {cross}"
