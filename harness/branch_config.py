"""The ``branches:`` block of a target repo's CONTEXT.md — the repo's branch model.

Reads the one key an autonomous lifecycle step needs to stop hardcoding this
repo's branch names into a generic scaffold: ``branches.integration`` — the branch
feature work bases off and merges back into (``dev`` here, ``main`` or ``trunk``
elsewhere). ``start`` resolves its ``--base`` default through it, and
``worktrees cleanup --merged`` reclaims against it instead of a literal
``dev``/``main``/``master`` set (CAL-1106).

Same regex-over-raw-text, block-scoped choice as :mod:`harness.repo_config` and
:mod:`harness.layers` — one key is not worth a YAML dependency in a file that is
mostly prose (``engineering-principles``: smallest change). It is a separate
module from ``repo_config`` because the concerns are separate: ``repo_config``
answers *where does this repo's work go* (the tracker), this answers *what is this
repo's branch model*.

**Why block scoping is load-bearing** — an ``integration:`` key can appear in more
than one block of a real CONTEXT.md; only the one under ``branches:`` is the
branch name. An unscoped search would match whichever came first, so this resolves
the ``branches:`` block and reads only inside it (mirrors
:func:`harness.repo_config._repo_block`).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["integration_branch"]

#: A top-level ``branches:`` key — column 0, optionally trailed by a comment.
_BRANCHES_HEADER = re.compile(r"^branches:\s*(?:#.*)?$")


def _branches_block(text: str) -> str | None:
    """Return the indented body of the ``branches:`` block, or ``None`` if absent.

    The block runs from the ``branches:`` header to the first line that is
    neither blank nor indented — a later top-level key ends it. Mirrors
    :func:`harness.repo_config._repo_block`.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if _BRANCHES_HEADER.match(line):
            start = index + 1
            break
    if start is None:
        return None

    body: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            continue  # a blank line inside the block is not its end
        if not line[:1].isspace():
            break  # a non-indented line closes the block
        body.append(line)
    return "\n".join(body)


def _read_key(block: str, key: str) -> str | None:
    """The value of the indented ``key:`` inside ``block``, or ``None`` if absent.

    Strips a trailing ``# comment`` and surrounding quotes. Mirrors
    :func:`harness.repo_config._read_key`.
    """
    pattern = re.compile(rf"^\s+{re.escape(key)}:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(block)
    if match is None:
        return None
    value = re.sub(r"\s+#.*$", "", match.group(1)).strip()
    value = value.strip('"').strip("'")
    return value or None


def integration_branch(repo_root: Path) -> str | None:
    """The integration branch from ``branches.integration`` in CONTEXT.md, or ``None``.

    ``None`` when CONTEXT.md is absent, has no ``branches:`` block, or the block
    omits ``integration:`` — the caller supplies the fallback (a generic scaffold
    must never hard-fail because a repo has not spelled out its branch model).
    """
    try:
        text = (repo_root / "CONTEXT.md").read_text()
    except OSError:
        return None
    block = _branches_block(text)
    if block is None:
        return None
    return _read_key(block, "integration")
