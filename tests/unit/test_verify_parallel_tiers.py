"""#358 — the gate partitions the suite by the ``docker`` marker and parallelises the rest.

Measured on ``dev`` @ ``6e4174b`` (2026-08-07), the whole suite runs serially in
~224s, of which ``-m "unit or guard"`` is **9.1s** and ``-m integration`` is
**214.9s**. The cost is not compute — 138s CPU against 215s wall — it is ~1,933
process-spawning tests running one at a time on one of eight cores.

So the gate runs two pytest stages instead of one:

======  ====================  ==========================  ==============================
Stage   Selector              Workers                     Coverage
======  ====================  ==========================  ==============================
1       ``-m docker``         none                        ``--cov=harness``
2       ``-m "not docker"``   ``${HARNESS_TEST_WORKERS    ``--cov=harness --cov-append
                              :-auto}``                   --cov-fail-under=90``
======  ====================  ==========================  ==============================

**Why the boundary is the ``docker`` marker and not the tier.** The ticket's prose
asks for "the unit tier", but that tier is already 9 seconds — parallelising it
buys ~2%. The resource that actually races is the shared ``harness:test`` image
tag, which is what the ticket's own *Dependency* paragraph and AC-2's guard clause
name: two tests building and running one tag concurrently can run a container from
an image the other is mid-way through rewriting. Everything outside that
capability is safe to distribute, and #336's honest tiers are what make that a
checkable claim rather than a hope.

What each test here pins, against the acceptance criteria:

* **AC-1** — stage 2 carries ``-n``, its default is host-derived (``auto``), and it
  is not a fixed integer. A silent regression to ``-n 1`` must fail the gate
  rather than merely make it slow again, which is the criterion's whole point.
* **AC-2, symptom** — stage 1 carries no ``-n`` at all. "Carries no ``-n``" is one
  unambiguous predicate where "``-n 0`` or absent" would be two.
* **AC-2, cause** — every tracked test module naming the ``harness:test`` tag
  carries ``pytest.mark.docker``, so a third module cannot join the shared tag and
  silently land in the pool.

The coverage-combine wiring (AC-4) lives with the floor it protects, in
``test_verify_coverage_gate.py``; the behavioural proof that the combine preserves
the total is in ``test_coverage_combine_equivalence.py``. The union-is-the-whole-suite
invariant — the property that survives from #336's now-superseded ban on any ``-m``
appearing on a gate pytest line — is below, in
:func:`test_the_gate_stages_partition_the_whole_suite`.
"""

from __future__ import annotations

import ast
import functools
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under
from tests.unit.test_verify_coverage_gate import pytest_commands

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The Docker image tag the serialized stage exists to protect. Named once so the
#: scan and its floor cannot drift into looking for different needles.
SHARED_IMAGE_TAG = "harness:test"

#: This module, excluded from the tag scan below — it has to carry the literal in
#: order to look for it, so a tracked-tree scan finds *itself* and demands a
#: ``docker`` marker it must not have (it builds no image). Same ``_SELF``
#: exclusion the repo's other retirement guards use, e.g.
#: ``test_tiers_corpus.py``. The exclusion is kept narrow by
#: :func:`test_the_tag_sharing_scan_finds_the_modules_it_claims_to`, which
#: requires the scan to still reach the modules that really do build the tag.
_SELF = "tests/unit/test_verify_parallel_tiers.py"

#: The marker that selects the serial stage.
_DOCKER_MARKER = "docker"

#: The two modules that build into :data:`SHARED_IMAGE_TAG` today. An anchor for
#: the scan's floor, not a value the scan is allowed to assume: the assertion is
#: that the scan *finds* these, so a derivation that silently matched nothing
#: cannot pass. A third module joining the tag is expected to add itself here in
#: the same change that marks it.
_KNOWN_TAG_SHARERS = frozenset(
    {
        "tests/integration/test_docker.py",
        "tests/integration/test_serve_socket.py",
    }
)


