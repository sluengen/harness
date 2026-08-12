"""CAL-829 — code-quality enumerates a fetch-untrusted-URLs hardening checklist.

From ``/assess code`` 2026-06-20 (pass 5), steward insight CODE-INSIGHT-1 on the
CAL-819 crawler surface (slate): the repo gained its first code that fetches and
parses adversarial third-party content (GETs roaster homepages and
page-declared logo URLs), and no skill named the hardening checklist that
boundary needs. ``engineering-principles`` carries the abstract "Validate at
boundaries, trust within", but nothing in ``code-quality`` enumerated the
concrete network-fetch checks — so CAL-827 (the *absence* of a standard
checklist on a brand-new fetch surface) was a guidance gap, not a one-off slip.

These are text-parse content guards in the style of
``test_mirrors_admission_third_strike`` (CAL-800) and ``test_over_engineering_lens``
(CAL-711): they read the as-built guidance and assert the rule is present, so a
later re-edit cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — ``code-quality`` Part B carries a "Fetching untrusted URLs"
  subsection. Proven by :func:`test_fetch_subsection_exists` and
  :func:`test_fetch_subsection_is_in_part_b`.
* **AC-2** — the subsection enumerates the four concrete checks: a scheme
  allowlist (``http``/``https`` only), a host allowlist / reject-internal-address
  rule (loopback, private, link-local, reserved, cloud-metadata), a streamed
  download size cap, and a decompression/pixel cap that re-validates the URL
  after redirects. Proven by the four ``test_check_*`` functions.
* **AC-3** — the subsection names itself the concrete application of
  ``engineering-principles``' "Validate at boundaries, trust within": the
  principle keeps its one home, the application points to it. Proven by
  :func:`test_fetch_subsection_cites_boundary_principle`.

Version integrity (header ↔ registry parity) is covered by the pre-existing
``test_guidance_source.test_surface_headers_match_registry``; no duplicate
parity guard is added here (cf. ``test_skill_boundary_dedup``).
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "references" / "untrusted-fetch.md"


def _fetch_section(text: str) -> str:
    """The 'Fetching untrusted URLs' subsection of code-quality Part B.

    Slice from that ``###`` heading to the next ``###``/``##`` heading so the
    assertions see only this rule, not the neighbouring Structure subsections.
    """
    m = re.search(r"^### Fetching untrusted URLs\s*$", text, re.MULTILINE)
    assert m, (
        "code-quality Part B must carry a '### Fetching untrusted URLs' "
        "subsection (CAL-829 AC-1)."
    )
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


# --- AC-1: the subsection exists, in Part B -----------------------------------


def test_fetch_subsection_exists() -> None:
    """code-quality has a 'Fetching untrusted URLs' subsection (AC-1)."""
    section = _fetch_section(_CODE_QUALITY.read_text())
    assert section.strip(), "the 'Fetching untrusted URLs' subsection is empty."


def test_fetch_subsection_is_directly_linked_from_part_b() -> None:
    """The conditional checklist remains reachable from Part B (AC-1)."""
    core = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
    text = core.read_text()
    part_b = text.index("## Part B")
    part_c = text.index("## Part C", part_b)
    link = text.index("references/untrusted-fetch.md")
    assert part_b < link < part_c, (
        "Part B must directly link the conditional untrusted-fetch checklist"
    )


# --- AC-2: the four concrete checks -------------------------------------------


def test_check_scheme_allowlist() -> None:
    """Check 1 — a scheme allowlist of http/https for untrusted-derived URLs."""
    section = _fetch_section(_CODE_QUALITY.read_text()).lower()
    assert "scheme" in section and "https" in section, (
        "the checklist must require a scheme allowlist (http/https only) for "
        "URLs derived from untrusted content (CAL-829 AC-2, check 1)."
    )


def test_check_host_allowlist_rejects_internal_addresses() -> None:
    """Check 2 — reject internal addresses (the SSRF surface)."""
    section = _fetch_section(_CODE_QUALITY.read_text()).lower()
    required = ("loopback", "private", "link-local", "reserved", "metadata")
    missing = [r for r in required if r not in section]
    assert not missing, (
        "the checklist must reject internal addresses (loopback, private, "
        f"link-local, reserved, cloud-metadata); missing: {missing} "
        "(CAL-829 AC-2, check 2)."
    )


def test_check_download_size_cap() -> None:
    """Check 3 — a streamed download size cap, not a whole-body buffer."""
    section = _fetch_section(_CODE_QUALITY.read_text()).lower()
    assert "cap" in section and "stream" in section and "abort" in section, (
        "the checklist must require a streamed download size cap (stream + "
        "abort, don't buffer the whole body) (CAL-829 AC-2, check 3)."
    )


def test_check_decompression_cap_and_redirect_revalidation() -> None:
    """Check 4 — a decompression/pixel cap that re-validates after redirects."""
    section = _fetch_section(_CODE_QUALITY.read_text()).lower()
    assert "decompression" in section and "pixel" in section, (
        "the checklist must cap the decoded size of compressed/media payloads "
        "(a decompression and pixel cap) (CAL-829 AC-2, check 4)."
    )
    assert "redirect" in section, (
        "the checklist must re-validate the URL after redirects — the redirect "
        "target is as untrusted as the original (CAL-829 AC-2, check 4)."
    )


# --- AC-3: the checklist points to the principle's one home -------------------


def test_fetch_subsection_cites_boundary_principle() -> None:
    """The checklist names itself the application of the boundary principle (AC-3)."""
    section = _fetch_section(_CODE_QUALITY.read_text())
    low = section.lower()
    assert "engineering-principles" in low, (
        "the checklist must point to `engineering-principles` as the home of "
        "the boundary principle it applies (CAL-829 AC-3)."
    )
    assert "validate at boundaries" in low, (
        "the checklist must name the 'Validate at boundaries, trust within' "
        "principle it concretizes (CAL-829 AC-3)."
    )
