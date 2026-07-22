"""The repo-guide landing page (docs/index.html) — artifact guards (CAL-1200).

The page is a hand-authored, self-contained landing page grown from the
internal ``four-loops.html``. It duplicates facts that live canonically in
``registry.yaml`` and the specs, so these guards pin the three acceptance
criteria that keep it honest:

  AC-1  it renders standalone (no external resource requests) and carries all
        three sections — the Four Loops hero, the harness, and the guidance.
  AC-2  no stale claims remain — the two the proposal named: the as-built
        review is recorded by the reviewer on PASS (not "closed by hand /
        find the old chat"), and ADRs live in ``specs/decisions/`` (not
        "there is no separate ``decisions/`` folder").
  AC-3  every command / skill / agent the page names resolves to an id in
        ``registry.yaml``. Named guidance is marked with a
        ``data-guidance="<id>"`` attribute so the check keys on a deliberate
        machine-readable reference rather than brittle prose-scanning.

The dedicated gate-level drift guard — a ``scripts/`` check that also enforces
the *completeness* (registry -> page) direction — is a separate ticket
(CAL-1202); these are the artifact tests that pin the page as built.

Registry ids are read with a line regex, not PyYAML — PyYAML is not a declared
dependency (mirrors ``test_guidance_footprint``).
"""

from __future__ import annotations

import re
from pathlib import Path

#: ``tests/unit/test_*.py`` -> ``parents[2]`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "docs" / "index.html"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The three top-level sections the page must carry, keyed by their stable
#: ``data-section`` marker (the visible heading text is free to change).
REQUIRED_SECTIONS = ("loops", "harness", "guidance")


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _registry_ids_by_kind() -> dict[str, set[str]]:
    """Map surface kind (``skills`` / ``agents`` / ``commands``) -> set of ids.

    Reads the ``files:`` block of ``registry.yaml`` with a line regex (PyYAML is
    not a declared dependency). A files entry looks like::

        skills/work-discovery/SKILL.md: { id: work-discovery, version: 0.3.0, ... }
    """
    text = REGISTRY.read_text(encoding="utf-8")
    start = text.index("\nfiles:")
    end = text.index("\nmeta:", start)
    by_kind: dict[str, set[str]] = {"skills": set(), "agents": set(), "commands": set()}
    entry = re.compile(r"^\s*(?P<path>[\w./-]+)\s*:\s*\{[^}]*\bid:\s*(?P<id>[\w-]+)")
    for line in text[start:end].splitlines():
        m = entry.match(line)
        if not m:
            continue
        kind = m.group("path").split("/", 1)[0]
        if kind in by_kind:
            by_kind[kind].add(m.group("id"))
    return by_kind


def _all_registry_ids() -> set[str]:
    kinds = _registry_ids_by_kind()
    return kinds["skills"] | kinds["agents"] | kinds["commands"]


def _named_guidance() -> set[str]:
    """The registry ids the page deliberately references, via ``data-guidance``."""
    return set(re.findall(r'data-guidance=["\']([\w-]+)["\']', _page()))


# --------------------------------------------------------------------------- #
# AC-1 — relocation + self-contained + all three sections
# --------------------------------------------------------------------------- #


def test_page_relocated_from_four_loops() -> None:
    """The page lives at ``docs/index.html``; ``four-loops.html`` is moved, not copied."""
    assert PAGE.is_file(), "docs/index.html must exist (four-loops.html relocated here)"
    assert not (REPO_ROOT / "four-loops.html").exists(), (
        "four-loops.html must be moved to docs/index.html, not left behind as a copy"
    )


def test_no_external_resource_requests() -> None:
    """AC-1: the page fetches nothing at render — inline CSS/SVG only.

    Navigation links (``<a href="https://...">``) are allowed — a click, not a
    load-time request. Resource-loading references are not: external
    stylesheets, scripts, images, iframes, web fonts, or a CSS ``url()`` /
    ``@import`` pointing at a remote host.
    """
    html = _page()
    forbidden = [
        (r"<link\b[^>]*\brel\s*=\s*['\"]?(stylesheet|preconnect|dns-prefetch|prefetch)",
         "external <link rel>"),
        (r"<link\b[^>]*\bhref\s*=\s*['\"]?https?://", "external <link href>"),
        (r"<script\b[^>]*\bsrc\s*=\s*['\"]?https?://", "external <script src>"),
        (r"<img\b[^>]*\bsrc\s*=\s*['\"]?https?://", "external <img src>"),
        (r"<iframe\b", "iframe"),
        (r"@import\b", "CSS @import"),
        (r"url\(\s*['\"]?https?://", "CSS url() to a remote host"),
    ]
    hits = [why for rx, why in forbidden if re.search(rx, html, re.IGNORECASE)]
    assert not hits, f"page must be self-contained; found external resource refs: {hits}"


def test_carries_all_three_sections() -> None:
    """AC-1: the Four Loops hero, the harness, and the guidance sections all render."""
    html = _page()
    missing = [s for s in REQUIRED_SECTIONS if f'data-section="{s}"' not in html]
    assert not missing, f"page is missing required section(s): {missing}"


# --------------------------------------------------------------------------- #
# AC-2 — no stale claims (the two the proposal named)
# --------------------------------------------------------------------------- #


def test_no_stale_as_built_review_claim() -> None:
    """AC-2: the as-built review is recorded by the reviewer on PASS via ``close`` —
    not "closed by hand (find the old chat)"."""
    low = _page().lower()
    assert "closed by hand" not in low, "stale claim: as-built review is not 'closed by hand'"
    assert "find the old chat" not in low, "stale claim: 'find the old chat' is no longer true"


def test_no_stale_decisions_folder_claim() -> None:
    """AC-2: ADRs live in ``specs/decisions/`` — not "there is no separate decisions/ folder"."""
    html = _page()
    low = html.lower()
    assert "no separate decisions/ folder" not in low, "stale claim: there IS a decisions/ folder"
    assert "there is no separate" not in low, "stale phrasing: embedded-only decisions model"
    assert "specs/decisions/" in html, "the page must point ADRs at specs/decisions/"


# --------------------------------------------------------------------------- #
# AC-3 — every named command / skill / agent resolves in registry.yaml
# --------------------------------------------------------------------------- #


def test_named_guidance_resolves_in_registry() -> None:
    """AC-3: every skill / agent / command the page names exists in registry.yaml."""
    named = _named_guidance()
    assert named, "the page must mark its guidance references with data-guidance=\"<id>\""
    unknown = named - _all_registry_ids()
    assert not unknown, f"page names guidance absent from registry.yaml: {sorted(unknown)}"


def test_catalog_marks_every_kind() -> None:
    """AC-3: the guidance catalog names at least one skill, one agent, and one command
    (a self-contained catalog cannot be honest if a whole kind is missing)."""
    named = _named_guidance()
    kinds = _registry_ids_by_kind()
    for kind in ("skills", "agents", "commands"):
        assert named & kinds[kind], f"the guidance catalog names no {kind}"
