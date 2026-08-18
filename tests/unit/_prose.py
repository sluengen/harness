"""The repository root, and the one shared prose reader the guard suite still needs.

Before v5 this was the neutral home (#467) for the slicers and anchored readers
the prose-guard suite shared — sentence splitters, section slicers, registry
readers. ADR 0017 D5 deleted that suite with its subjects, and the chunk-4
audit slimmed this module to what the surviving guards import: the resolved
repository root, and the proposal-status reader the accepted-proposal dead-path
guard anchors on. A helper with no importer left is dead code in a test tree
exactly as it would be anywhere else.

``REPO_ROOT`` is the **resolved** form, deliberately: compared against a
git-printed path, an unresolved root is a latent constant-true or
constant-false on any checkout reached through a symlink, and nothing at the
comparison says which.
"""

from __future__ import annotations

import re
from pathlib import Path

#: ``tests/unit/_prose.py`` → ``parents[2]`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parents[2]

PROPOSAL_STATUS = re.compile(r"^status:\s*(?P<status>[a-z][a-z-]*)\s*(?:#.*)?$", re.MULTILINE)


def proposal_status(text: str) -> str:
    """The ``status:`` a proposal's frontmatter declares.

    Raises on a proposal with no parseable status: a proposal that declares
    nothing must not read as a proposal that declares something valid.
    """
    match = PROPOSAL_STATUS.search(text)
    if match is None:
        raise AssertionError("no parseable 'status:' line in this proposal's frontmatter")
    return match.group("status")