def _marker_selector(command: str) -> str | None:
    """The ``-m`` expression on *command*, or None if it carries none.

    Parsed with :mod:`shlex` rather than a regex so the quoting is read the way
    bash reads it: ``-m "not docker"`` is one token, and a selector that lost its
    quotes would parse as a different expression here too rather than being
    silently normalised back into the one the gate intends.
    """
    tokens = shlex.split(command, comments=True)
    for index, token in enumerate(tokens):
        if token == "-m" and index + 1 < len(tokens):
            return tokens[index + 1]
    return None


def _worker_flag(command: str) -> str | None:
    """The ``-n`` value on *command*, or None if it carries none."""
    tokens = shlex.split(command, comments=True)
    for index, token in enumerate(tokens):
        if token == "-n" and index + 1 < len(tokens):
            return tokens[index + 1]
    return None


def _stage(selector: str) -> str:
    """The gate's pytest invocation whose ``-m`` expression is *selector*."""
    matches = [cmd for cmd in pytest_commands() if _marker_selector(cmd) == selector]
    assert len(matches) == 1, (
        f"scripts/verify.sh must carry exactly one pytest invocation selecting "
        f'-m "{selector}"; found {len(matches)} (#358)'
    )
    return matches[0]


def test_the_gate_runs_exactly_two_pytest_stages() -> None:
    """The partition is two invocations, selecting ``docker`` and ``not docker``.

    Asserted as set equality rather than membership, so neither stage can be
    dropped nor have its selector hand-edited into something that still looks
    plausible while omitting a slice. Set equality cannot see a *duplicated*
    stage; that is caught by :func:`_stage`'s exactly-one lookup and by
    ``test_verify_coverage_gate.py``'s two-stage count.
    """
    selectors = [_marker_selector(cmd) for cmd in pytest_commands()]
    assert set(selectors) == {_DOCKER_MARKER, f"not {_DOCKER_MARKER}"}, (
        f"scripts/verify.sh must partition the suite into exactly "
        f'-m {_DOCKER_MARKER} and -m "not {_DOCKER_MARKER}"; found selectors '
        f"{selectors!r} (#358)"
    )


def test_the_parallel_stage_derives_its_worker_count_from_the_host() -> None:
    """AC-1: stage 2 carries ``-n``, defaulting to xdist's host-derived ``auto``.

    The value must be the ``${HARNESS_TEST_WORKERS:-auto}`` parameter expansion:
    overridable for reproducing an order-dependence failure (``0`` runs in the
    controller), host-derived when unset.
    """
    workers = _worker_flag(_stage(f"not {_DOCKER_MARKER}"))
    assert workers is not None, (
        "scripts/verify.sh's parallel pytest stage must pass -n so the suite runs "
        "across the host's cores instead of one (#358 AC-1)."
    )
    assert workers == "${HARNESS_TEST_WORKERS:-auto}", (
        f"the parallel stage's worker count must default to xdist's host-derived "
        f"`auto` via ${{HARNESS_TEST_WORKERS:-auto}}; found -n {workers!r} (#358 AC-1)."
    )


def test_the_parallel_stages_worker_count_is_not_a_fixed_literal() -> None:
    """AC-1, the regression the criterion actually names.

    A gate that quietly became ``-n 1`` (or ``-n 2``) would still pass the
    "carries ``-n``" check above while running effectively serially again — the
    silent regression the criterion exists to catch. Stated as its own assertion,
    because the equality above would also be satisfied by a future respelling of
    the default that happened to be an integer.
    """
    workers = _worker_flag(_stage(f"not {_DOCKER_MARKER}"))
    assert workers is not None and not re.fullmatch(r"\d+", workers), (
        f"the parallel stage's worker count must be host-derived, not a fixed "
        f"literal: -n {workers!r} pins the pool size and would let the gate "
        f"regress to serial while still carrying -n (#358 AC-1)."
    )


