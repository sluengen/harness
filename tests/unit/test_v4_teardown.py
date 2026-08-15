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

from pathlib import Path

import pytest

from tests._gitutil import ShallowHistoryError, last_commit_date, tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]

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
    "scripts/mutate.py",
    "scripts/verify.sh",
    ".codex",
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
    return sorted(str(path.relative_to(_REPO_ROOT)) for path in paths)


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
    assert len(_SURVIVING_TREES) >= 11, _SURVIVING_TREES
    assert len(_SURVIVING_PROMOTION) >= 3, _SURVIVING_PROMOTION
    assert len(_SURVIVING_GUIDANCE) >= 8, _SURVIVING_GUIDANCE


@pytest.mark.parametrize(
    "pathspec",
    (
        *_RETIRED_PATHS,
        *_RETIRED_GUIDANCE_PATHS,
        *_RETIRED_TEST_MODULES,
        *_RETIRED_GUIDANCE_TEST_MODULES,
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

    ``last_commit_date`` answers from ``git log`` and returns ``None`` for a path
    with no commit, so a name that was never real fails here.

    :class:`ShallowHistoryError` is caught and treated as a **pass**, which is
    the opposite of how every other caller treats it and needs saying why. That
    exception is raised only when git *did* find a commit touching the path and
    the answer resolved to a shallow clone's graft boundary — it carries that
    SHA in its message. What is untrustworthy there is the **date**, and this
    test does not read the date; it asks only whether any commit ever touched
    the path. Existence is exactly what a boundary answer proves. Re-raising
    would make the guard red on any shallow checkout for the one reason that has
    nothing to do with what it measures, and a guard that fails for an unrelated
    reason gets weakened by whoever hits it next.
    """
    try:
        dated = last_commit_date(pathspec)
    except ShallowHistoryError:
        return
    assert dated is not None, (
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
