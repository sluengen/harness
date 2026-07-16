"""Community-facing docs for the public repo (CAL-1028).

The harness went public (2026-07-06 open-sourcing decision). A public repo needs
a minimum set of community surfaces, and they must not silently rot away:

* a root ``SECURITY.md`` naming a **private** disclosure path and disclaiming a
  bug bounty (a public repo must not imply a reward it will not pay);
* a stated **contribution stance** (a root ``CONTRIBUTING.md``) that addresses
  both issues and pull requests, so a would-be contributor knows what to expect;
* a ``README`` that both **points at** those surfaces (or they are undiscoverable)
  and **warns** a first-time reader this is dogfood infrastructure to adapt, not
  turnkey software.

These guards pin the surfaces, not the prose: they check that each doc exists,
carries the load-bearing statement, and is linked — not that it is worded a
particular way. Git-aware (``tracked_files_under``): each doc must be a
*committed* file, since a public reader sees only the committed tree — one that
exists solely on an author's disk must still fail on a clean checkout (the
CAL-619 git-aware-guard principle).
"""

from __future__ import annotations

from pathlib import Path

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECURITY = _REPO_ROOT / "SECURITY.md"
_CONTRIBUTING = _REPO_ROOT / "CONTRIBUTING.md"
_README = _REPO_ROOT / "README.md"


def test_security_md_is_tracked() -> None:
    """A committed root ``SECURITY.md`` exists — public readers look for it there."""
    assert _SECURITY.resolve() in tracked_files_under("SECURITY.md"), (
        "No tracked SECURITY.md at the repo root. A public repo needs a disclosure "
        "policy where readers (and GitHub's UI) expect it (CAL-1028)."
    )


def test_security_md_states_private_disclosure_and_no_bounty() -> None:
    """SECURITY.md names a private disclosure path and disclaims a bounty."""
    text = _SECURITY.read_text().lower()
    assert "privately" in text, (
        "SECURITY.md must direct reporters to disclose *privately* (e.g. GitHub "
        "private vulnerability reporting), not to open a public issue (CAL-1028)."
    )
    assert "no bug bounty" in text, (
        "SECURITY.md must state plainly that there is no bug bounty, so the policy "
        "does not imply a reward this project will not pay (CAL-1028)."
    )


def test_contributing_md_is_tracked_and_states_stance() -> None:
    """A committed ``CONTRIBUTING.md`` states the stance on issues and PRs."""
    assert _CONTRIBUTING.resolve() in tracked_files_under("CONTRIBUTING.md"), (
        "No tracked CONTRIBUTING.md. The open-sourcing needs an explicit "
        "contribution stance so a would-be contributor knows what to expect "
        "(CAL-1028)."
    )
    text = _CONTRIBUTING.read_text().lower()
    assert "issue" in text and ("pull request" in text or " pr" in text), (
        "CONTRIBUTING.md must address both issues and pull requests — that is the "
        "stance the ticket asks for (CAL-1028)."
    )


def test_readme_links_community_docs() -> None:
    """The README points at the community docs so they are discoverable, not orphaned."""
    text = _README.read_text()
    missing = [name for name in ("SECURITY.md", "CONTRIBUTING.md") if name not in text]
    assert not missing, (
        f"README does not reference {missing!r}. A community doc nobody links to is "
        "an orphan — point readers at SECURITY.md and CONTRIBUTING.md (CAL-1028)."
    )


def test_readme_warns_dogfood_not_turnkey() -> None:
    """The README carries the public-reader caveat: dogfood infrastructure, not turnkey."""
    text = _README.read_text().lower()
    assert "adapt to taste" in text or "dogfood infrastructure" in text, (
        "README must carry the prominent caveat that this is dogfood "
        "infrastructure to adapt, not turnkey software a public reader can run "
        "unmodified (CAL-1028)."
    )
