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
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "GitHubSettings",
    "github_settings",
    "linear_enabled",
    "tracker",
    "tracker_config_error",
]

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

#: The ``github:`` config block header (column 0) — the GitHub backend's
#: backend-specific config, read only when ``tracker: github`` (CAL-1105), the
#: same way ``repo.linear`` is Linear-only config.
_GITHUB_HEADER = re.compile(r"^github:\s*(?:#.*)?$")

#: Indented scalar keys inside the ``github:`` block. ``repo`` and ``project``
#: are bare tokens (``owner/name`` and ``owner/number``); ``status_field`` may
#: contain spaces (e.g. ``Harness Status``) so it captures the rest of the line
#: and is stripped of surrounding quotes by :func:`github_settings`.
_GH_REPO_KEY = re.compile(r"^\s+repo:\s*(\S+)", re.MULTILINE)
_GH_PROJECT_KEY = re.compile(r"^\s+project:\s*(\S+)", re.MULTILINE)
_GH_STATUS_FIELD_KEY = re.compile(r"^\s+status_field:\s*(.+?)\s*$", re.MULTILINE)

#: The default single-select field the harness drives when ``status_field`` is
#: not configured — GitHub's built-in Projects v2 status field name.
_DEFAULT_STATUS_FIELD = "Status"


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


@dataclass(frozen=True)
class GitHubSettings:
    """The GitHub backend's config, read from the ``github:`` block (CAL-1105).

    ``repo`` is the issues repository (``owner/name``); ``project`` is the
    Projects v2 board (``owner/number``) whose single-select ``status_field``
    the harness workflow states map onto. Backend-specific — read only when
    ``tracker: github``.
    """

    repo: str
    project: str
    status_field: str


def _github_settings_from_text(text: str) -> GitHubSettings | None:
    """Resolve :class:`GitHubSettings` from raw CONTEXT.md text, or ``None``.

    ``None`` when there is no ``github:`` block, or the block omits ``repo`` or
    ``project`` — an incomplete block is not a usable config. ``status_field``
    defaults to :data:`_DEFAULT_STATUS_FIELD`.
    """
    block = _block(text, _GITHUB_HEADER)
    if block is None:
        return None
    repo_match = _GH_REPO_KEY.search(block)
    project_match = _GH_PROJECT_KEY.search(block)
    if repo_match is None or project_match is None:
        return None
    field_match = _GH_STATUS_FIELD_KEY.search(block)
    status_field = (
        field_match.group(1).strip().strip("'\"")
        if field_match
        else _DEFAULT_STATUS_FIELD
    )
    return GitHubSettings(
        repo=repo_match.group(1),
        project=project_match.group(1),
        status_field=status_field or _DEFAULT_STATUS_FIELD,
    )


def github_settings(repo_root: Path) -> GitHubSettings | None:
    """Resolve ``repo_root``'s GitHub backend config, or ``None`` if unconfigured.

    Reads the ``github:`` block from CONTEXT.md. Returns ``None`` when the block
    is absent or incomplete (missing ``repo`` or ``project``) — the factory
    turns that into a fail-fast config error, never a silent tracker-less run.
    """
    text = _read_context(repo_root)
    if text is None:
        return None
    return _github_settings_from_text(text)


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

    ``tracker: github`` (CAL-1105) is held to its own config: it requires a
    ``github:`` block carrying ``repo`` (``owner/name``) and ``project``
    (``owner/number``); an absent or incomplete block is rejected here so a
    misconfigured GitHub repo fails fast at ``start`` rather than mid-transition.
    A missing CONTEXT.md — or a CONTEXT.md that declares *no* tracker
    switch at all — is not an inconsistency: the backend reads as the conservative
    ``linear`` default and there is no explicit statement to contradict, so an
    unconfigured repo is left to fail later at the key check, exactly as today.
    Only an **explicit** switch (a ``tracker:`` key, or a back-compat
    ``layers.linear``) is held to the address it implies.
    """
    text = _read_context(repo_root)
    if text is None:
        return None

    has_tracker_key = _TRACKER_KEY.search(text) is not None
    layers = _layers_linear(text)
    explicit = has_tracker_key or layers is not None
    backend = _tracker_from_text(text)
    address = _repo_linear(text)
    has_address = address is not None and address.lower() != "none"

    if backend == "github" and _github_settings_from_text(text) is None:
        return (
            "tracker: github requires a github: block with repo (owner/name) and "
            "project (owner/number) — add it, or set a different tracker"
        )
    if explicit and backend == "linear" and not has_address:
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
    if has_tracker_key and layers is not None:
        layers_on = layers.lower() != "false"
        if layers_on != (backend != "none"):
            return (
                f"tracker: {backend} contradicts layers.linear: {layers} — "
                "remove layers.linear; tracker: is the single source of truth"
            )

    return None
