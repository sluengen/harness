"""Docs consistency checks — catch stale bootstrap phrases in key docs.

Scans README.md and CLAUDE.md for phrases that indicate the repo is in a
pre-implementation state. If the harness has shipped, these should be absent.

Also enforces (DOC-3, CAL-593) that every spec the SPEC.md index marks as
superseded carries an in-file dated supersede banner, so an agent opening the
file directly is not misled into reading retired-engine content as live.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent

BOOTSTRAP_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
]

STALE_PHRASES = [
    "Pre-implementation",
    "pre-implementation",
]


@pytest.mark.parametrize("doc", BOOTSTRAP_DOCS, ids=lambda p: p.name)
def test_no_stale_bootstrap_phrases(doc: Path) -> None:
    """Bootstrap docs must not contain pre-implementation placeholder language."""
    if not doc.exists():
        pytest.skip(f"{doc.name} not found")
    text = doc.read_text()
    found = [phrase for phrase in STALE_PHRASES if phrase in text]
    assert not found, (
        f"{doc.name} contains stale phrase(s): {found!r}. "
        "Remove or replace with language that reflects the shipped state."
    )


# --- Supersede banners (DOC-3, CAL-593) ---------------------------------------

SPEC_INDEX = REPO_ROOT / "SPEC.md"

#: Header of the SPEC.md index table that lists superseded specs.
_SUPERSEDED_TABLE_MARKER = "**Superseded (retired deterministic engine"

#: A spec file carries a banner if one of its first lines is a blockquote of the
#: form ``> **Superseded YYYY-MM-DD** …`` (the format `hermes-orchestration.md`
#: established). The date requirement is what makes it a *dated* banner.
_BANNER_RE = re.compile(r"^>\s*\*\*Superseded\s+\d{4}-\d{2}-\d{2}")

#: Only the top of the file matters — a marker buried mid-document would not warn
#: an agent who opens the file and reads the lede.
_BANNER_SCAN_LINES = 12


def _superseded_specs() -> list[Path]:
    """Spec files the SPEC.md index marks as superseded.

    Parses the "Superseded" table rather than hard-coding a list, so a spec
    added to (or removed from) the index is automatically held to the same rule.
    """
    text = SPEC_INDEX.read_text()
    lines = text.splitlines()
    specs: list[Path] = []
    in_table = False
    for line in lines:
        if _SUPERSEDED_TABLE_MARKER in line:
            in_table = True
            continue
        if not in_table:
            continue
        if in_table and not line.lstrip().startswith("|"):
            # Table ends at the first non-row line after it has begun.
            if specs:
                break
            continue
        for match in re.finditer(r"specs/([A-Za-z0-9_-]+\.md)", line):
            candidate = REPO_ROOT / "specs" / match.group(1)
            if candidate not in specs:
                specs.append(candidate)
    return specs


def test_superseded_table_is_parseable() -> None:
    """Guard the parser itself: the index must list the known superseded specs."""
    names = {p.name for p in _superseded_specs()}
    assert {
        "engine-executor.md",
        "engine-loop.md",
        "ai-node.md",
        "script-node.md",
        "workflow-schema.md",
        "build-workflow.md",
        "cli.md",
        "hermes-orchestration.md",
    } <= names


@pytest.mark.parametrize(
    "spec", _superseded_specs(), ids=lambda p: p.name
)
def test_superseded_spec_has_in_file_banner(spec: Path) -> None:
    """Every spec marked superseded in the index carries a dated in-file banner."""
    assert spec.exists(), f"{spec} listed in SPEC.md index but does not exist"
    head = spec.read_text().splitlines()[:_BANNER_SCAN_LINES]
    assert any(_BANNER_RE.match(line) for line in head), (
        f"{spec.name} is marked superseded in the SPEC.md index but has no "
        "in-file supersede banner near the top. Prepend a dated banner of the "
        "form '> **Superseded YYYY-MM-DD** by …' (see hermes-orchestration.md)."
    )


# --- D5 routing-discipline scope (ADH-1, CAL-596) -----------------------------
#
# The architecture-principles "Routing discipline" principle once claimed that
# *every* git and ticket mutation goes through a verb. That overstated the
# guarantee: the agent-led backup flow (`/start` → `/review` → `/ship`)
# hand-rolls a Linear lifecycle transition outside the verbs and outside the
# `runs` ledger, by design. These two tests pin the prose to that reality —
# one anchors the reality (the backup flow really does hand-roll the
# transition), the other forbids the unqualified claim from creeping back.

ARCH_PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"
LINEAR_SYNC = REPO_ROOT / "skills" / "linear-sync.md"

#: The exact unqualified assertion ADH-1 (CAL-596) flagged as overstated.
_UNQUALIFIED_D5_CLAIM = "Every git and ticket mutation goes through a verb."


def _routing_discipline_section() -> str:
    """Body of the '### Routing discipline' subsection of the principles spec."""
    text = ARCH_PRINCIPLES.read_text()
    marker = "### Routing discipline"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    # The section runs until the next heading of equal-or-higher level.
    end = re.search(r"\n#{1,3} ", rest)
    return rest[: end.start()] if end else rest


def test_backup_flow_hand_rolls_linear_transition() -> None:
    """The reality ADH-1 documents: the agent-led backup flow hand-rolls a Linear
    lifecycle transition outside the verbs. If this stops being true, the
    run-lifecycle carve-out in architecture-principles.md is stale — revisit it.
    """
    text = LINEAR_SYNC.read_text()
    assert "issueUpdate" in text and "stateId" in text, (
        "skills/linear-sync.md no longer shows a hand-rolled issueUpdate/stateId "
        "transition. Re-check whether architecture-principles.md still needs its "
        "run-lifecycle carve-out (ADH-1, CAL-596)."
    )


def test_routing_discipline_scoped_to_run_lifecycle() -> None:
    """ADH-1: the routing-discipline principle must scope its guarantee to the
    run lifecycle, not claim that *every* ticket mutation goes through a verb —
    the backup flow is a standing counterexample."""
    section = _routing_discipline_section()
    assert _UNQUALIFIED_D5_CLAIM not in section, (
        "architecture-principles.md 'Routing discipline' still makes the "
        f"unqualified claim {_UNQUALIFIED_D5_CLAIM!r}. The agent-led backup flow "
        "hand-rolls a Linear transition outside the verbs, so this overstates the "
        "guarantee — scope it to run-lifecycle mutations (ADH-1, CAL-596)."
    )
    assert "run-lifecycle" in section or "run lifecycle" in section, (
        "architecture-principles.md 'Routing discipline' must scope the guarantee "
        "to run-lifecycle mutations (ADH-1, CAL-596)."
    )
