"""The ``repo:`` block of a target repo's CONTEXT.md — repo identity keys.

Reads the two workspace-routing keys an autonomous lifecycle step needs to reach
the tracker without the orchestrator threading them by hand: ``repo.linear`` (the
Linear **team key**, e.g. ``CAL``) and ``repo.project`` (the Linear project the
routines pull from, e.g. ``Harness v3``). Escalation (``harness promote escalate``,
CAL-1118) is the first caller — it files a ticket into that team/project and would
otherwise need both passed on every invocation.

Same regex-over-raw-text choice as :mod:`harness.layers` and
:mod:`harness.loop_budget` — a couple of keys are not worth a YAML dependency in a
file that is mostly prose (``engineering-principles``: smallest change). It is a
separate module from ``layers`` because the concerns are separate: ``layers``
answers *is a capability on*, this answers *where does this repo's work go*.

**Why block scoping is load-bearing** — the same reason :mod:`harness.layers`
documents: ``linear:`` appears *twice* in a real CONTEXT.md, the team key under
``repo:`` and the on/off switch under ``layers:``::

    repo:
      linear: CAL          # the team key  ← this module
    layers:
      linear: true         # the switch    ← harness.layers

An unscoped ``linear:`` search is ambiguous (it matches the team key first and
never sees the switch, or vice versa), so this resolves the ``repo:`` block first
and reads only inside it.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["repo_linear_team", "repo_project"]

#: A top-level ``repo:`` key — column 0, optionally trailed by a comment.
_REPO_HEADER = re.compile(r"^repo:\s*(?:#.*)?$")


def _repo_block(text: str) -> str | None:
    """Return the indented body of the ``repo:`` block, or ``None`` if absent.

    The block runs from the ``repo:`` header to the first line that is neither
    blank nor indented — a later top-level key ends it. Mirrors
    :func:`harness.layers._layers_block`.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if _REPO_HEADER.match(line):
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

    Captures the whole value (so ``project: Harness v3`` keeps its internal space,
    which a bare ``\\S+`` grab would truncate), then strips a trailing ``# comment``
    and surrounding quotes.
    """
    pattern = re.compile(rf"^\s+{re.escape(key)}:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(block)
    if match is None:
        return None
    value = re.sub(r"\s+#.*$", "", match.group(1)).strip()
    value = value.strip('"').strip("'")
    return value or None


def _read(repo_root: Path, key: str) -> str | None:
    try:
        text = (repo_root / "CONTEXT.md").read_text()
    except OSError:
        return None
    block = _repo_block(text)
    if block is None:
        return None
    return _read_key(block, key)


def repo_linear_team(repo_root: Path) -> str | None:
    """The Linear team key from ``repo.linear`` in CONTEXT.md, or ``None``."""
    return _read(repo_root, "linear")


def repo_project(repo_root: Path) -> str | None:
    """The Linear project name from ``repo.project`` in CONTEXT.md, or ``None``."""
    return _read(repo_root, "project")
