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
appearing on a gate pytest line — is in ``test_tiers_corpus.py``, next to the tier
vocabulary it reasons about.
"""

from __future__ import annotations

import ast
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

    Asserted as set equality rather than membership so neither stage can be
    dropped, duplicated, or have its selector hand-edited into something that
    still looks plausible while omitting a slice of the suite.
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


def _tag_sharing_modules() -> dict[str, set[str]]:
    """Every tracked test module naming :data:`SHARED_IMAGE_TAG`, to its markers."""
    sharers: dict[str, set[str]] = {}
    for path in tracked_files_under("tests"):
        if not (path.name.startswith("test_") and path.suffix == ".py"):
            continue
        source = path.read_text(encoding="utf-8")
        if SHARED_IMAGE_TAG not in source:
            continue
        sharers[path.relative_to(_REPO_ROOT).as_posix()] = _module_pytestmark_names(
            source
        )
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


def _collect_node_ids(selector: str | None) -> set[str]:
    """The node ids pytest collects for *selector* (None = the whole suite).

    A real collection in a subprocess rather than a re-derivation of the tiers in
    Python: the claim under test is about what **the gate** runs, and the gate
    runs pytest. Routing through the real collector means the answer passes
    through ``tests/conftest.py``'s ``pytest_collection_modifyitems`` — the hook
    that assigns the tier markers the gate's ``-m`` expressions select on — so a
    hook that stopped marking shrinks these sets instead of leaving the check
    agreeing with itself.
    """
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "--no-header",
        "-p",
        "no:cacheprovider",
    ]
    if selector is not None:
        command += ["-m", selector]
    result = subprocess.run(
        command,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, (
        f"collection failed for -m {selector!r} (exit {result.returncode}):\n"
        f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.lstrip().startswith(("[", "<"))
    }


def test_the_gate_stages_partition_the_whole_suite() -> None:
    """The gate runs every test exactly once, across its stages.

    **Supersedes ``test_tiers_corpus.py::test_the_gate_still_runs_the_whole_suite``**
    (#336), which banned any ``-m`` from the gate's pytest lines. That ban was a
    proxy for this property, and #358's partition would now trip it. The property
    itself is strictly stronger: the proxy would have passed a gate that quietly
    added ``--ignore=tests/integration`` or ``--deselect``, because neither is a
    ``-m``.

    Two halves, because a partition can fail in two directions: a test in **no**
    stage is silently unverified, and a test in **two** stages is double-counted
    in the coverage population the floor is measured on.
    """
    selectors = [_marker_selector(cmd) for cmd in pytest_commands()]
    assert all(selector is not None for selector in selectors), (
        f"every gate pytest stage must carry an explicit -m expression, so the "
        f"union accounts for all of them; found {selectors!r}"
    )

    whole = _collect_node_ids(None)
    assert len(whole) > 4000, (
        f"the unfiltered collection is this check's yardstick and must be the "
        f"real suite; collected {len(whole)}"
    )

    union: set[str] = set()
    for selector in selectors:
        selected = _collect_node_ids(selector)
        assert selected, f'the gate stage -m "{selector}" collects nothing'
        overlap = union & selected
        assert not overlap, (
            f'the gate\'s stages overlap: -m "{selector}" re-runs {len(overlap)} '
            f"tests another stage already ran, so the coverage floor would be "
            f"measured on a double-counted population (#358 AC-4)."
        )
        union |= selected

    missing = whole - union
    assert not missing, (
        f"the gate's stages must partition the whole suite; {len(missing)} tests "
        f"run in no stage and would be silently unverified: "
        f"{sorted(missing)[:10]} (#358)."
    )


def test_the_partition_check_would_notice_a_dropped_slice() -> None:
    """Positive control: the union check discriminates rather than always passing.

    The real gate partitions correctly, so the assertion above is an absence
    assertion — free without a control showing the check *can* fail (#183). This
    runs the same :func:`_collect_node_ids` the real check calls over a selection
    that drops a slice, and requires the result to fall short of the whole. Using
    the same function, rather than a second inline collection, is what makes a
    mutation to it visible here too (#327).
    """
    whole = _collect_node_ids(None)
    partial = _collect_node_ids(_DOCKER_MARKER)
    assert partial, "the control's own selection must be non-empty to prove anything"
    assert partial < whole, (
        "a single-slice selection must be a proper subset of the whole suite, or "
        "the union check could not tell a partition from a dropped slice"
    )


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
