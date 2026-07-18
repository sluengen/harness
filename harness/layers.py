"""The tracker switch of a target repo's CONTEXT.md — CAL-1104, CAL-1164.

Whether a repo is wired to a tracker at all is load-bearing for the engine. With
it off, the verbs run **tracker-less** — ``start`` treats its argument as an
opaque run identifier, ``close`` skips the Done transition, ``reclaim`` skips the
revert — so the harness is usable in a repo that has no Linear workspace, which
is the seam a second tracker backend later plugs into.

**The single source of truth is ``tracker:``** (CAL-1164): a top-level key whose
value is the backend — ``linear``, ``github``, or ``none``. It replaces the
CAL-1104 ``layers.linear`` switch, whose name *collided* with the ``repo.linear``
address (``linear:`` appeared twice in a real CONTEXT.md) and whose on/off state
was derivable from — yet unenforced against — that address. ``tracker:`` carries
the on/off-plus-backend fact in one place, so no second boolean can contradict
the address.

**Back-compat.** A repo not yet migrated has no ``tracker:`` key; the reader then
falls back to ``layers.linear`` (``false`` → ``none``, otherwise → ``linear``),
so existing repos keep working. This fallback still resolves the ``layers:``
block before matching ``linear:``, because the CAL-1104 trap survives there: an
unscoped ``linear:`` search matches the **team prefix** (``repo.linear``) first
and never sees the switch (pinned in ``tests/unit/test_layers.py``).

The reader is deliberately a **regex over the raw text**, not a YAML parse — the
same choice, for the same reason, as :mod:`harness.loop_budget`'s threshold
reader: a key or two is not worth a YAML dependency in a file that is mostly
prose (``engineering-principles``: smallest change). It is a *separate* module
from ``loop_budget`` because the concerns are separate — spend breakers are not
the tracker switch — and neither reads the other's keys.

**Coherence.** :func:`tracker_config_error` rejects an address/switch that
contradict — ``tracker: linear`` with no ``repo.linear`` address, ``tracker:
none`` with a dangling address, or a lingering ``layers.linear`` that disagrees
with ``tracker:``. ``start`` runs it as a fail-fast guard (pinned in
``tests/unit/test_tracker.py``).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["linear_enabled", "tracker", "tracker_config_error"]

#: Recognised backends. An unrecognised value reads as ``linear`` (conservative
#: on), the same way an unrecognised ``layers.linear`` value did.
_BACKENDS = ("linear", "github", "none")

#: A top-level ``tracker:`` key — column 0, its bare value, optional comment.
_TRACKER_KEY = re.compile(r"^tracker:\s*(\S+)", re.MULTILINE)

#: A top-level block header — column 0, optionally trailed by a comment.
_LAYERS_HEADER = re.compile(r"^layers:\s*(?:#.*)?$")
_REPO_HEADER = re.compile(r"^repo:\s*(?:#.*)?$")

#: An *indented* ``linear:`` key and its bare value, matched only within a
#: resolved block. The indent requirement is what keeps a top-level ``linear:``
#: out of the match.
_LINEAR_KEY = re.compile(r"^\s+linear:\s*(\S+)", re.MULTILINE)


def _block(text: str, header: re.Pattern[str]) -> str | None:
    """Return the indented body of the ``header`` block, or ``None`` if absent.

    The block runs from the header line to the first line that is neither blank
    nor indented — a later top-level key (or a closing code fence) ends it.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if header.match(line):
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


def _read_context(repo_root: Path) -> str | None:
    try:
        return (repo_root / "CONTEXT.md").read_text()
    except OSError:
        return None


def _layers_linear(text: str) -> str | None:
    """The raw ``layers.linear`` value, or ``None`` if the key is absent."""
    block = _block(text, _LAYERS_HEADER)
    if block is None:
        return None
    match = _LINEAR_KEY.search(block)
    return match.group(1) if match else None


def _repo_linear(text: str) -> str | None:
    """The raw ``repo.linear`` address, or ``None`` if the key is absent."""
    block = _block(text, _REPO_HEADER)
    if block is None:
        return None
    match = _LINEAR_KEY.search(block)
    return match.group(1) if match else None


def _tracker_from_text(text: str) -> str:
    """Resolve the backend from raw CONTEXT.md text (the shared reader core)."""
    match = _TRACKER_KEY.search(text)
    if match is not None:
        value = match.group(1).lower()
        return value if value in _BACKENDS else "linear"

    # Back-compat: no ``tracker:`` key → fall back to ``layers.linear``.
    layers = _layers_linear(text)
    if layers is not None and layers.lower() == "false":
        return "none"
    return "linear"


def tracker(repo_root: Path) -> str:
    """Resolve ``repo_root``'s tracker backend: ``linear``, ``github``, or ``none``.

    The single source of truth is a top-level ``tracker:`` key. When it is
    absent, the reader falls back to ``layers.linear`` (``false`` → ``none``,
    otherwise → ``linear``) so an un-migrated repo keeps working. Defaults to
    ``linear`` whenever the answer is not an explicit off: a missing CONTEXT.md,
    a missing ``tracker:`` key with no ``layers.linear``, or an unrecognised
    value all read as ``linear``. The default is deliberately conservative — a
    repo that has not opted out keeps today's behaviour, including failing fast
    on a missing ``LINEAR_API_KEY``, rather than silently degrading to a
    tracker-less run because a file could not be parsed.
    """
    text = _read_context(repo_root)
    if text is None:
        return "linear"
    return _tracker_from_text(text)


def linear_enabled(repo_root: Path) -> bool:
    """Whether the Linear tracker backend is active (``tracker == "linear"``)."""
    return tracker(repo_root) == "linear"


def tracker_config_error(repo_root: Path) -> str | None:
    """Return a message if the tracker switch and the address contradict, else ``None``.

    The switch (``tracker:``, or its ``layers.linear`` back-compat equivalent) and
    the ``repo.linear`` address are two facts about the same thing; this rejects
    the states where they disagree:

    * ``tracker: linear`` with no ``repo.linear`` address — the Linear backend has
      nothing to talk to.
    * ``tracker: none`` with a real ``repo.linear`` address still set — a dangling
      address contradicting the off switch.
    * a lingering ``layers.linear`` that disagrees with an explicit ``tracker:`` —
      the exact second-source-of-truth this ticket removes.

    ``github`` is not checked here: its backend and config are out of scope
    (CAL-1105). A missing CONTEXT.md is not an inconsistency — it reads as the
    conservative default and has nothing to contradict.
    """
    text = _read_context(repo_root)
    if text is None:
        return None

    backend = _tracker_from_text(text)
    address = _repo_linear(text)
    has_address = address is not None and address.lower() != "none"

    if backend == "linear" and not has_address:
        return (
            "tracker: linear requires a repo.linear address, but repo.linear is "
            "unset or 'none' — set the address, or set tracker: none"
        )
    if backend == "none" and has_address:
        return (
            f"tracker: none contradicts repo.linear: {address} — remove the "
            "address (set repo.linear: none), or set tracker: linear"
        )

    # A second, derivable boolean that disagrees with an explicit tracker: is the
    # very state this ticket removes. Only flag it when tracker: is explicit —
    # otherwise layers.linear *is* the source (the back-compat path above).
    if _TRACKER_KEY.search(text) is not None:
        layers = _layers_linear(text)
        if layers is not None:
            layers_on = layers.lower() != "false"
            if layers_on != (backend != "none"):
                return (
                    f"tracker: {backend} contradicts layers.linear: {layers} — "
                    "remove layers.linear; tracker: is the single source of truth"
                )

    return None
