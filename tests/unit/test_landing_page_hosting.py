"""Hosting metadata for the repo-guide landing page (CAL-1201).

CAL-1200 authored ``docs/index.html``; this ticket makes it a shareable,
discoverable GitHub Pages landing page. These guards pin the builder-settleable
acceptance criteria:

  * the page carries Open-Graph + Twitter-card meta tags and a favicon, with the
    referenced raster assets present under ``docs/``;
  * the canonical share URL is the decided GitHub Pages default host;
  * the README links the hosted guide near the top (the README stays the
    canonical text front door; the page is its visual companion);
  * ``specs/infrastructure.md`` records the hosting decision and the
    release-cadence / world-readable exposure note.

AC-1 ("page reachable at the Pages URL") is an *operational* criterion: it
depends on the operator enabling Pages and on ``docs/`` reaching ``main`` via a
``dev -> staging -> main`` release. It is verified against the live GitHub API,
not in these unit tests — there is nothing in the tree to assert against.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

DOCS = REPO_ROOT / "docs"
PAGE = DOCS / "index.html"
README = REPO_ROOT / "README.md"
INFRA = REPO_ROOT / "specs" / "infrastructure.md"

#: The decided canonical share URL — GitHub Pages default host, no custom domain.
PAGES_URL = "https://sluengen.github.io/harness/"

#: How many leading README lines count as "near the top".
README_TOP_LINES = 15


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _head(html: str) -> str:
    """The ``<head>`` ... ``</head>`` slice — meta tags must live there."""
    m = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
    assert m, "page must have a <head> section"
    return m.group(1)


def _meta_content(head: str, attr: str, key: str) -> str | None:
    """Return the ``content`` of ``<meta {attr}="{key}" content="...">``."""
    m = re.search(
        rf'<meta\b[^>]*\b{attr}=["\']{re.escape(key)}["\'][^>]*'
        rf'\bcontent=["\']([^"\']+)["\']',
        head,
    )
    return m.group(1) if m else None


# --------------------------------------------------------------------------- #
# Open Graph + Twitter card
# --------------------------------------------------------------------------- #


def test_page_declares_open_graph_tags() -> None:
    head = _head(_page())
    for prop in ("og:type", "og:url", "og:title", "og:description", "og:image"):
        assert _meta_content(head, "property", prop), f"missing Open-Graph tag: {prop}"


def test_page_declares_twitter_card() -> None:
    head = _head(_page())
    card = _meta_content(head, "name", "twitter:card")
    assert card == "summary_large_image", (
        f"twitter:card should be summary_large_image, got {card!r}"
    )
    for name in ("twitter:title", "twitter:description", "twitter:image"):
        assert _meta_content(head, "name", name), f"missing Twitter-card tag: {name}"


def test_share_url_is_pages_default_host() -> None:
    url = _meta_content(_head(_page()), "property", "og:url")
    assert url == PAGES_URL, f"og:url must be the decided Pages URL {PAGES_URL!r}, got {url!r}"


def test_page_has_meta_description() -> None:
    desc = _meta_content(_head(_page()), "name", "description")
    assert desc and desc.strip(), "page must carry a non-empty meta description"


# --------------------------------------------------------------------------- #
# Favicon + raster share assets
# --------------------------------------------------------------------------- #


def test_page_declares_favicon() -> None:
    head = _head(_page())
    m = re.search(r'<link\b[^>]*\brel=["\']icon["\'][^>]*\bhref=["\']([^"\']+)["\']', head)
    assert m, 'page must declare a favicon (<link rel="icon">)'
    href = m.group(1)
    assert not href.startswith(("http://", "https://")), "favicon must be a local asset, not a URL"
    asset = (DOCS / href).resolve()
    assert asset.is_file() and asset.stat().st_size > 0, (
        f"favicon asset {href!r} must exist under docs/"
    )


def test_raster_share_assets_are_pngs() -> None:
    """The favicon and the Open-Graph card image are real, non-trivial rasters."""
    for name in ("favicon.png", "og-card.png"):
        asset = DOCS / name
        assert asset.is_file(), f"expected raster asset docs/{name}"
        data = asset.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), f"docs/{name} must be a PNG"
        assert len(data) > 200, f"docs/{name} looks empty/truncated"


def test_og_image_points_at_local_share_asset() -> None:
    url = _meta_content(_head(_page()), "property", "og:image")
    assert url, "missing og:image meta tag"
    # Crawlers require an absolute URL; it must resolve under the Pages host and
    # name a raster that exists under docs/.
    assert url.startswith(PAGES_URL), f"og:image must be absolute under {PAGES_URL}, got {url!r}"
    name = url[len(PAGES_URL):]
    assert (DOCS / name).is_file(), f"og:image {name!r} must exist under docs/"


# --------------------------------------------------------------------------- #
# README link (canonical text front door -> visual companion)
# --------------------------------------------------------------------------- #


def test_readme_links_hosted_guide_near_top() -> None:
    lines = README.read_text(encoding="utf-8").splitlines()[:README_TOP_LINES]
    assert any(PAGES_URL in line for line in lines), (
        f"README must link the hosted guide ({PAGES_URL}) within the first {README_TOP_LINES} lines"
    )


# --------------------------------------------------------------------------- #
# infrastructure.md record (hosting decision + cadence/exposure note)
# --------------------------------------------------------------------------- #


def test_infrastructure_records_hosting_decision() -> None:
    text = INFRA.read_text(encoding="utf-8")
    assert PAGES_URL in text, "infrastructure.md must record the Pages URL"
    assert "GitHub Pages" in text, (
        "infrastructure.md must name GitHub Pages as the hosting platform"
    )


def test_infrastructure_records_exposure_and_cadence() -> None:
    text = INFRA.read_text(encoding="utf-8")
    assert "world-readable" in text.lower(), (
        "infrastructure.md must record that docs/ on main is world-readable"
    )
    assert "dev → staging → main" in text, (
        "infrastructure.md must record the docs release cadence "
        "(docs/ only updates on a dev → staging → main release)"
    )