def test_the_docker_stage_runs_outside_the_parallel_pool() -> None:
    """AC-2, symptom: stage 1 carries no ``-n``, so there is no pool to land in.

    Not "``-n 0`` or absent" — absence is one predicate, and a stage with no
    worker flag cannot acquire one by a scheduler's choice.
    """
    command = _stage(_DOCKER_MARKER)
    assert _worker_flag(command) is None, (
        f"the -m {_DOCKER_MARKER} stage must carry no -n: the tests sharing the "
        f"{SHARED_IMAGE_TAG} image tag race one Docker resource if any two of "
        f"them run concurrently (#358 AC-2).\n  {command.strip()}"
    )


def _module_pytestmark_names(source: str) -> set[str]:
    """Every ``pytest.mark.<name>`` in *source*'s module-level ``pytestmark``.

    Read from the AST rather than by substring so a marker named inside a
    docstring or a comment — ``test_docker.py``'s own docstring says
    "marked ``@pytest.mark.docker``" — cannot satisfy the check without the
    module actually carrying the mark.
    """
    names: set[str] = set()
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "pytestmark"
            for target in node.targets
        ):
            continue
        for attribute in ast.walk(node.value):
            if (
                isinstance(attribute, ast.Attribute)
                and isinstance(attribute.value, ast.Attribute)
                and attribute.value.attr == "mark"
            ):
                names.add(attribute.attr)
    return names


#: The module-level name the two owners give the tag. A third module can reach the
#: shared resource without ever spelling the literal — ``from
#: tests.integration.test_docker import IMAGE_TAG`` is enough — so importing the
#: constant counts as sharing the tag. Without this the scan is a spelling check
#: rather than a dependency check, and the hole it leaves is the exact failure
#: AC-2 exists to prevent.
_TAG_CONSTANT = "IMAGE_TAG"


