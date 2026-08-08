"""#324 — the ``changelog.d/`` fragment system is deleted, and stays deleted.

ADR 0014 makes the commit log the source of the changelog. The fragment system
that preceded it — ``scripts/changelog_fragments.py`` (``check`` / ``require`` /
``fold``), the ``changelog.d/`` directory, a per-fragment byte budget, a
fragment-count cadence bound, and #287's reserved ``no-ticket-<slug>`` stem
class — compelled a per-change artifact that restated the commit body it shipped
beside, and produced no released entry in its lifetime. It is removed whole.

Two failure modes are guarded here, and they are not the same shape:

* **Deleted** — the module, the directory and the two fragment-only test modules
  resolve to nothing in the index. Judged over the *tracked* tree rather than
  the working tree (CAL-619): a guard whose contract is "this is gone" must pass
  on a clean checkout while a stale ``__pycache__`` or an editor's cruft lingers
  on disk.
* **Unreferenced** — no living Python still imports the deleted module, and the
  gate no longer invokes it. This is the half that actually breaks a build:
  ``scripts/cadence.py`` imported ``FRAGMENT_DIRNAME`` and ``fragment_paths`` at
  module scope, so deleting the script without following its importers is an
  ``ImportError`` at collection, not a quiet leftover.

The import ban carries **both** controls, proven on synthetic source rather than
on the live tree: :func:`test_the_import_ban_catches_the_import_it_forbids`
pins that the predicate fires, and
:func:`test_prose_recording_the_retirement_stays_legal` pins that it does not
fire on a module that merely *names* the retired system in prose. A ban with
only the first control cannot tell a real import from the word appearing in a
docstring, and the docstrings recording this retirement — including this one —
are exactly where the word must stay legal.

The counterpart to "it is gone" is "the right thing survived". The fragment
system shared ``scripts/cadence.py`` with the ``CHANGELOG.md`` byte and line
ratchets, which are **not** fragment machinery and guard the root file against
silent regrowth. :func:`test_the_changelog_ratchets_survive_the_deletion` is the
did-not-delete-too-much control; the measuring half of AC-2 — that those bounds
still *fail* an append — lives in :mod:`tests.unit.test_cadence_bounds`, where
it can run the real script over a planted tree.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under, tracked_py_sources

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The name the gate's changelog-fragment stage printed. Banned from live prose
#: because a stage list that names a stage the gate does not run is a false
#: description of the canonical gate, in the files an agent session reads first.
_RETIRED_STAGE = "changelog fragment guard"

#: Trees that record what was believed or shipped at a moment, not what is
#: currently asserted. Exempt by *category* rather than by filename, so a new
#: proposal or assessment is covered the day it lands rather than the day
#: someone extends a list.
_HISTORICAL_PREFIXES = (
    "CHANGELOG.md",
    "CHANGELOG-archive/",
    "specs/decisions/",
    "specs/proposals/",
    "specs/retired/",
    "assessments/",
    "LOG.md",
)

#: The one live document still describing the deleted mechanism, deliberately.
#: ``RELEASING.md``'s changelog section is #325's subject — this ticket's Out of
#: scope reserves it, and item 4 of ADR 0014's breakdown ships "with or
#: immediately after" item 3, never before. The exemption is paired with
#: :func:`test_the_releasing_exemption_is_still_load_bearing`, which fails once
#: #325 lands, so it cannot outlive the reason for it.
_PENDING_REWRITE = "RELEASING.md"


def _live_markdown() -> list[Path]:
    """Tracked ``.md`` files that make standing claims, not historical ones."""
    live = []
    for path in sorted(tracked_files_under(".")):
        if path.suffix != ".md":
            continue
        relpath = str(path.relative_to(_REPO_ROOT))
        if relpath.startswith(_HISTORICAL_PREFIXES):
            continue
        live.append(path)
    return live

#: This module names the deleted module in order to look for it, so it is its
#: own worst offender and must never be its own subject.
_SELF = _REPO_ROOT / "tests" / "unit" / "test_changelog_fragment_system_retired.py"

#: The deleted module, as a Python module name and as a repo-relative path.
_MODULE = "changelog_fragments"
_SCRIPT = "scripts/changelog_fragments.py"
_FRAGMENT_DIR = "changelog.d"

#: The two test modules that existed only to guard the fragment system. The
#: second is listed here rather than deferred to #325 (``RELEASING.md``'s prose
#: and its doc guards) because it cannot survive this change on its own terms:
#: it imports the deleted module, asserts the gate invokes
#: ``changelog_fragments.py fold``, and requires **three** cadence bounds where
#: two remain. #325 rewrites the runbook prose those guards described.
_DELETED_TEST_MODULES = (
    "tests/unit/test_changelog_fragments.py",
    "tests/unit/test_releasing_changelog_fold.py",
)

#: An ``import changelog_fragments`` / ``from changelog_fragments import …``
#: statement, at any indentation. Deliberately matches the *statement*, not the
#: bare word: the word survives legitimately in the prose recording this
#: retirement, and a guard that banned the vocabulary would be satisfied only by
#: deleting true sentences.
_IMPORT = re.compile(
    rf"^\s*(?:from\s+{_MODULE}\s+import\b|import\s+{_MODULE}\b)",
    re.MULTILINE,
)


def _importers(paths: list[Path]) -> list[str]:
    """Every path in ``paths`` whose source imports the deleted module."""
    return [
        str(path.relative_to(_REPO_ROOT))
        for path in paths
        if path != _SELF and _IMPORT.search(path.read_text(encoding="utf-8"))
    ]


# ---------------------------------------------------------------------------
# AC-1 — the module, the directory, and the fragment-only tests are gone.
# ---------------------------------------------------------------------------


def test_the_fragment_module_is_gone_from_the_index() -> None:
    """``scripts/changelog_fragments.py`` is no longer a tracked file."""
    assert tracked_files_under(_SCRIPT) == set(), (
        f"{_SCRIPT} must be deleted — ADR 0014 derives the changelog from "
        "commits, so the fold, the presence check and the format grammar it "
        "held have no remaining caller."
    )


def test_the_fragment_directory_is_gone_from_the_index() -> None:
    """``changelog.d/`` holds no tracked file, README included."""
    survivors = sorted(
        str(path.relative_to(_REPO_ROOT)) for path in tracked_files_under(_FRAGMENT_DIR)
    )
    assert survivors == [], (
        f"{_FRAGMENT_DIR}/ must be deleted whole, but these files are still "
        f"tracked: {survivors}. The pending window is no longer a directory — "
        "a release derives its entries from the commit range."
    )


def test_the_fragment_only_test_modules_are_gone_from_the_index() -> None:
    """Both fragment-only test modules are deleted, not merely emptied."""
    survivors = [
        module for module in _DELETED_TEST_MODULES if tracked_files_under(module)
    ]
    assert survivors == [], (
        f"these modules guarded only the fragment system and must go with it: "
        f"{survivors}."
    )


# ---------------------------------------------------------------------------
# AC-1 — nothing living still reaches for it.
# ---------------------------------------------------------------------------


def test_no_living_python_imports_the_deleted_module() -> None:
    """No tracked source imports ``changelog_fragments``.

    The importer that made this load-bearing was ``scripts/cadence.py``, which
    pulled ``FRAGMENT_DIRNAME`` and ``fragment_paths`` at module scope for its
    fragment-count bound. A module-scope import of a deleted module is an
    ``ImportError`` at collection, so this is the difference between a clean
    deletion and a red gate everywhere.
    """
    importers = _importers(tracked_py_sources("harness", "tests", "scripts"))
    assert importers == [], (
        f"these modules still import {_MODULE!r}, which no longer exists: "
        f"{importers}. Remove the dependency rather than restoring the module."
    )


def test_the_import_ban_catches_the_import_it_forbids(tmp_path: Path) -> None:
    """Positive control: the predicate fires on a real import statement.

    Run over synthetic source, so the control proves the predicate rather than
    the current state of the tree — on a correctly-deleted tree the live scan
    above passes vacuously and would keep passing if the pattern never matched
    anything.
    """
    offender = tmp_path / "importer.py"
    offender.write_text(
        f"from {_MODULE} import fragment_paths\n\nPATHS = fragment_paths\n",
        encoding="utf-8",
    )
    plain = tmp_path / "plain_importer.py"
    plain.write_text(f"import {_MODULE}\n", encoding="utf-8")

    for path in (offender, plain):
        assert _IMPORT.search(path.read_text(encoding="utf-8")), (
            f"the import ban failed to match {path.name} — it would not have "
            "caught scripts/cadence.py, the importer this guard exists for."
        )


def test_prose_recording_the_retirement_stays_legal(tmp_path: Path) -> None:
    """Negative control: naming the retired system in prose is not an import.

    An as-built record, a decision record and this module all have to say what
    was deleted. A guard that banned the vocabulary could only be satisfied by
    deleting true sentences, which is a worse outcome than no guard.
    """
    historian = tmp_path / "historian.py"
    historian.write_text(
        f'"""#324 deleted {_MODULE}; {_FRAGMENT_DIR}/ went with it."""\n'
        f"\n"
        f"NOTE = 'the {_SCRIPT} fold produced no released entry'\n",
        encoding="utf-8",
    )

    assert not _IMPORT.search(historian.read_text(encoding="utf-8")), (
        "the import ban fired on prose that merely names the retired system — "
        "it must match the import statement, not the vocabulary."
    )


