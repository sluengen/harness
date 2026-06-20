"""CAL-811 — registered universal prose carries no repo-specific ticket IDs.

The installed surface ships prose into *consuming* repos. That prose must name
no facts of the *source* repo — a ticket id like ``CAL-702`` is meaningless (and
faintly absurd) in a repo with its own tracker, and it violates the
universal/repo-specific boundary that ``guidance-coherence`` polices.

This already drifted live: ``commands/harness.md`` became a distributed surface
unit (CAL-764) while still carrying ``CAL-702`` and ``CAL-739`` in universal
prose, so the source-freshness hook warned on an otherwise normal edit of it
(``/assess system`` 2026-06-19, finding SYSTEM-1). The hook
(``hooks/guidance-freshness.js``) catches a leak only when a file *is edited*;
nothing pins the committed tree, so the next leak rides in silently until someone
happens to touch that file.

This guard turns the hook's per-edit warning into a standing check on the
committed tree. The leak definition is **not re-invented** — the
``TICKET`` regex and the ``STD`` allowlist are parsed straight out of
``hooks/guidance-freshness.js`` and reused here, so the guard can never drift
from the hook's detector semantics: a future change to the hook's allowlist
propagates automatically, and a parse failure trips :func:`test_detector_parsed_from_hook`
loudly rather than silently checking nothing.

Scope — *registered* universal prose: a git-tracked file under the universal
prose dirs (``skills/`` ``agents/`` ``commands/`` ``process/`` ``templates/`` —
the hook's ``PROSE`` set) that is a member of ``registry.yaml``'s ``files:``
block. A repo-owned file a repo keeps under those dirs but never registers is
*not* distributed guidance (the hook exempts it via its non-member early return),
so it is out of scope and may name its own repo's facts. Membership is decided by
the hook's own ``registryMember`` rule, mirrored here.

Acceptance criteria (CAL-811):

* **AC-3** — the guard scans current registered universal prose for
  ticket-ID-shaped repo facts using the ``guidance-freshness.js`` detector
  semantics. Proven by :func:`test_no_repo_ids_in_distributed_prose`, which fails
  against the original ``CAL-702`` / ``CAL-739`` leaks, anchored non-vacuous by
  :func:`test_sweep_covers_registered_prose` and the detector/membership pins.
* **AC-1/AC-2/AC-4** (no leak in ``commands/harness.md``; provenance moved to
  neutral wording; the hook no longer warns) follow from the same file being in
  scope and clean — the hook reuses this very detector, so an empty result here
  *is* a no-warn there.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "guidance-freshness.js"
_REGISTRY = _REPO_ROOT / "registry.yaml"

#: The universal-prose directories — the hook's ``PROSE`` set. Leaks are
#: leak-checked only inside these (``hooks`` / ``settings`` are distributed but
#: not prose).
_PROSE_DIRS = ("skills", "agents", "commands", "process", "templates")


def _parse_detector(hook_src: str) -> tuple[re.Pattern[str], frozenset[str]]:
    """Parse the hook's ``TICKET`` regex and ``STD`` allowlist and reuse them.

    The JS regex body (``\\b([A-Z]{2,5})-\\d+\\b``) is valid Python ``re`` syntax,
    so it is compiled as-is rather than transcribed — there is exactly one leak
    definition, and it lives in the hook.
    """
    ticket = re.search(r"const TICKET\s*=\s*/(?P<body>.+?)/[a-z]*;", hook_src)
    std = re.search(r"const STD\s*=\s*new Set\(\[(?P<items>.*?)\]\)", hook_src, re.S)
    assert ticket and std, "could not parse TICKET/STD out of guidance-freshness.js"
    members = frozenset(re.findall(r'"([^"]+)"', std.group("items")))
    return re.compile(ticket.group("body")), members


_TICKET, _STD = _parse_detector(_HOOK.read_text())


def _leaked_ids(text: str) -> list[str]:
    """Ticket-ID-shaped tokens that are repo facts, per the hook's detector.

    Mirrors ``leakedIds`` in the hook: a match counts unless its alpha prefix
    (group 1) is an allow-listed standard/abbreviation (``RFC``, ``AC``, …).
    """
    return sorted({m.group(0) for m in _TICKET.finditer(text) if m.group(1) not in _STD})


def _is_registered(rel_path: str, registry_src: str) -> bool:
    """Whether ``rel_path`` is a member of ``registry.yaml``'s files block.

    Mirrors the hook's ``registryMember`` rule (a ``<path>: {`` mapping key)
    rather than re-deriving it, so source and guard agree on what "distributed"
    means.
    """
    pattern = r"(^|\n)\s*" + re.escape(rel_path) + r":\s*\{"
    return re.search(pattern, registry_src) is not None


def _registered_prose_files() -> list[Path]:
    """Git-tracked, registry-member files under the universal-prose dirs."""
    registry_src = _REGISTRY.read_text()
    found: list[Path] = []
    for prose_dir in _PROSE_DIRS:
        for path in sorted(tracked_files_under(prose_dir)):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if _is_registered(rel, registry_src):
                found.append(path)
    return found


def test_detector_parsed_from_hook() -> None:
    """The detector is the hook's own, and classifies leaks correctly.

    Pins the parse so the sweep is never silently neutered: the allowlist must be
    non-empty and a known standard must survive, while a real repo ticket id must
    be flagged. Anchors AC-3's "matching the detector semantics".
    """
    assert "AC" in _STD and "RFC" in _STD, "STD allowlist did not parse"
    assert _leaked_ids("the verb falls back once to Claude (CAL-702)") == ["CAL-702"]
    assert _leaked_ids("acceptance criterion AC-1 per RFC-2119") == []


def test_registry_member_rule() -> None:
    """The membership predicate matches the registered command, not a non-entry.

    ``commands/harness.md`` is registered (CAL-764), so it is in scope — the very
    file this ticket cleans must be covered. A made-up path must not register, or
    the sweep would silently widen.
    """
    registry_src = _REGISTRY.read_text()
    assert _is_registered("commands/harness.md", registry_src)
    assert not _is_registered("commands/does-not-exist.md", registry_src)


def test_sweep_covers_registered_prose() -> None:
    """The sweep is non-vacuous: it sees real registered prose, incl. the target.

    Guards against a collector that finds nothing (registry-path mismatch, wrong
    root), which would make the leak sweep pass without checking anything.
    """
    rels = {p.relative_to(_REPO_ROOT).as_posix() for p in _registered_prose_files()}
    assert "commands/harness.md" in rels
    assert any(r.startswith("skills/") for r in rels), "no registered skill prose found"


def test_no_repo_ids_in_distributed_prose() -> None:
    """No registered universal prose file carries a repo-specific ticket id (AC-3)."""
    violations: list[str] = []
    for path in _registered_prose_files():
        ids = _leaked_ids(path.read_text())
        if ids:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            violations.append(f"{rel}: {', '.join(ids)}")

    assert not violations, (
        "registered universal prose names repo-specific ticket id(s) — universal "
        "guidance must name no repo facts; use neutral decision/proposal wording "
        "or move provenance to tests/assessments/changelog (CAL-811):\n  "
        + "\n  ".join(violations)
    )
