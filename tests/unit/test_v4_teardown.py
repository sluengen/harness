"""#435 — ADR 0015's teardown, asserted as absence from the git index.

`specs/decisions/0015-harness-v4-thin-verification-layer.md` retires the runtime.
This module is the mechanical form of that decision's AC1 — *the retired
subsystems are gone* — and it grows one stage at a time, because an absence
assertion can only be written honestly once the stage that deletes its subject
is the stage being built.

**Stage 1 — the deployment envelope.** The container, the developer wrapper, the
GHCR release workflow, and the operator documents that existed to run them.

**Stage 2 — the guidance surface.** The repo's own ``/harness`` command
namespace, and the `guidance-coherence` skill ADR 0015 retires by name. This
stage is where a teardown is most likely to over-reach, because the trees it
edits — ``commands/``, ``skills/``, ``.codex/`` — are almost entirely surviving
surface with a few retired entries inside them. So the did-not-delete-too-much
control names those three trees specifically, not only the repo at large.

**Stage 4 — the engine.** The ``harness/`` package itself, every test module
that imported it, and the test helpers that existed only to drive it. This
stage carries a fourth property the earlier ones did not need: *nothing living
still reaches for the package*. A module-scope ``import harness`` of a deleted
package is an ``ImportError`` at collection, so that is the difference between
a clean deletion and a gate that is red everywhere. It is asserted with an
import-**statement** regex rather than a ban on the word, because the word
survives legitimately in prose and in ``scripts/mutate.py``'s worked example —
a vocabulary ban would be satisfiable only by deleting true sentences. A regex
can be wrong in both directions, so it carries a positive and a negative
control, both run against synthetic source in ``tmp_path`` so they exercise the
*predicate* rather than agreeing with the current state of the tree.

**Stage 5 — the records.** The documents that described the runtime: ``SPEC.md``
(the verb model's design spec), the changelog and its archive with the cadence
script that measured them, and the six ``specs/features/*.md`` records of
retired subsystems. The feature specs are **moved**, not deleted, so this stage
carries a fifth property: an archived record must actually land in the archive
carrying a banner that dates its retirement. Absence alone would be satisfied by
deleting them, which is the opposite of what ADR 0015 asks for — a retired
subsystem's as-built record is the thing a later reader needs most.

Two properties, and they fail for different reasons:

* **Absence.** Every retired path resolves to nothing in the index. Judged with
  :func:`tests._gitutil.tracked_files_under`, which answers from ``git
  ls-files`` — *index membership*, the opposite polarity from a grep. A grep for
  a forbidden string passes when the tree is empty and passes again when the
  search is misspelled; an index-membership assertion is satisfiable only by the
  file actually being gone, so it cannot fail open.
* **The did-not-delete-too-much control.** A pure absence suite is green on an
  empty repository, which is the one tree it must not certify. So the surviving
  surface is asserted non-empty in the same module, and specifically the pieces
  a teardown of *this* shape is most likely to take with it: the guidance the
  repo publishes, and the promotion path ADR 0015 deliberately keeps.

The promotion floor is the load-bearing half of that control. The operator
decision behind this teardown keeps ``dev → staging → main`` **and** its nightly
automation; only the ``harness promote`` verb dies. A teardown that deleted
``scripts/promotion-step.sh`` along with the verb it used to call would satisfy
every absence assertion above and lose a live release path, so the script and
both surviving workflows are named here rather than left to be noticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._gitutil import (
    path_ever_existed,
    tracked_files_under,
    tracked_py_sources,
)
from tests.unit._prose import REPO_ROOT

# size: over the ceiling on declarative data, not on logic — roughly three
# quarters of this module is the retirement inventory itself: nine tuples naming
# every path, guard and helper ADR 0015 retires, each annotated with why it
# belongs to the stage it is listed under. That annotation is the judgement the
# teardown makes once and must then be held to, so it lives beside the entry
# rather than in a commit body. Ten short test bodies read those tuples; the
# executable surface is one regex and two helpers.


#: Stage 1's retired paths — the deployment envelope, as pathspecs.
#:
#: ``docker/`` and ``bin/`` are directories: ADR 0015 retires "the Docker
#: container, the runtime host" whole, and ``bin/harness`` is the developer
#: wrapper that fronted it. ``.dockerignore`` is a build input with no build.
#: ``release.yml`` builds and publishes the GHCR image. The three root documents
#: are operator prose for the retired loops: ``RUNBOOK.md`` ran them,
#: ``RELEASING.md`` cut the image releases, ``ONBOARDING.md`` installed the
#: wrapper and wired its credentials. ``specs/local-orchestrator-stack.md`` is a
#: spike about driving the ``harness promote`` verb locally.
_RETIRED_PATHS = (
    "docker",
    "bin",
    ".dockerignore",
    ".github/workflows/release.yml",
    "RUNBOOK.md",
    "RELEASING.md",
    "ONBOARDING.md",
    "specs/local-orchestrator-stack.md",
)

#: Stage 2's retired paths — the guidance surface, as pathspecs.
#:
#: ``commands/harness.md`` and the ``commands/harness/`` directory under it are
#: the repo's own ``/harness`` command namespace: ``run``, ``ingest`` and the two
#: unattended routines. Every one of them drives a verb ADR 0015 retires, and
#: their replacements (``/build``, ``/routine``) already ship. ``.codex/skills/
#: command-harness`` is the generated Codex adapter for the same command, which
#: ``templates/generate_codex_artifacts.py`` prunes once the command is gone.
#: ``skills/guidance-coherence`` is retired by ADR 0015 by name, taking the
#: ``/assess system`` scope with it, and its generated Codex symlink with that.
_RETIRED_GUIDANCE_PATHS = (
    "commands/harness.md",
    "commands/harness",
    "skills/guidance-coherence",
    ".codex/skills/command-harness",
    ".codex/skills/guidance-coherence",
)

#: Test modules whose **subject** is a Stage 1 retired path, deleted in the same
#: change as the thing they certify. Listed as an explicit set rather than
#: derived, because "which guard belongs to which subsystem" is a judgement the
#: teardown makes once and must then be held to: a module quietly re-added here
#: would be guarding a subject that no longer exists.
_RETIRED_TEST_MODULES = (
    "tests/unit/test_bin_wrapper.py",
    "tests/unit/test_client_install.py",
    "tests/unit/test_container_hardening.py",
    "tests/unit/test_docker_entrypoint.py",
    "tests/unit/test_guidance_update_scheduling_docs.py",
    "tests/unit/test_local_orchestrator_stack_docs.py",
    "tests/unit/test_release_docs_currency.py",
    "tests/unit/test_release_workflow.py",
    "tests/unit/test_venv_clobber_doc.py",
    "tests/unit/test_wrapper_delegates.py",
    "tests/unit/test_wrapper_image_staleness.py",
    "tests/unit/test_wrapper_source_sync.py",
    "tests/unit/test_ci_workflow_release_cadence.py",
    "tests/integration/test_docker.py",
    "tests/integration/test_docker_worktree_prune.py",
    "tests/integration/test_nightly_promotion_workspace_allowlist.py",
)

#: Test modules whose **subject** is a Stage 2 retired path or a retired verb's
#: prose. Same rule as the Stage 1 list above, and the same reason for spelling
#: it out: several of these are prose sweeps, and a prose sweep over a deleted
#: document is the fail-open shape this teardown is most exposed to.
_RETIRED_GUIDANCE_TEST_MODULES = (
    "tests/unit/test_harness_command_distributed.py",
    "tests/unit/test_routine_commands.py",
    "tests/unit/test_attendance_declaration.py",
    "tests/unit/test_close_no_rebase_rule_documented.py",
    "tests/unit/test_design_concurrency_warning.py",
    "tests/unit/test_design_verb_lifecycle_documented.py",
    "tests/unit/test_loop_stop_rule_coherence.py",
    "tests/unit/test_promotion_design.py",
    "tests/unit/test_review_engine_decision.py",
    "tests/unit/test_loop_substrate_decision.py",
    "tests/unit/test_design_engine_capability_claim.py",
)

#: Stage 4's retired paths — the engine itself, as pathspecs.
#:
#: ``harness/`` is the package ADR 0015 retires: the verb loop, the run ledger,
#: the event store, the tracker clients and the gate driver. It goes whole,
#: because no internal seam leaves the rest importable — ``cli/`` reaches into
#: ``state/``, ``events/``, ``gate.py`` and ``worktree.py`` pervasively.
#: ``tests/integration/`` goes with it: every module under it either imported
#: the package or shelled out to the container, and the one guard there whose
#: subject survives (``scripts/promotion-step.sh``) is moved into
#: ``tests/unit/`` rather than deleted.
_RETIRED_ENGINE_PATHS = (
    "harness",
    "tests/integration",
)

#: Test helpers that existed only to drive the retired package, as pathspecs.
#:
#: Each was checked against its consumers before being listed: every remaining
#: importer of these seven is itself a module this stage deletes. ``_ledger``
#: built ledger rows, ``_reclaim`` staged reclaimable runs, ``_cliutil`` drove
#: verbs through ``CliRunner``, ``_asyncutil`` ran the async verb bodies,
#: ``_capture`` and ``_stream_json`` parsed engine transcripts, and ``_tiers``
#: classified tests by the process/SQLite/CLI boundaries only the package had.
#: ``conftest.py`` goes with ``_tiers``: it existed to apply those markers, to
#: deny those boundaries, and to unset ``LINEAR_API_KEY`` for the Linear client
#: that is gone. ``tests/_gitutil.py`` is deliberately **not** here — 61 modules
#: import it and most survive, this one included.
_RETIRED_TEST_HELPERS = (
    "tests/_ledger.py",
    "tests/_reclaim.py",
    "tests/_cliutil.py",
    "tests/_asyncutil.py",
    "tests/_capture.py",
    "tests/_stream_json.py",
    "tests/_tiers.py",
    "tests/conftest.py",
)

#: Stage 5's retired paths — the records, as pathspecs.
#:
#: ``SPEC.md`` is the design spec of the verb model: its live sections describe
#: the verbs, the ledger and the CLI, and its retired sections were already
#: re-homed under ``specs/retired/``. ``CHANGELOG.md`` and
#: ``CHANGELOG-archive/`` are the released history of a released artifact; ADR
#: 0015 leaves nothing to release, and ADR 0014 already made the commit body the
#: entry. ``scripts/cadence.py`` existed solely to measure those two files'
#: growth, and was the last stage of ``scripts/verify.sh``.
_RETIRED_RECORD_PATHS = (
    "SPEC.md",
    "CHANGELOG.md",
    "CHANGELOG-archive",
    "scripts/cadence.py",
)

#: Test modules whose **subject** is a Stage 5 retired record. Same rule and the
#: same reason as the two lists above: ``test_cadence_bounds`` and
#: ``test_changelog_rotation`` measure files this stage deletes,
#: ``test_changelog_fragment_system_retired`` guards a deletion inside a
#: changelog system that no longer exists, ``test_spec_engine_extraction``
#: asserts a section layout in ``SPEC.md``, and
#: ``test_persistent_runtime_host_decision`` pins ``SPEC.md`` §16's non-goals
#: against ADR 0012 — an ADR about the runtime host ADR 0015 retires.
_RETIRED_RECORD_TEST_MODULES = (
    "tests/unit/test_cadence_bounds.py",
    "tests/unit/test_changelog_rotation.py",
    "tests/unit/test_changelog_fragment_system_retired.py",
    "tests/unit/test_spec_engine_extraction.py",
    "tests/unit/test_persistent_runtime_host_decision.py",
)

#: The as-built records of retired subsystems, as ``(old, new)`` pathspecs.
#:
#: These are the one part of this teardown that must **not** end in an empty
#: index. Each describes a subsystem ADR 0015 retires, so it cannot stay under
#: ``specs/features/`` — that tree is the *current* as-built record, and
#: ``feature_specs: true`` makes it the contract a builder reads before changing
#: behaviour. But a retired subsystem's record is exactly what a later reader
#: needs to understand why the tree looks as it does, so it moves to
#: ``specs/retired/`` rather than being deleted, which is the convention that
#: tree has carried since CAL-661.
_ARCHIVED_FEATURE_SPECS = (
    ("specs/features/verb-model.md", "specs/retired/verb-model.md"),
    ("specs/features/cli-surface.md", "specs/retired/cli-surface.md"),
    ("specs/features/run-ledger.md", "specs/retired/run-ledger.md"),
    ("specs/features/runtime-host.md", "specs/retired/runtime-host.md"),
    ("specs/features/host-platform.md", "specs/retired/host-platform.md"),
    (
        "specs/features/worktree-lifecycle.md",
        "specs/retired/worktree-lifecycle.md",
    ),
)

#: The surviving surface. Non-empty is the whole claim: these are the trees a
#: mass deletion is likeliest to over-reach into, and an empty answer for any of
#: them means the teardown took something ADR 0015 keeps.
_SURVIVING_TREES = (
    "skills",
    "hooks",
    "commands",
    "agents",
    "process",
    "templates",
    "design",
    "specs/decisions",
    "specs/features",
    "scripts",
    "scripts/mutate.py",
    "scripts/verify.sh",
    ".codex",
    # Stage 4 deletes 143 of the 275 modules under `tests/unit/` and seven of
    # the nine helpers beside it. Both floors are named because "the suite is
    # empty" and "the suite kept its shared helper" are the two ways this stage
    # over-reaches, and either would leave every absence assertion above green.
    "tests/unit",
    "tests/_gitutil.py",
)

#: The guidance Stage 2 edits *around*. Named individually because "``commands/``
#: is non-empty" is a floor one surviving file satisfies, and this stage deletes
#: files from inside three trees that are otherwise almost all survivors — the
#: over-reach it risks is a sibling, not a tree. Each entry sits next to
#: something this stage removes: ``/promote`` keeps its command and its generated
#: Codex adapter while ``/harness`` loses both; ``/build`` and ``/routine`` are
#: the replacements the retired namespace routes to, so deleting either would
#: leave the process doc pointing at nothing; ``assessment-craft`` is the
#: methodology skill that stays when ``guidance-coherence`` (its ``system``-scope
#: domain half) goes.
_SURVIVING_GUIDANCE = (
    "commands/build.md",
    "commands/routine.md",
    "commands/promote.md",
    "commands/assess.md",
    "skills/assessment-craft/SKILL.md",
    "skills/work-discovery/SKILL.md",
    ".codex/skills/command-promote/SKILL.md",
    ".codex/skills/command-build/SKILL.md",
)

#: The promotion path, named separately because it survives *by decision* and
#: for a reason that does not generalise: the verb it used to call is retired,
#: which makes deleting it the intuitive move and the wrong one.
_SURVIVING_PROMOTION = (
    "scripts/promotion-step.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly-staging-promotion.yml",
)


def _relative(paths: set[Path]) -> list[str]:
    """Tracked paths as repo-relative strings, for a legible failure."""
    return sorted(str(path.relative_to(REPO_ROOT)) for path in paths)


# ---------------------------------------------------------------------------
# AC1 — the retired subsystems are gone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pathspec", _RETIRED_PATHS)
def test_a_retired_deployment_path_is_gone_from_the_index(pathspec: str) -> None:
    """Nothing under a Stage 1 retired path is still tracked."""
    survivors = _relative(tracked_files_under(pathspec))
    assert survivors == [], (
        f"{pathspec} is retired by ADR 0015 (the container, the wrapper, the "
        f"image release, and the operator prose for the loops they ran), but "
        f"these files are still tracked: {survivors}."
    )


@pytest.mark.parametrize("module", _RETIRED_TEST_MODULES)
def test_a_guard_over_a_retired_path_is_gone_with_its_subject(module: str) -> None:
    """A guard whose subject Stage 1 deletes is deleted in the same change.

    Not tidiness. Each of these reads a file this stage removes, so leaving one
    behind is either a red gate or — worse, for the sweep-shaped ones — a guard
    that keeps passing over an empty set and reports a property nothing holds.
    """
    survivors = _relative(tracked_files_under(module))
    assert survivors == [], (
        f"{module} guards a subject Stage 1 deletes and must go with it; still "
        f"tracked: {survivors}."
    )


@pytest.mark.parametrize("pathspec", _RETIRED_GUIDANCE_PATHS)
def test_a_retired_guidance_path_is_gone_from_the_index(pathspec: str) -> None:
    """Nothing under a Stage 2 retired guidance path is still tracked."""
    survivors = _relative(tracked_files_under(pathspec))
    assert survivors == [], (
        f"{pathspec} is retired by ADR 0015 (the repo's own `/harness` command "
        f"namespace and the `guidance-coherence` skill), but these files are "
        f"still tracked: {survivors}."
    )


@pytest.mark.parametrize("module", _RETIRED_GUIDANCE_TEST_MODULES)
def test_a_guard_over_retired_guidance_is_gone_with_its_subject(module: str) -> None:
    """A guard whose subject Stage 2 deletes is deleted in the same change."""
    survivors = _relative(tracked_files_under(module))
    assert survivors == [], (
        f"{module} guards a subject Stage 2 deletes and must go with it; still "
        f"tracked: {survivors}."
    )


@pytest.mark.parametrize("pathspec", _RETIRED_ENGINE_PATHS)
def test_a_retired_engine_path_is_gone_from_the_index(pathspec: str) -> None:
    """Nothing under a Stage 4 retired engine path is still tracked."""
    survivors = _relative(tracked_files_under(pathspec))
    assert survivors == [], (
        f"{pathspec} is retired by ADR 0015 — the harness becomes deterministic "
        f"gates plus hooks, with no runtime package — but these files are still "
        f"tracked: {survivors}."
    )


@pytest.mark.parametrize("pathspec", _RETIRED_TEST_HELPERS)
def test_a_helper_that_only_drove_the_engine_is_gone(pathspec: str) -> None:
    """A test helper whose every consumer this stage deletes goes with them.

    Left behind, each would be dead code that still imports the deleted package
    at module scope — collected by nothing, but read by the next person as a
    seam that still exists.
    """
    survivors = _relative(tracked_files_under(pathspec))
    assert survivors == [], (
        f"{pathspec} existed only to drive the retired package and has no "
        f"surviving consumer; still tracked: {survivors}."
    )


@pytest.mark.parametrize("pathspec", _RETIRED_RECORD_PATHS)
def test_a_retired_record_path_is_gone_from_the_index(pathspec: str) -> None:
    """Nothing under a Stage 5 retired record path is still tracked."""
    survivors = _relative(tracked_files_under(pathspec))
    assert survivors == [], (
        f"{pathspec} is retired by ADR 0015 (the verb model's design spec, the "
        f"released history of an artifact there is no longer anything to "
        f"release, and the script that measured its growth), but these files "
        f"are still tracked: {survivors}."
    )


@pytest.mark.parametrize("module", _RETIRED_RECORD_TEST_MODULES)
def test_a_guard_over_a_retired_record_is_gone_with_its_subject(module: str) -> None:
    """A guard whose subject Stage 5 deletes is deleted in the same change."""
    survivors = _relative(tracked_files_under(module))
    assert survivors == [], (
        f"{module} guards a subject Stage 5 deletes and must go with it; still "
        f"tracked: {survivors}."
    )


def test_every_parametrized_set_in_this_module_is_populated() -> None:
    """The floor under **every** ``@parametrize`` source in this module.

    An empty ``@parametrize`` set collects zero cases and reports ``skipped``,
    which reads as green — so each list below can delete all of its own coverage
    without failing anything. This is the one case that cannot be skipped away,
    and it is unparametrized for exactly that reason.

    Every list, not just the retirement ones. Emptying ``_SURVIVING_TREES``,
    ``_SURVIVING_PROMOTION`` or ``_SURVIVING_GUIDANCE`` silently removes the
    did-not-delete-too-much control, which is the assertion that stops the rest
    of this module being satisfied by deleting the repository — the control
    needs a control.
    """
    assert len(_RETIRED_PATHS) >= 8, _RETIRED_PATHS
    assert len(_RETIRED_GUIDANCE_PATHS) >= 5, _RETIRED_GUIDANCE_PATHS
    assert len(_RETIRED_TEST_MODULES) >= 12, _RETIRED_TEST_MODULES
    assert len(_RETIRED_GUIDANCE_TEST_MODULES) >= 11, _RETIRED_GUIDANCE_TEST_MODULES
    assert len(_RETIRED_ENGINE_PATHS) >= 2, _RETIRED_ENGINE_PATHS
    assert len(_RETIRED_TEST_HELPERS) >= 8, _RETIRED_TEST_HELPERS
    assert len(_RETIRED_RECORD_PATHS) >= 4, _RETIRED_RECORD_PATHS
    assert len(_RETIRED_RECORD_TEST_MODULES) >= 5, _RETIRED_RECORD_TEST_MODULES
    assert len(_ARCHIVED_FEATURE_SPECS) >= 6, _ARCHIVED_FEATURE_SPECS
    assert len(_SURVIVING_TREES) >= 14, _SURVIVING_TREES
    assert len(_SURVIVING_PROMOTION) >= 3, _SURVIVING_PROMOTION
    assert len(_SURVIVING_GUIDANCE) >= 8, _SURVIVING_GUIDANCE
    # Count is not membership, and for the did-not-delete-too-much control the
    # difference is the whole assertion: swapping `tests/unit` and
    # `tests/_gitutil.py` out for two root documents keeps the length at 14 and
    # stops checking that the suite and its one shared helper survived at all.
    # These four are named because each is a floor no other entry implies — the
    # tests that remain, the helper 61 of them import, the gate, and the
    # mutation instrument that proves a guard can fail.
    for required in ("tests/unit", "tests/_gitutil.py", "scripts/verify.sh", "scripts/mutate.py"):
        assert required in _SURVIVING_TREES, (
            f"{required} dropped out of the did-not-delete-too-much control. "
            f"Its absence is not visible in the length above, and nothing else "
            f"here asserts that it survived."
        )


@pytest.mark.parametrize(
    "pathspec",
    (
        *_RETIRED_PATHS,
        *_RETIRED_GUIDANCE_PATHS,
        *_RETIRED_TEST_MODULES,
        *_RETIRED_GUIDANCE_TEST_MODULES,
        *_RETIRED_ENGINE_PATHS,
        *_RETIRED_TEST_HELPERS,
        *_RETIRED_RECORD_PATHS,
        *_RETIRED_RECORD_TEST_MODULES,
        *(old for old, _ in _ARCHIVED_FEATURE_SPECS),
    ),
)
def test_a_retired_path_is_one_that_really_existed(pathspec: str) -> None:
    """Every path named above was a real file, proven from git history.

    **This is the assertion that stops the absence guards failing open**, and it
    was added because mutating one of the literals showed they do. Index
    membership is the opposite polarity from a grep for a *correctly spelled*
    path — but ``tracked_files_under("dockerX")`` is also empty, so a typo, a
    rename, or a path that never existed satisfies every absence assertion above
    while measuring nothing at all. Fifteen such entries would look exactly like
    fifteen successful deletions.

    ``path_ever_existed`` answers from ``git log`` and returns ``False`` for a
    path with no commit, so a name that was never real fails here.

    The question has to be asked over the **whole history graph**, which is why
    this calls a helper of its own rather than reusing the date one. Git's
    default history simplification prunes a path created and deleted entirely on
    one side of a merge, so on a release candidate — a merge of the release
    branch and the integration branch — a module retired since the last release
    reads as "never existed". Measured on one such candidate, two of this
    module's parameters failed that way and the guard went red on a legitimate
    tree (#451). A simplified answer is a fact about the topology it was asked
    over, and this guard is asking about the path.

    The shallow-history reasoning that used to sit here as an ``except`` clause
    now lives in ``path_ever_existed``'s docstring, where it belongs: a graft
    boundary makes a *date* untrustworthy and leaves *existence* proven, which is
    a property of the question rather than of this caller.
    """
    assert path_ever_existed(pathspec), (
        f"git has no commit touching {pathspec!r}, so it never existed under that "
        f"name and its absence assertion proves nothing. Fix the spelling — an "
        f"absence guard over a path that was never real is the failure mode this "
        f"whole module is written to avoid."
    )


# ---------------------------------------------------------------------------
# AC1 — the did-not-delete-too-much control.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pathspec", _SURVIVING_TREES)
def test_a_surviving_tree_still_holds_tracked_files(pathspec: str) -> None:
    """The surface ADR 0015 keeps is still there.

    Without this, every assertion above is satisfied by deleting the repository.
    """
    assert tracked_files_under(pathspec), (
        f"{pathspec} holds no tracked file — ADR 0015 retires the runtime, not "
        f"the guidance surface and the gate the repo becomes."
    )


@pytest.mark.parametrize("pathspec", _SURVIVING_PROMOTION)
def test_the_promotion_path_survives_the_verb_it_used_to_call(pathspec: str) -> None:
    """``dev → staging → main`` and its nightly automation are kept by decision.

    ``scripts/promotion-step.sh`` drove ``harness promote start|continue|pr``;
    the verb is retired and the script is rewritten to plain git rather than
    deleted with it. Asserted here because the deletion is the intuitive move.
    """
    assert tracked_files_under(pathspec), (
        f"{pathspec} is not tracked — the `harness promote` verb is retired, "
        f"but the promotion topology and its nightly automation are kept "
        f"(ADR 0015 operator decision). Rewrite it to plain git; do not delete it."
    )


@pytest.mark.parametrize("pathspec", _SURVIVING_GUIDANCE)
def test_a_sibling_of_a_retired_guidance_path_survives(pathspec: str) -> None:
    """Stage 2 removed entries from three trees, not the trees.

    A tree-level floor (``commands`` is non-empty) is satisfied by one surviving
    file, which is not the property this stage needs: it deletes named files
    from inside trees that are otherwise entirely survivors, and the plausible
    over-reach is the neighbour — the `/promote` command alongside `/harness`,
    the generated Codex adapter alongside the generated Codex adapter, the
    methodology skill alongside its retired domain half.
    """
    assert tracked_files_under(pathspec), (
        f"{pathspec} holds no tracked file — Stage 2 retires the repo's own "
        f"`/harness` namespace and the `guidance-coherence` skill, not the "
        f"commands, skills and Codex adapters standing next to them."
    )


# ---------------------------------------------------------------------------
# AC1 — a retired subsystem's as-built record is archived, not destroyed.
# ---------------------------------------------------------------------------

#: The banner ``specs/retired/`` has carried since CAL-661: a blockquote
#: immediately under the H1, opening ``> **Superseded YYYY-MM-DD**``. The date is
#: what makes it a *dated* note (``spec-authoring``), and it is required as a
#: literal pattern rather than as free prose because "this is history" is the one
#: thing a reader must learn before reading the body.
_BANNER = re.compile(r"^>\s*\*\*Superseded\s+(\d{4}-\d{2}-\d{2})\*\*")

#: Lines scanned for the banner. A note buried mid-document would not warn a
#: reader who opens the file and reads the lede, which is the whole job.
_BANNER_SCAN_LINES = 8

#: One id per archived record, so a failure names the subsystem rather than
#: repeating the slug once per parameter.
_ARCHIVE_IDS = [Path(old).stem for old, _ in _ARCHIVED_FEATURE_SPECS]


@pytest.mark.parametrize(
    "old, new", _ARCHIVED_FEATURE_SPECS, ids=_ARCHIVE_IDS
)
def test_a_retired_subsystems_record_left_the_current_as_built_tree(
    old: str, new: str
) -> None:
    """The record is gone from ``specs/features/`` and present in the archive.

    Both halves in one case, because they are one move and the failure modes are
    each other's opposite. Absence alone is satisfied by deleting the record —
    the worst outcome available here, since a retired subsystem's as-built record
    is precisely what explains a tree full of removals. Presence alone is
    satisfied by copying it and leaving the original in place, which leaves
    ``feature_specs: true``'s contract tree asserting that a deleted subsystem is
    current behaviour.
    """
    assert _relative(tracked_files_under(old)) == [], (
        f"{old} records a subsystem ADR 0015 retires and must not stay in "
        f"specs/features/ — that tree is the *current* as-built record, and "
        f"`feature_specs: true` makes it the contract a builder reads before "
        f"changing behaviour."
    )
    assert tracked_files_under(new), (
        f"{new} is not tracked. The record moves to specs/retired/; it is not "
        f"deleted. A retired subsystem's as-built record is what explains the "
        f"shape of the tree that replaced it."
    )


@pytest.mark.parametrize(
    "old, new", _ARCHIVED_FEATURE_SPECS, ids=_ARCHIVE_IDS
)
def test_an_archived_record_says_it_is_history_and_when_it_became_history(
    old: str, new: str
) -> None:
    """Each archived record carries a dated banner citing ADR 0015.

    ``specs/retired/`` is exempt *by category* from every retirement sweep in
    this suite — that is what lets these six keep describing the verbs, the
    ledger and the container in the present tense of their own day. The
    exemption is only honest if the file says so on its face, so the banner is
    the condition of the exemption rather than a formatting preference: without
    it, the six documents most likely to be mistaken for current design are the
    six nothing checks.
    """
    text = (REPO_ROOT / new).read_text(encoding="utf-8")
    head = text.splitlines()[:_BANNER_SCAN_LINES]
    dated = [match for match in (_BANNER.match(line) for line in head) if match]
    assert dated, (
        f"{new} has no dated supersede banner in its first "
        f"{_BANNER_SCAN_LINES} lines. Prepend a blockquote under the H1: "
        f"`> **Superseded YYYY-MM-DD** — describes the <subsystem>. <what "
        f"replaced it, or that nothing did>. Kept for historical reference "
        f"only.` (the convention specs/retired/ has carried since CAL-661)."
    )
    banner = "\n".join(head)
    assert "0015" in banner, (
        f"{new}'s supersede banner must cite ADR 0015 — the decision that "
        f"retired the subsystem it describes. A date says when; only the "
        f"citation says why, and it is the reader's next hop."
    )


# ---------------------------------------------------------------------------
# AC1 — nothing living still reaches for the deleted package.
# ---------------------------------------------------------------------------

#: The trees the import sweep reads. Named as a constant and pinned below,
#: because the sweep's subject list is as much of the predicate as its regex is:
#: narrowing the call to ``tracked_py_sources("scripts")`` leaves every assertion
#: in this module green while ``tests/`` — 130-odd modules, the population that
#: actually imported the package — stops being read at all.
_IMPORT_SWEEP_ROOTS = ("scripts", "tests", "templates")

#: An ``import harness`` / ``from harness[.sub] import …`` statement, at any
#: indentation.
#:
#: The **statement**, deliberately, not the bare word. ``harness`` is this
#: repository's own name: it appears in the ADR that records the retirement, in
#: ``CONTEXT.md``, in ``process/harness.md``, and in ``scripts/mutate.py``'s
#: module docstring, which carries a worked example of a mutation entry. A ban
#: on the vocabulary would be satisfiable only by deleting true sentences, which
#: is a worse tree than the one it was meant to protect.
#:
#: A regex is a predicate that can be wrong in either direction, so it is
#: exercised by :func:`_engine_importers` — the one function the live sweep and
#: both controls below call — rather than asserted about.
_ENGINE_IMPORT = re.compile(
    r"^\s*(?:from\s+harness(?:\.[A-Za-z0-9_.]+)?\s+import\b|import\s+harness\b)",
    re.MULTILINE,
)


def _engine_importers(paths: list[Path], *, root: Path) -> list[str]:
    """Every path in ``paths`` whose source imports the retired package."""
    return sorted(
        str(path.relative_to(root))
        for path in paths
        if _ENGINE_IMPORT.search(path.read_text(encoding="utf-8"))
    )


def test_no_surviving_python_imports_the_retired_package() -> None:
    """No tracked Python source imports ``harness``.

    The consequence is not tidiness. A module-scope import of a deleted package
    raises ``ImportError`` during collection, which takes the whole suite down
    rather than failing one test — so this is the difference between a clean
    deletion and a gate that is red everywhere for a reason unrelated to the
    change under review.
    """
    assert _IMPORT_SWEEP_ROOTS == ("scripts", "tests", "templates"), (
        f"the import sweep's subject roots changed to {_IMPORT_SWEEP_ROOTS}. "
        f"Every tracked Python tree must be read; dropping one costs nothing "
        f"visible — the sweep simply stops looking there."
    )
    swept = tracked_py_sources(*_IMPORT_SWEEP_ROOTS)
    assert len(swept) >= 120, (
        f"the import sweep read only {len(swept)} Python sources — the tracked "
        f"tree carries far more, so the roots have stopped resolving"
    )
    importers = _engine_importers(swept, root=REPO_ROOT)
    assert importers == [], (
        f"these modules still import the retired `harness` package: {importers}. "
        f"ADR 0015 deletes it; remove the dependency rather than restoring the "
        f"module."
    )


def test_the_import_predicate_catches_a_real_import(tmp_path: Path) -> None:
    """Positive control: the shapes a real dependency takes are all matched.

    Without this the sweep above is green on an empty tree, on a misspelled
    pattern, and on a regex that matches nothing at all.
    """
    forms = {
        "plain.py": "import harness\n",
        "submodule.py": "import harness.cli.review as r\n",
        "from_package.py": "from harness import gate\n",
        "from_submodule.py": "from harness.cli import review\n",
        "from_deep.py": "from harness.state.store import Store\n",
        "indented.py": "def f():\n    from harness import gate\n",
        "after_prose.py": '"""A docstring."""\n\nimport harness.events\n',
    }
    for name, source in forms.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    caught = _engine_importers(sorted(tmp_path.glob("*.py")), root=tmp_path)
    assert caught == sorted(forms), (
        f"the predicate missed a real import statement: expected all of "
        f"{sorted(forms)}, caught {caught}."
    )


def test_the_import_predicate_leaves_true_prose_alone(tmp_path: Path) -> None:
    """Negative control: naming the retired package is not importing it.

    This is the half that stops the guard being "fixed" by deleting the
    sentences that record the retirement. ``scripts/mutate.py``'s docstring is
    the live case — it carries a worked example of a mutation entry, and a
    surviving example is still an example. The repo's own name, its process
    doc's filename, and a path literal must all stay legal.
    """
    legal = {
        "docstring.py": (
            '"""The harness retires its runtime (ADR 0015).\n\n'
            'A mutation entry may name a module to import as an observation:\n'
            "    observe = [\"-c\", \"import scripts.mutate as m; print(m)\"]\n"
            '"""\n'
        ),
        "prose_naming_the_package.py": (
            "# The harness package was deleted; nothing imports harness now.\n"
            "REASON = 'the harness runtime is retired'\n"
        ),
        "path_literal.py": "DOC = 'process/harness.md'\nROOT = 'harness/'\n",
        "unrelated_import.py": "from tests._gitutil import tracked_files_under\n",
    }
    for name, source in legal.items():
        (tmp_path / name).write_text(source, encoding="utf-8")

    caught = _engine_importers(sorted(tmp_path.glob("*.py")), root=tmp_path)
    assert caught == [], (
        f"the predicate flagged prose that merely names the package: {caught}. "
        f"A guard satisfiable only by deleting true sentences is worse than no "
        f"guard."
    )
