"""CODE-1 / CODE-INSIGHT-1 (2026-06-15 code reassessment) — documented examples
of ``harness version`` output must track the real version.

``harness version`` prints ``harness <__version__>`` (``harness/cli/version.py``).
Onboarding/ops docs show that output as a sanity-check example, e.g.
``docker run --rm harness:dev version  # → harness 0.1.0``. Those examples
hardcode a version that drifts every release: at the ``0.2.1`` release both
``BOOTSTRAP.md`` and ``docker/README.md`` still showed ``harness 0.1.0`` — a doc
stating behaviour the code no longer has.

This guard turns that recurring find→fix into a suite gate: every
``harness X.Y.Z`` example in the live docs must equal the current
``harness.__version__``. Same text-structural form as ``test_retired_spec_cites``
(CAL-633) and ``test_source_file_size_justification`` (CODE-1, 2026-06-15): a
manual drift check made a permanent check.

Scope and discriminator:

* **Live docs only.** Globs git-tracked ``*.md`` under the repo root, excluding
  ``CHANGELOG.md`` and ``assessments/`` — both legitimately record *historical*
  versions (a changelog entry for ``0.1.0``, a past assessment's gate line),
  which must NOT be rewritten to the current version.
* **Keys on the ``harness X.Y.Z`` form** — the exact shape the human output
  takes (``harness {__version__}`` in ``version.py``). A bare ``0.1.0`` elsewhere
  (a dependency pin, a year) is not a version-output example and is not matched.

Acceptance criteria:

* **AC-1** — a live doc showing ``harness <old>`` where ``<old>`` != the current
  version fails the guard. Proven by
  :func:`test_doc_version_examples_match_current_version` (it failed on
  ``BOOTSTRAP.md`` and ``docker/README.md`` showing ``harness 0.1.0`` before
  this change).
* **AC-2** — on the current tree every ``harness X.Y.Z`` example equals
  ``harness.__version__``, so the guard passes.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness import __version__
from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The human form of ``harness version`` output: ``harness <semver>``.
_VERSION_EXAMPLE = re.compile(r"\bharness (\d+\.\d+\.\d+)\b")

# Docs that legitimately record *historical* versions — excluded from the gate.
_EXCLUDED_FILES = frozenset({"CHANGELOG.md"})
_EXCLUDED_DIRS = frozenset({"assessments"})


def _live_docs() -> list[Path]:
    """Git-tracked ``*.md`` files whose version examples must track the code."""
    docs: list[Path] = []
    for path in tracked_files_under("."):
        if path.suffix != ".md":
            continue
        rel = path.relative_to(_REPO_ROOT)
        if rel.name in _EXCLUDED_FILES:
            continue
        # Match an excluded dir at any depth (``assessments/`` at any level) —
        # it holds historical version records that must not track the code.
        if _EXCLUDED_DIRS.intersection(rel.parts):
            continue
        docs.append(path)
    return docs


def test_live_docs_are_discovered() -> None:
    """Sanity: the doc set is non-empty (a broken glob would vacuously pass)."""
    names = {p.name for p in _live_docs()}
    assert "BOOTSTRAP.md" in names
    assert "README.md" in {p.relative_to(_REPO_ROOT).name for p in _live_docs()}


def test_doc_version_examples_match_current_version() -> None:
    """AC-1 / AC-2: every ``harness X.Y.Z`` example equals ``__version__``."""
    offenders: list[str] = []
    for doc in _live_docs():
        text = doc.read_text(encoding="utf-8")
        for match in _VERSION_EXAMPLE.finditer(text):
            if match.group(1) != __version__:
                rel = doc.relative_to(_REPO_ROOT)
                offenders.append(
                    f"{rel}: 'harness {match.group(1)}' != current "
                    f"'harness {__version__}'"
                )
    assert not offenders, (
        "documented `harness version` examples drifted from "
        f"harness.__version__ ({__version__}):\n" + "\n".join(offenders)
    )
