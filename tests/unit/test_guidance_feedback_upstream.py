"""#205 — ship the guidance-feedback-upstream rule (proposal breakdown item 1).

*Source:* ``specs/proposals/guidance-feedback-upstream.md`` (accepted
2026-07-20), breakdown item 1. The tracking ticket (CAL-1199, Linear-era) got
diverted into an unrelated fix and the doc edit was never actually shipped —
confirmed still missing at ``process/harness.md:108`` / ``registry.yaml:128``
(``guidance:process-harness@0.4.7``, later 0.4.8 from an unrelated #202 bump).

This ticket lands the rule itself:

* ``process/harness.md``'s "Updating the guidance" section documents the
  GitHub-issue routing rule (trigger, ``source.repo`` resolution, scope guard,
  draft-and-surface posture, source-repo fix-and-file case, no-lock-file
  degradation) — mirrored byte-identically into ``AGENTS.md`` / ``CLAUDE.md``
  / ``GEMINI.md``.
* ``commands/update-guidance.md`` carries a one-line cross-reference next to
  its existing LOCAL-edit "suggest pushing upstream" branch.
* ``process/harness.md``'s ``guidance:`` header and its ``registry.yaml``
  entry are bumped consistently (registry self-version bumped too, since its
  own header + ``files:`` entry move together).
* the proposal's breakdown item 1 is marked shipped / linked to this issue.

**What this module asserts (#459).** Structural correspondence, plus one
tripwire.

*Correspondence, unchanged* — the three mirrors are byte-identical to
``process/harness.md``; the process doc's header matches its ``registry.yaml``
entry; ``registry.yaml``'s own header matches its ``meta:`` self-entry; and
``commands/update-guidance.md`` cross-references the rule next to its
LOCAL-edit branch.

*One tripwire* — the ``## Updating the guidance`` section, read as its own
slice, names the artifacts the rule cannot be stated without and carries the
negation bound to hardcoding. The seven ``test_names_*`` functions it replaces
were one rule-home pinned seven ways, each on a literal phrase
(``"search existing issues"``, ``"draft a github issue"``, ``"fix the defect
at source"``…): brittle to any rewording that preserved the rule and blind to
an edit that kept the bytes while inverting it (``code-quality`` Part C → *A
guard over prose owns structure and negative space, never meaning*; ADR 0016).

*Two guards retired.* ``test_process_harness_version_bumped_from_0_4_8``
froze a shipped version number, which the header⇄registry parity assertion
beside it already subsumes and which only ever needs hand-editing on a
legitimate bump. ``test_proposal_breakdown_item_marked_shipped_or_linked``
read a decided proposal's ``status:`` field — a museum record with one commit
in its history and no regression to catch.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
MIRRORS = [REPO_ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")]
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
REGISTRY = REPO_ROOT / "registry.yaml"

_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def _registry_entry(path: str) -> str:
    pattern = re.escape(path) + r":\s*\{[^}]*\}"
    m = re.search(pattern, REGISTRY.read_text())
    assert m, f"registry.yaml must have a files: entry for {path}"
    return m.group(0)


def _section(text: str, heading_substr: str) -> str:
    """The body of the heading line containing ``heading_substr`` up to the
    next heading of the same-or-higher level."""
    lines = text.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        if line.startswith("#") and heading_substr in line:
            start = i
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""
    body: list[str] = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            this_level = len(line) - len(line.lstrip("#"))
            if this_level <= level:
                break
        body.append(line)
    return "\n".join(body)


def _updating_guidance_section() -> str:
    return _section(PROCESS_DOC.read_text(), "Updating the guidance")


# --- AC-1: the rule's required elements are in "Updating the guidance" ------


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of this module's #459
    mutation table surfaced exactly that: an inverted clause survived on a
    negation belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


def test_updating_guidance_routes_feedback_to_the_recorded_source() -> None:
    """Tripwire — the section routes upstream feedback without guessing a URL.

    Terms the rule cannot be stated without: ``.guidance-lock.yaml`` and
    ``source.repo`` (where the destination is resolved from), ``draft`` (what
    an agent produces rather than sends), ``operator`` (who sends it), and
    ``proprietary`` (the scope bound on the body). Polarity: the sentence
    naming hardcoding carries a negation — the upstream repo is resolved,
    *never* hardcoded. That direction is the whole fork-attribution risk the
    proposal named, and it is invisible to term co-occurrence: a section
    telling an agent to hardcode the owner/repo names every term above.
    """
    body = _updating_guidance_section()
    lowered = body.lower()
    for term in (".guidance-lock.yaml", "source.repo", "draft", "operator", "proprietary"):
        assert term in lowered, (
            "process/harness.md's 'Updating the guidance' section must state the "
            f"upstream-routing rule in terms of {term!r} (#205 AC-1)."
        )
    hardcoded = [s for s in _sentences(lowered) if re.search(r"hardcod", s)]
    assert hardcoded, (
        "the rule must say something about hardcoding the upstream repo "
        "(#205 AC-1, proposal Risks: fork attribution)."
    )
    assert any(_NEGATION.search(s) for s in hardcoded), (
        "the source.repo resolution must carry its negation — resolved from the "
        "lock file, never hardcoded. Without it this guard reads the same green "
        "on prose that told an agent to hardcode an owner/repo (#205 AC-1)."
    )


# --- AC-2: commands/update-guidance.md cross-references the rule ------------


def test_update_guidance_cross_references_the_rule() -> None:
    text = UPDATE_GUIDANCE.read_text()
    local_idx = text.index("suggest pushing")
    ref_idx = text.find("Updating the guidance", local_idx)
    assert ref_idx != -1, (
        "commands/update-guidance.md must carry a one-line cross-reference "
        "to process/harness.md's 'Updating the guidance' section, next to "
        "its existing LOCAL-edit 'suggest pushing upstream' branch (#205 "
        "AC-2)."
    )


# --- AC-3: header/registry bump, mirrors re-derived and byte-identical ------


def test_mirrors_carry_the_same_feedback_rule() -> None:
    canonical = PROCESS_DOC.read_text()
    for mirror in MIRRORS:
        assert mirror.read_text() == canonical, (
            f"{mirror.relative_to(REPO_ROOT)} must be byte-identical to "
            "process/harness.md, including the new guidance-feedback-"
            "upstream rule (#205 AC-3)."
        )


def test_process_harness_header_matches_registry() -> None:
    header = re.search(r"guidance:process-harness@([\d.]+)", PROCESS_DOC.read_text())
    assert header, "process/harness.md must carry a guidance:process-harness@x.y.z header."
    entry = _registry_entry("process/harness.md")
    registry_version = re.search(r"version:\s*([\d.]+)", entry).group(1)
    assert header.group(1) == registry_version, (
        f"process/harness.md header {header.group(1)!r} must match "
        f"registry.yaml's {registry_version!r} (#205 AC-3)."
    )


def test_registry_self_version_header_matches_meta_entry() -> None:
    """registry.yaml itself changes in this ticket (the files: entry for
    process/harness.md moves), so its own header and meta: self-entry must be
    bumped together — the three-place self-version trap (ticks #94-#97)."""
    text = REGISTRY.read_text()
    header = re.search(r"#\s*guidance:registry@([\d.]+)", text)
    assert header, "registry.yaml must carry its own `# guidance:registry@x.y.z` header."
    meta_entry = re.search(r"registry\.yaml:\s*\{[^}]*\}", text)
    assert meta_entry, "registry.yaml's meta: block must list its own self-entry."
    meta_version = re.search(r"version:\s*([\d.]+)", meta_entry.group(0)).group(1)
    assert header.group(1) == meta_version, (
        f"registry.yaml header {header.group(1)!r} must match its own meta: "
        f"self-entry {meta_version!r} (#205 AC-3)."
    )