def test_the_gate_no_longer_invokes_the_fragment_guard() -> None:
    """``scripts/verify.sh`` runs no changelog-fragment stage.

    The gate ran ``check`` (every fragment parses) and ``require`` (this change
    carries a fragment or an exemption). Both are gone: there is no fragment to
    parse, and nothing to require.
    """
    verify = (_REPO_ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
    offending = [
        line.strip()
        for line in verify.splitlines()
        if _MODULE in line and not line.strip().startswith("#")
    ]
    assert offending == [], (
        f"scripts/verify.sh still invokes the deleted fragment guard: "
        f"{offending}."
    )


# ---------------------------------------------------------------------------
# AC-1 — no live document describes the gate as still running the stage.
# ---------------------------------------------------------------------------


def test_no_live_document_names_the_retired_gate_stage() -> None:
    """No standing prose lists ``changelog fragment guard`` as a gate stage.

    Deleting the stage from ``scripts/verify.sh`` while two stage lists still
    recite it leaves a false description of the canonical gate in the files an
    agent reads first — ``CONTEXT.md``'s ``commands.verify`` comment and
    ``specs/infrastructure.md``'s CI row both carried it, and nothing pinned
    either. It is the same defect this change's own freshness-hook assertion
    forbids: a description naming something that does not exist is worse than
    none, because it is believed.
    """
    offenders = [
        str(path.relative_to(_REPO_ROOT))
        for path in _live_markdown()
        if _RETIRED_STAGE in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"these live documents still list the retired {_RETIRED_STAGE!r} as a "
        f"stage of scripts/verify.sh: {offenders}. The gate no longer runs it."
    )


def test_no_live_document_points_a_reader_at_the_deleted_script() -> None:
    """Only ``RELEASING.md`` may still name ``scripts/changelog_fragments.py``.

    Every other live document must describe the gate and the release path as
    they are. ``RELEASING.md`` is exempt for exactly as long as #325 takes.
    """
    offenders = [
        str(path.relative_to(_REPO_ROOT))
        for path in _live_markdown()
        if str(path.relative_to(_REPO_ROOT)) != _PENDING_REWRITE
        and _SCRIPT in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"these live documents send a reader to {_SCRIPT}, which is deleted: "
        f"{offenders}. Only {_PENDING_REWRITE} may, until #325 rewrites it."
    )


def test_the_releasing_exemption_is_still_load_bearing() -> None:
    """The exemption above dies with the reason for it.

    An exemption nobody re-checks is how a guard goes quiet: once #325 rewrites
    ``RELEASING.md``, the carve-out would sit there permitting a reference that
    is no longer made, and the next document to reintroduce one could be moved
    under it without argument. So the carve-out asserts its own necessity — when
    #325 lands, this test fails and the exemption must be deleted with it.
    """
    releasing = (_REPO_ROOT / _PENDING_REWRITE).read_text(encoding="utf-8")
    assert _SCRIPT in releasing, (
        f"{_PENDING_REWRITE} no longer names {_SCRIPT}, so #325 has landed and "
        f"the {_PENDING_REWRITE} exemption in this module is now dead. Delete "
        "the exemption and the two tests that reference it."
    )


# ---------------------------------------------------------------------------
# AC-2 — the did-not-delete-too-much control.
# ---------------------------------------------------------------------------


def test_the_changelog_ratchets_survive_the_deletion() -> None:
    """``CHANGELOG.md``'s byte and line bounds outlive the fragment bound.

    They shared ``scripts/cadence.py`` with the fragment-count bound and are the
    piece most easily deleted by accident alongside it — they guard the root
    file against silent regrowth and have nothing to do with fragments. That
    they still *fail an append* is asserted where it can be measured, by
    :func:`tests.unit.test_cadence_bounds.test_an_appended_entry_breaches_the_root_ratchet`.
    """
    import sys

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import cadence

    names = {entry.name for entry in cadence.BOUNDS}
    assert {"changelog-bytes", "changelog-lines"} <= names, (
        f"the CHANGELOG.md ratchets must survive the fragment deletion, but "
        f"scripts/cadence.py now registers only {sorted(names)}."
    )
    assert "changelog-fragments" not in names, (
        "the fragment-count cadence bound must go with the directory it "
        "measures — it can only ever read 0 now."
    )
