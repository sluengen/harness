"""The ``layers:`` block of a target repo's CONTEXT.md — CAL-1104.

``CONTEXT.md`` lets each repo turn optional capabilities on or off in a
``layers:`` block. One of them is load-bearing for the engine: ``layers.linear``
says whether the repo is wired to a tracker at all. With it off, the verbs run
**tracker-less** — ``start`` treats its argument as an opaque run identifier,
``close`` skips the Done transition, ``reclaim`` skips the revert — so the
harness is usable in a repo that has no Linear workspace, which is the seam a
second tracker backend later plugs into.

The reader is deliberately a **regex over the raw text**, not a YAML parse — the
same choice, for the same reason, as :mod:`harness.loop_budget`'s threshold
reader: one key is not worth a YAML dependency in a file that is mostly prose
(``engineering-principles``: smallest change). It is a *separate* module from
``loop_budget`` because the concerns are separate — spend breakers are not
layers — and neither reads the other's keys.

**Why the block scoping is load-bearing.** ``linear:`` appears *twice* in a real
CONTEXT.md::

    repo:
      name: harness
      linear: CAL          # the team prefix
    layers:
      linear: true         # the switch

An unscoped ``linear:`` search matches the **team prefix** first and never sees
the switch — so a repo that plainly sets ``layers.linear: false`` would still be
read as on, and the verbs would demand a tracker the repo does not have. The
reader therefore resolves the ``layers:`` block first and matches only inside it
(pinned in ``tests/unit/test_layers.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["linear_enabled"]

#: A top-level ``layers:`` key — column 0, optionally trailed by a comment.
_LAYERS_HEADER = re.compile(r"^layers:\s*(?:#.*)?$")

#: An *indented* ``linear:`` key and its bare value, matched only within the
#: resolved block. The indent requirement is what keeps a top-level ``linear:``
#: out of the match.
_LINEAR_KEY = re.compile(r"^\s+linear:\s*(\S+)", re.MULTILINE)


def _layers_block(text: str) -> str | None:
    """Return the indented body of the ``layers:`` block, or ``None`` if absent.

    The block runs from the ``layers:`` header to the first line that is neither
    blank nor indented — a later top-level key (or a closing code fence) ends it.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if _LAYERS_HEADER.match(line):
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


def linear_enabled(repo_root: Path) -> bool:
    """Whether ``repo_root``'s CONTEXT.md leaves the Linear layer on.

    Defaults to **on** whenever the answer is not an explicit ``false``: a
    missing CONTEXT.md, a missing ``layers:`` block, a missing ``linear:`` key,
    or an unrecognised value all read as on. The default is deliberately
    conservative — a repo that has not opted out keeps today's behaviour,
    including failing fast on a missing ``LINEAR_API_KEY``, rather than silently
    degrading to a tracker-less run because a file could not be parsed.
    """
    try:
        text = (repo_root / "CONTEXT.md").read_text()
    except OSError:
        return True

    block = _layers_block(text)
    if block is None:
        return True

    match = _LINEAR_KEY.search(block)
    if match is None:
        return True
    return match.group(1).lower() != "false"
