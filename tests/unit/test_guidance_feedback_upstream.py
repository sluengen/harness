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

These guards pin that the rule actually landed with the elements the
proposal's resolved decisions require, not just a placeholder mention.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
MIRRORS = [REPO_ROOT / name for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")]
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
REGISTRY = REPO_ROOT / "registry.yaml"
PROPOSAL = REPO_ROOT / "specs" / "proposals" / "guidance-feedback-upstream.md"


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


def test_names_the_trigger() -> None:
    body = _updating_guidance_section().lower()
    assert "defect" in body and "friction" in body and "idea" in body, (
        "process/harness.md's 'Updating the guidance' section must name the "
        "trigger — a guidance defect, process friction, or feature idea "
        "(#205 AC-1)."
    )


def test_names_search_existing_issues_first() -> None:
    body = _updating_guidance_section().lower()
    assert "search existing issues" in body, (
        "the rule must say to search existing issues first, mitigating "
        "duplicate/noise filing (#205 AC-1, proposal Risks)."
    )


def test_names_source_repo_resolution_never_hardcoded() -> None:
    body = _updating_guidance_section()
    assert ".guidance-lock.yaml" in body and "source.repo" in body, (
        "the rule must resolve the upstream repo from .guidance-lock.yaml's "
        "source.repo, never hardcode an owner/repo (#205 AC-1)."
    )
    assert "never hardcod" in body.lower(), (
        "the rule must explicitly say never to hardcode an owner/repo "
        "(#205 AC-1, proposal Risks: fork attribution)."
    )


def test_names_draft_and_surface_posture() -> None:
    body = _updating_guidance_section().lower()
    assert "draft a github issue" in body, (
        "the rule must say to draft a GitHub issue, not send one directly "
        "(#205 AC-1, resolved decision: draft and surface)."
    )
    assert "operator" in body and (
        "review and send" in body or "surface" in body
    ), (
        "the rule must surface the draft to the operator to review and send "
        "— no unattended public write (#205 AC-1)."
    )


def test_names_scope_guard() -> None:
    body = _updating_guidance_section().lower()
    assert "proprietary" in body, (
        "the rule must scope the issue body to the guidance itself, never "
        "the consumer's proprietary code (#205 AC-1)."
    )


def test_names_source_repo_fix_and_file_case() -> None:
    body = _updating_guidance_section().lower()
    assert "fix the defect at source" in body and "public record" in body, (
        "the rule must fold the source-repo case to fix-at-source AND file "
        "the issue — the issue is the public record, not a substitute for "
        "fixing (#205 AC-1, resolved decision)."
    )


def test_names_no_lock_file_degradation() -> None:
    body = _updating_guidance_section()
    assert "no `.guidance-lock.yaml`" in body or "no .guidance-lock.yaml" in body, (
        "the rule must degrade gracefully when there is no "
        ".guidance-lock.yaml or its source.repo does not resolve — surface "
        "to the operator instead of guessing a URL (#205 AC-1, proposal "
        "Risks: consumer without a lock file)."
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


def test_process_harness_version_bumped_from_0_4_8() -> None:
    header = re.search(r"guidance:process-harness@([\d.]+)", PROCESS_DOC.read_text())
    assert header and header.group(1) != "0.4.8", (
        "process/harness.md's guidance: header must be bumped from 0.4.8 "
        "since this ticket changes its content (#205 AC-3)."
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


# --- AC-4: the proposal's breakdown item 1 is marked shipped / linked -------


def test_proposal_breakdown_item_marked_shipped_or_linked() -> None:
    text = PROPOSAL.read_text()
    status = re.search(r"^status:\s*(\S+)", text, re.MULTILINE)
    assert status, "the proposal must carry a status: field."
    linked_in_breakdown = "#205" in _section(text, "Breakdown")
    assert status.group(1) == "shipped" or linked_in_breakdown, (
        "specs/proposals/guidance-feedback-upstream.md's breakdown item 1 "
        "must be marked shipped (status: shipped) or linked to #205 (#205 "
        "AC-4)."
    )