def _imports_the_tag_constant(source: str) -> bool:
    """Whether *source* imports :data:`_TAG_CONSTANT` from anywhere.

    Read from the AST, so the name has to be genuinely imported rather than merely
    mentioned in a docstring or comment.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and any(
            alias.name == _TAG_CONSTANT for alias in node.names
        ):
            return True
    return False


def _shares_the_tag(source: str) -> bool:
    """Whether *source* reaches the shared image tag, by literal or by import."""
    return SHARED_IMAGE_TAG in source or _imports_the_tag_constant(source)


def _tag_sharing_modules() -> dict[str, set[str]]:
    """Every tracked test module reaching :data:`SHARED_IMAGE_TAG`, to its markers."""
    sharers: dict[str, set[str]] = {}
    for path in tracked_files_under("tests"):
        if not (path.name.startswith("test_") and path.suffix == ".py"):
            continue
        relpath = path.relative_to(_REPO_ROOT).as_posix()
        if relpath == _SELF:
            continue
        source = path.read_text(encoding="utf-8")
        if not _shares_the_tag(source):
            continue
        sharers[relpath] = _module_pytestmark_names(source)
    return sharers


def test_the_tag_sharing_scan_finds_the_modules_it_claims_to() -> None:
    """Non-vacuity floor for the scan below.

    An "every module that shares the tag is marked" assertion is free if the scan
    matches nothing — the shape that reads green while measuring nothing (#168).
    Anchored on the two modules known to build the tag rather than on a count,
    since a count is the drift the floor exists to absorb.
    """
    found = set(_tag_sharing_modules())
    assert found >= _KNOWN_TAG_SHARERS, (
        f"the {SHARED_IMAGE_TAG} scan must reach the modules that build the tag; "
        f"missing {sorted(_KNOWN_TAG_SHARERS - found)} — the scan is not measuring "
        f"what it claims (#358 AC-2)."
    )


def test_the_self_exclusion_is_narrow_and_still_needed() -> None:
    """The ``_SELF`` exclusion names this file, and this file really would trip.

    An exclusion is a hole in the scan, so it needs both halves: that it names
    live code, and that removing it would change the answer. The second is what
    stops a stale exclusion quietly widening — the failure mode #327's
    still-needed test was written against.

    This module names the tag but builds no image, which is exactly why it is
    exempt and why the exemption must not extend past it.
    """
    assert (_REPO_ROOT / _SELF).is_file(), (
        f"_SELF names {_SELF}, which the tree does not contain — a stale "
        f"exclusion is a hole, not a no-op"
    )
    own_source = (_REPO_ROOT / _SELF).read_text(encoding="utf-8")
    assert SHARED_IMAGE_TAG in own_source, (
        "this module no longer names the shared tag, so the _SELF exclusion is "
        "unnecessary — delete it rather than leaving the scan with a hole"
    )
    assert _DOCKER_MARKER not in _module_pytestmark_names(own_source), (
        "this module is not marked docker (it builds no image), which is why it "
        "must be excluded rather than marked"
    )
    assert _SELF not in _tag_sharing_modules(), (
        "the exclusion must actually remove this module from the scan"
    )


@pytest.mark.parametrize("module", sorted(_tag_sharing_modules()))
def test_every_tag_sharing_module_is_marked_docker(module: str) -> None:
    """AC-2, cause: sharing the tag implies running in the serial stage.

    The stage is selected by the marker, so an unmarked module that builds
    ``harness:test`` would land in the parallel pool and race the tag — the
    failure AC-2's serial stage exists to prevent. Catching it here means the
    gate fails on the module's *arrival* rather than on the flake it causes later.
    """
    assert _DOCKER_MARKER in _tag_sharing_modules()[module], (
        f"{module} names the shared {SHARED_IMAGE_TAG} image tag but carries no "
        f"module-level pytest.mark.{_DOCKER_MARKER}, so it would run in the "
        f"parallel pool and race the tag against the other builders (#358 AC-2)."
    )


def test_the_marker_scan_would_notice_an_unmarked_sharer() -> None:
    """Positive control: the predicate discriminates, rather than always passing.

    The real tree has no unmarked sharer — an absence assertion is free without a
    control that shows the check can fail. Both samples name the tag; only the
    marker differs, so this isolates the marker check rather than the tag scan.
    """
    marked = "import pytest\n\npytestmark = [pytest.mark.docker]\ntag = 'harness:test'\n"
    unmarked = "import pytest\n\npytestmark = [pytest.mark.integration]\ntag = 'harness:test'\n"
    assert SHARED_IMAGE_TAG in marked and SHARED_IMAGE_TAG in unmarked
    assert _DOCKER_MARKER in _module_pytestmark_names(marked)
    assert _DOCKER_MARKER not in _module_pytestmark_names(unmarked)


#: Tokens that change how a stage *executes* but not *which tests it selects*.
#: Everything else on the gate's command line is reproduced in the collection —
#: that is what makes this check see a narrowing spelled any way at all, not only
#: as a ``-m``. Each of these takes a separate value token, which is dropped too.
_EXECUTION_ONLY_WITH_VALUE = frozenset({"-n", "--dist", "--durations", "-p"})

#: Same, for the ``--flag=value`` spelling, plus the coverage flags.
_EXECUTION_ONLY_PREFIXES = ("--cov", "--durations=", "--dist=", "-n=")


def _collection_argv(command: str) -> list[str]:
    """*command*'s selection arguments, as argv for a ``--collect-only`` run.

    Derived from the gate's real command line rather than rebuilt from its ``-m``
    expression alone. That distinction is the whole point: a stage can be narrowed
    by ``--ignore``, ``--deselect``, ``-k``, or a positional path just as easily as
    by a marker, and a check that reads only the marker is blind to every one of
    them — it would certify a gate that runs a subset while looking like it
    partitions. Only genuinely execution-only tokens are dropped.
    """
    tokens = shlex.split(command, comments=True)
    assert "pytest" in tokens, f"not a pytest command: {command!r}"
    argv: list[str] = []
    skip_value = False
    for token in tokens[tokens.index("pytest") + 1 :]:
        if skip_value:
            skip_value = False
            continue
        if token in _EXECUTION_ONLY_WITH_VALUE:
            skip_value = True
            continue
        if token.startswith(_EXECUTION_ONLY_PREFIXES):
            continue
        argv.append(token)
    return argv


@functools.cache
def _collect_node_ids(argv: tuple[str, ...]) -> frozenset[str]:
    """The node ids pytest collects for *argv* (empty = the whole suite).

    A real collection in a subprocess rather than a re-derivation of the tiers in
    Python: the claim under test is about what **the gate** runs, and the gate
    runs pytest. Routing through the real collector means the answer passes
    through ``tests/conftest.py``'s ``pytest_collection_modifyitems`` — the hook
    that assigns the tier markers the gate's ``-m`` expressions select on — so a
    hook that stopped marking shrinks these sets instead of leaving the check
    agreeing with itself.

    Cached because a full collection is ~2s and the checks below ask for the same
    few selections more than once; keyed on the argv tuple, and nothing mutates
    the tree during a run.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *argv,
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (
        f"collection failed for {list(argv)!r} (exit {result.returncode}):\n"
        f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    return frozenset(
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.lstrip().startswith(("[", "<"))
    )


def _partition_gaps(argvs: list[list[str]]) -> tuple[set[str], set[str]]:
    """``(overlap, missing)`` for *argvs* measured against the whole suite.

    The single home for the partition computation, so that the real assertion and
    its controls exercise the *same* code. A control that re-implemented this
    comparison inline would leave a mutation to it killing nothing (#327), which
    is exactly the shape this function exists to avoid.

    ``overlap`` — node ids selected by more than one argv (double-counted in the
    coverage population). ``missing`` — node ids in the suite that no argv selects
    (silently unverified).
    """
    whole = _collect_node_ids(())
    assert len(whole) > 4000, (
        f"the unfiltered collection is this check's yardstick and must be the "
        f"real suite; collected {len(whole)}"
    )
    union: set[str] = set()
    overlap: set[str] = set()
    for argv in argvs:
        selected = _collect_node_ids(tuple(argv))
        overlap |= union & selected
        union |= selected
    return overlap, set(whole) - union


def test_the_gate_stages_partition_the_whole_suite() -> None:
    """The gate runs every test exactly once, across its stages.

    **Supersedes ``test_tiers_corpus.py::test_the_gate_still_runs_the_whole_suite``**
    (#336), which banned any ``-m`` from the gate's pytest lines. That ban was a
    proxy for this property, and #358's partition would now trip it. The property
    itself is stronger, and in the dimension that matters: it is measured from the
    gate's real argv, so it also catches a narrowing spelled ``--ignore``,
    ``--deselect``, ``-k`` or a positional path — none of which is a ``-m``, and
    every one of which the old ban would have waved through.

    Two halves, because a partition can fail in two directions: a test in **no**
    stage is silently unverified, and a test in **two** stages is double-counted
    in the coverage population the floor is measured on.
    """
    commands = pytest_commands()
    selectors = [_marker_selector(cmd) for cmd in commands]
    assert all(selector is not None for selector in selectors), (
        f"every gate pytest stage must carry an explicit -m expression, so the "
        f"union accounts for all of them; found {selectors!r}"
    )

    overlap, missing = _partition_gaps([_collection_argv(cmd) for cmd in commands])
    assert not overlap, (
        f"the gate's stages overlap: {len(overlap)} tests are run by more than one "
        f"stage, so the coverage floor would be measured on a double-counted "
        f"population: {sorted(overlap)[:10]} (#358 AC-4)."
    )
    assert not missing, (
        f"the gate's stages must partition the whole suite; {len(missing)} tests "
        f"run in no stage and would be silently unverified: "
        f"{sorted(missing)[:10]} (#358)."
    )


def test_the_partition_check_notices_a_dropped_slice() -> None:
    """Control: a stage list that omits a slice is reported as ``missing``.

    The real gate partitions correctly, so the assertion above is an absence
    assertion — free without a control showing the check *can* fail (#183). This
    calls :func:`_partition_gaps` itself, rather than re-deriving the comparison,
    so a mutation to the real computation dies here too (#327).
    """
    overlap, missing = _partition_gaps([["-m", _DOCKER_MARKER]])
    assert not overlap
    assert missing, (
        "selecting only the docker slice must leave the rest of the suite "
        "`missing`, or the check cannot tell a partition from a dropped slice"
    )


def test_the_partition_check_notices_an_overlap() -> None:
    """Control: a stage list that runs the same tests twice is reported as ``overlap``.

    Without this, nothing ever constructs an overlapping pair, and the overlap
    half of :func:`_partition_gaps` could be degraded to a constant empty set
    while every assertion stayed green.
    """
    overlap, _ = _partition_gaps(
        [["-m", _DOCKER_MARKER], ["-m", _DOCKER_MARKER], ["-m", f"not {_DOCKER_MARKER}"]]
    )
    assert overlap, (
        "running the docker slice twice must be reported as an overlap, or the "
        "double-counting half of the check measures nothing"
    )


def test_the_partition_check_notices_a_narrowing_that_is_not_a_marker() -> None:
    """Control: the check reads the gate's argv, not just its ``-m`` expression.

    This is the claim that makes the successor stronger than the #336 ban it
    replaced, so it is pinned rather than asserted in prose. The two argvs below
    partition the suite *by marker* and would satisfy any marker-only reading —
    but the second also carries ``--ignore``, so a real collection reports the
    ignored tests as ``missing``.

    The ignored path is a module of **non-docker** tests on purpose. Ignoring
    ``tests/integration/`` instead would prove nothing: every module there is
    docker-marked, so stage 1 already covers them and the union stays complete.
    A control has to drop something the other stage does not pick back up.
    """
    ignored = "tests/unit/test_tiers.py"
    assert (_REPO_ROOT / ignored).is_file(), (
        f"the control ignores {ignored}, which must exist for it to drop anything"
    )
    argvs = [
        ["-m", _DOCKER_MARKER],
        ["-m", f"not {_DOCKER_MARKER}", f"--ignore={ignored}"],
    ]
    assert [argv[1] for argv in argvs] == [
        _DOCKER_MARKER,
        f"not {_DOCKER_MARKER}",
    ], "the samples must look like a correct partition to a marker-only reading"
    _, missing = _partition_gaps(argvs)
    assert missing, (
        "a stage narrowed by --ignore must leave tests `missing`; a check that "
        "rebuilt the collection from the -m expression alone would call this a "
        "clean partition and certify a gate that runs a subset (#358)"
    )


def test_a_module_reaching_the_tag_by_import_is_still_caught() -> None:
    """Control: the scan is a dependency check, not a spelling check.

    A third module can join the shared tag without ever writing the literal — it
    imports the owner's constant instead. A scan that only matched the literal
    would leave that module in the parallel pool, racing the tag, which is the
    precise failure AC-2's serial stage exists to prevent. The sample below is a
    real bypass: it builds the image and never spells ``harness:test``.
    """
    bypass = (
        "import subprocess\n"
        "\n"
        f"from tests.integration.test_docker import {_TAG_CONSTANT}\n"
        "\n"
        f"subprocess.run(['docker', 'build', '-t', {_TAG_CONSTANT}, '.'])\n"
    )
    assert SHARED_IMAGE_TAG not in bypass, (
        "the sample must not contain the literal, or it does not distinguish the "
        "dependency check from the spelling check it replaced"
    )
    assert _shares_the_tag(bypass)
    assert _DOCKER_MARKER not in _module_pytestmark_names(bypass)

    # And the name must be genuinely imported, not merely mentioned.
    prose = f'"""This test reuses {_TAG_CONSTANT} from the docker suite."""\n'
    assert _TAG_CONSTANT in prose
    assert not _shares_the_tag(prose)


def test_a_marker_named_only_in_prose_does_not_satisfy_the_check() -> None:
    """The AST read is why the scan cannot be fooled by a docstring.

    ``tests/integration/test_docker.py``'s own docstring says the test "is marked
    ``@pytest.mark.docker``". A substring check would accept that sentence in a
    module carrying no mark at all, which is exactly the module this guard exists
    to catch.
    """
    prose_only = (
        '"""The test is marked ``@pytest.mark.docker`` and skips without a daemon."""\n'
        "import pytest\n\npytestmark = [pytest.mark.integration]\n"
        "tag = 'harness:test'\n"
    )
    assert "pytest.mark.docker" in prose_only
    assert _DOCKER_MARKER not in _module_pytestmark_names(prose_only)
