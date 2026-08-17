"""Community-facing docs for the public repo.

The harness went public (2026-07-06 open-sourcing decision). A public repo needs
a minimum set of community surfaces, and they must not silently rot away:

* a root ``SECURITY.md`` naming a **private** disclosure path, disclaiming a
  bug bounty (a public repo must not imply a reward it will not pay), and stating
  the **gate's trust boundary** (#435 re-pinned this from the retired ledger onto
  the gate — the named surface moved, the boundary did not);
* a stated **contribution stance** (a root ``CONTRIBUTING.md``);
* a ``README`` that both **points at** those surfaces (or they are undiscoverable)
  and **warns** a first-time reader this is dogfood infrastructure to adapt, not
  turnkey software.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) the prose pins collapse to one
tripwire per rule-home, and the structural assertions stay:

* **Tracked-file existence** for ``SECURITY.md`` and ``CONTRIBUTING.md``, and the
  README → docs **link correspondence**, are unchanged. They compare two things
  in the tree, which ADR 0016 exempts. Git-aware (``tracked_files_under``): a
  public reader sees only the committed tree, so a doc that exists solely on an
  author's disk must still fail on a clean checkout.
* **``SECURITY.md``** gets one tripwire, reading each claim from **the section
  that carries it** — the sections located by subject word among the file's own
  headings, and each claim asserted against the section *body* rather than its
  title. The ticket's plan called for a single whole-file read, on the grounds
  that the policy is one page. Measured, that is weaker than it looks: the file
  states its gate disclaimer twice and titles its bounty section *No bug
  bounty*, so a whole-file negation search is satisfied by a second sentence or
  by a heading, and inverting the paragraph a reader acts on leaves it green.
  Terms: the private disclosure path, the actor who can forge evidence.
  Polarity yes, twice, and both anchored in a body: *no bug bounty*, and *not a
  cryptographic attestation*. A policy that mentions a bounty without refusing
  one implies the reward, and a gate section that mentions attestation without
  disclaiming it is the security claim the project never made.
* **``README.md``** gets one tripwire over its turnkey section, located by the
  word ``turnkey`` in a heading rather than by the heading's full text, so a
  benign re-titling does not break the anchor. Term: ``adapt``, what the reader
  is told to do instead. Polarity yes and anchored: *not a turnkey product*.

Occurrence these cite (``code-quality`` Part C, *A new guard cites the occurrence
it prevents*): the predecessor README assertion was ``"adapt to taste" in text or
"dogfood infrastructure" in text`` — an exact-phrase pin over the whole file that
would break on rewording the caveat and pass on a README that kept the phrase in
a section promising turnkey installation.

The CONTRIBUTING stance is asserted as a tracked file only; whether its prose
covers issues *and* pull requests is meaning, which the review gate owns.
"""

from __future__ import annotations

import re

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

_SECURITY = REPO_ROOT / "SECURITY.md"
_CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
_README = REPO_ROOT / "README.md"

#: The bounty disclaimer, **anchored to the noun it refuses**. A policy carrying
#: a negation somewhere and the words *bug bounty* somewhere states nothing.
_NO_BOUNTY = re.compile(r"\bno\b(?:\W+\w+){0,2}?\W+bug bounty\b", re.IGNORECASE)

#: The gate's trust boundary, **anchored to the guarantee it declines**. Naming
#: attestation or tamper-evidence without refusing it is the reading the section
#: exists to head off.
_NOT_ATTESTATION = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,4}?\W+(?:attestation|tamper)\w*\b", re.IGNORECASE
)

#: The README caveat, **anchored to the claim it denies**.
_NOT_TURNKEY = re.compile(r"\b(?:not|never|no)\b(?:\W+\w+){0,3}?\W+turnkey\b", re.IGNORECASE)


def _security_section_body(subject: str) -> str:
    """The body of the ``SECURITY.md`` section whose heading names ``subject``.

    Two narrowings, both load-bearing. **By section**, because the policy states
    its gate disclaimer twice: a whole-file negation search is satisfied by the
    other sentence, so inverting the paragraph a reader acts on stays green.
    **Body only**, because one section is *titled* "No bug bounty" — a window
    including its own heading answers a question about the policy with the
    policy's table of contents.
    """
    text = _SECURITY.read_text()
    headings = list(re.finditer(r"^##+ .*$", text, re.MULTILINE))
    hits = [i for i, m in enumerate(headings) if subject in m.group(0).lower()]
    assert len(hits) == 1, (
        f"SECURITY.md must carry exactly one section heading naming {subject!r}; "
        f"found {len(hits)}. The disclosure policy's claims are addressed by "
        f"section, and a claim with no section of its own is one a reader has to "
        f"go looking for."
    )
    start = headings[hits[0]].end()
    end = headings[hits[0] + 1].start() if hits[0] + 1 < len(headings) else len(text)
    body = text[start:end]
    assert body.strip(), f"SECURITY.md's {subject!r} section has no body"
    return body.lower()


