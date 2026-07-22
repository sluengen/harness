#!/usr/bin/env python3
"""Gate guard against repo-guide guidance drift (#169 / CAL-1202).

The landing page ``docs/index.html`` is hand-authored and duplicates the
guidance catalog (skills / agents / commands) that lives canonically in
``registry.yaml``. A hand-authored copy rots — the pre-relocation
``four-loops.html`` was proof. The accepted proposal
(``specs/proposals/repo-guide-landing-page.md``) chose a **lean gate guard, not
a generator** (ADR 0004): catch the highest-likelihood drift — a renamed or
removed piece of guidance the page still names — without standing up a build
system for a single page.

Every named ``/command``, skill, and agent on the page carries a
``data-guidance="<id>"`` attribute — the machine-readable reference convention
established by CAL-1200 — so "every named piece of guidance" is exactly the set
of those attributes. This guard resolves each id against ``registry.yaml`` and
**fails the gate** (non-zero exit) when any does not resolve (a *ghost*
reference), or when the page names no guidance at all (a broken/restructured
page must not pass vacuously).

It is deliberately one-directional: page -> registry (does everything the page
names still exist?). The reverse direction (registry -> page completeness) and
generating the page from sources are out of scope — a full generator was
weighed and rejected as disproportionate for one page.

Stdlib only (no PyYAML — not a declared dependency; the registry is read with a
line regex, mirroring ``tests/unit/test_landing_page.py`` and
``test_guidance_footprint``). Runs from ``scripts/verify.sh``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: ``scripts/check_*.py`` -> ``parent.parent`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_DEFAULT = REPO_ROOT / "docs" / "index.html"
REGISTRY_DEFAULT = REPO_ROOT / "registry.yaml"

#: A deliberate, machine-readable guidance reference on the page.
_GUIDANCE_REF = re.compile(r'data-guidance=["\']([\w-]+)["\']')
#: A ``files:`` entry in registry.yaml, e.g.
#: ``skills/work-discovery/SKILL.md: { id: work-discovery, version: 0.4.0, ... }``
_REGISTRY_ENTRY = re.compile(r"^\s*[\w./-]+\s*:\s*\{[^}]*\bid:\s*(?P<id>[\w-]+)")


def page_guidance_ids(html: str) -> set[str]:
    """The registry ids the page deliberately references, via ``data-guidance``."""
    return set(_GUIDANCE_REF.findall(html))


def registry_guidance_ids(registry_text: str) -> set[str]:
    """Every id declared in the ``files:`` block of ``registry.yaml``."""
    start = registry_text.index("\nfiles:")
    end = registry_text.index("\nmeta:", start)
    return {
        m.group("id")
        for line in registry_text[start:end].splitlines()
        if (m := _REGISTRY_ENTRY.match(line))
    }


def find_ghost_references(html: str, registry_text: str) -> list[str]:
    """Page-named guidance ids that do not resolve in the registry, sorted."""
    return sorted(page_guidance_ids(html) - registry_guidance_ids(registry_text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--page", type=Path, default=PAGE_DEFAULT, help="path to the landing page HTML"
    )
    parser.add_argument(
        "--registry", type=Path, default=REGISTRY_DEFAULT, help="path to registry.yaml"
    )
    args = parser.parse_args(argv)

    html = args.page.read_text(encoding="utf-8")
    registry_text = args.registry.read_text(encoding="utf-8")

    named = page_guidance_ids(html)
    if not named:
        print(
            f"landing-page drift guard: {args.page} names no guidance "
            '(no data-guidance="<id>" references) — the page structure changed '
            "or is broken; refusing to pass vacuously.",
            file=sys.stderr,
        )
        return 2

    ghosts = sorted(named - registry_guidance_ids(registry_text))
    if ghosts:
        print(
            "landing-page drift guard: the page names guidance absent from "
            f"registry.yaml (ghost reference{'s' if len(ghosts) > 1 else ''}): "
            f"{', '.join(ghosts)}",
            file=sys.stderr,
        )
        return 1

    print(f"landing-page drift guard: OK — {len(named)} guidance references all resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
