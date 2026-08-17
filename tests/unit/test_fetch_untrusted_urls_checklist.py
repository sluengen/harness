"""``code-quality``'s untrusted-fetch checklist keeps its four checks.

From ``/assess code`` 2026-06-20 (pass 5), steward insight CODE-INSIGHT-1 on the
crawler surface: the repo gained its first code that fetches and parses
adversarial third-party content (GETs third-party homepages and page-declared
logo URLs), and no skill named the hardening checklist that boundary needs.
``engineering-principles`` carries the abstract *Validate at boundaries, trust
within*, but nothing enumerated the concrete network-fetch checks — so the
*absence* of a standard checklist on a brand-new fetch surface was a guidance
gap, not a one-off slip.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) seven functions over one section
collapse into one tripwire:

* the ``### Fetching untrusted URLs`` section **exists** in its canonical home,
  and the assertion reads only that slice;
* one term per check — ``scheme``, ``loopback``/``metadata``, ``stream``/``cap``,
  ``decompression``, ``redirect`` — plus the cite that gives the principle its
  one home (``engineering-principles`` → *Validate at boundaries, trust within*).

**This rule has no polarity, and none is faked.** The rule is an *enumeration*:
its content is that four named checks are present, not that some claim points one
way. Each item's direction lives in its own verb (accept `http`/`https`, refuse
loopback, abort past a cap), and a negation token asserted over the section as a
whole would match any of them — a checklist inverted item by item would keep
every ``not``/``never`` it has. Per ADR 0016 that is stated here rather than
dressed up as a polarity assertion: an inverted check is caught by the reviewer,
and a *deleted* check is caught by the term missing from the window.

The Part B link placement stays as its own assertion — it is **structural
correspondence** (the conditional reference is reachable from the hot skill, and
from the right part of it), which ADR 0016 exempts. Header ↔ registry parity is
owned by ``test_guidance_source.test_surface_headers_match_registry``; no
duplicate parity guard is added here.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "references" / "untrusted-fetch.md"


def _fetch_section() -> str:
    """The 'Fetching untrusted URLs' section, heading to the next heading.

    Sliced deliberately: the assertions must see only this rule, not the
    neighbouring prose, or a term found elsewhere in the file reports a check
    that is no longer written down.
    """
    text = _CODE_QUALITY.read_text()
    m = re.search(r"^### Fetching untrusted URLs\s*$", text, re.MULTILINE)
    assert m, (
        "code-quality's conditional fetch reference must carry a "
        "'### Fetching untrusted URLs' section"
    )
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    section = rest[: end.start()] if end else rest
    assert section.strip(), "the 'Fetching untrusted URLs' section is empty."
    return section.lower()


def test_the_untrusted_fetch_checklist_keeps_its_four_checks() -> None:
    """One tripwire for one rule-home: the anchor plus one term per check (#459)."""
    section = _fetch_section()

    # Check 1 — a scheme allowlist for URLs derived from untrusted content.
    assert "scheme" in section, (
        "the checklist must require a scheme allowlist (http/https only) for "
        "URLs derived from untrusted content"
    )
    # Check 2 — the SSRF surface: internal address ranges.
    for address in ("loopback", "metadata"):
        assert address in section, (
            f"the checklist must name {address!r} among the internal address "
            "ranges an untrusted-derived URL is refused for (the SSRF surface)"
        )
    # Check 3 — a streamed download cap rather than a whole-body buffer.
    assert "stream" in section and "cap" in section, (
        "the checklist must require a streamed download size cap — stream and "
        "abort, rather than buffering a whole untrusted response into memory"
    )
    # Check 4 — the decoded size, and the URL the redirect chain lands on.
    assert "decompression" in section, (
        "the checklist must bound the *decoded* size of compressed or media "
        "payloads; a wire-size cap alone passes a decompression bomb"
    )
    assert "redirect" in section, (
        "the checklist must re-validate the URL after redirects — a redirect "
        "target is as untrusted as the original"
    )
    # The principle keeps one home; this checklist is its application.
    assert "engineering-principles" in section, (
        "the checklist must point to `engineering-principles` as the home of the "
        "boundary principle it applies"
    )
    assert "validate at boundaries" in section, (
        "the checklist must name the 'Validate at boundaries, trust within' "
        "principle it concretizes, so the two surfaces stay tied together"
    )


def test_fetch_subsection_is_directly_linked_from_part_b() -> None:
    """The conditional checklist remains reachable from Part B (AC-1)."""
    core = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
    text = core.read_text()
    part_b = text.index("## Part B")
    part_c = text.index("## Part C", part_b)
    link = text.index("references/untrusted-fetch.md")
    assert part_b < link < part_c, (
        "Part B must directly link the conditional untrusted-fetch checklist"
    )