def _readme_turnkey_section() -> str:
    """The README section addressing turnkey-ness, located by its subject.

    The anchor is *a heading naming ``turnkey``*, derived from the file's own
    headings rather than pinned to one title, so re-titling the section keeps the
    guard pointed at it while deleting the section fails loudly.
    """
    text = _README.read_text()
    headings = list(re.finditer(r"^##+ .*$", text, re.MULTILINE))
    hits = [i for i, m in enumerate(headings) if "turnkey" in m.group(0).lower()]
    assert hits, (
        "README has no section heading about turnkey-ness. The public-reader "
        "caveat — dogfood infrastructure to adapt, not a product to install — is "
        "the first thing a first-time reader needs, and a caveat with no heading "
        "is not findable"
    )
    assert len(hits) == 1, (
        f"README carries {len(hits)} turnkey headings; the caveat has one home"
    )
    start = headings[hits[0]].start()
    end = headings[hits[0] + 1].start() if hits[0] + 1 < len(headings) else len(text)
    return text[start:end].lower()


def test_security_md_is_tracked() -> None:
    """A committed root ``SECURITY.md`` exists — public readers look for it there."""
    assert _SECURITY.resolve() in tracked_files_under("SECURITY.md"), (
        "No tracked SECURITY.md at the repo root. A public repo needs a disclosure "
        "policy where readers (and GitHub's UI) expect it."
    )


def test_contributing_md_is_tracked() -> None:
    """A committed ``CONTRIBUTING.md`` exists — the contribution stance has a home."""
    assert _CONTRIBUTING.resolve() in tracked_files_under("CONTRIBUTING.md"), (
        "No tracked CONTRIBUTING.md. The open-sourcing needs an explicit "
        "contribution stance so a would-be contributor knows what to expect."
    )


def test_readme_links_community_docs() -> None:
    """The README points at the community docs so they are discoverable, not orphaned."""
    text = _README.read_text()
    missing = [name for name in ("SECURITY.md", "CONTRIBUTING.md") if name not in text]
    assert not missing, (
        f"README does not reference {missing!r}. A community doc nobody links to is "
        "an orphan — point readers at SECURITY.md and CONTRIBUTING.md."
    )


def test_the_security_policy_states_its_two_refusals() -> None:
    """One tripwire for SECURITY.md: three sections, their terms, their negations (#459)."""
    assert "privately" in _security_section_body("vulnerability"), (
        "SECURITY.md's reporting section must direct reporters to disclose "
        "*privately* (e.g. GitHub private vulnerability reporting), rather than "
        "to open a public issue."
    )

    bounty = _security_section_body("bounty")
    assert _NO_BOUNTY.search(bounty), (
        "SECURITY.md must refuse a bug bounty in the body of the section, with "
        "the refusal anchored to the term. A section titled 'No bug bounty' whose "
        "text announces one is the reward this project will not pay, promised "
        "under a heading that says otherwise."
    )

    gate = _security_section_body("gate")
    assert "write access" in gate, (
        "SECURITY.md must state *who* can forge an event: anything with workspace "
        "write access. A trust boundary with no named actor is not a boundary."
    )
    assert _NOT_ATTESTATION.search(gate), (
        "SECURITY.md must *disclaim* cryptographic attestation / tamper-evidence, "
        "with the negation anchored to it. Naming attestation while leaving the "
        "guarantee open is the reading a public reader would build a security "
        "control on top of."
    )


def test_the_readme_denies_being_turnkey() -> None:
    """One tripwire for README.md: the caveat's section, its terms, its polarity (#459)."""
    section = _readme_turnkey_section()

    # `dogfood` is deliberately NOT asserted: in this section it appears only in
    # the heading, so requiring it would pin the anchor's wording a second time
    # rather than pin anything the section says.
    assert "adapt" in section, (
        "the README's turnkey section must tell the reader what to do with it: "
        "adapt the worked example, rather than install it unchanged."
    )
    assert _NOT_TURNKEY.search(section), (
        "the README's turnkey section must *deny* being turnkey, with the "
        "negation anchored to the word. A section that names turnkey software "
        "without denying it is the expectation this caveat exists to correct."
    )
