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

from tests._gitutil import tracked_files_under

REPO_ROOT = Path(__file__).parent.parent.parent

BOOTSTRAP_DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "CLAUDE.md",
]

STALE_PHRASES = [
    "Pre-implementation",
    "pre-implementation",
]


# --- BOOTSTRAP.md must be shipped (CAL-620) -----------------------------------
#
# CLAUDE.md / AGENTS.md / GEMINI.md / RELEASING.md all link to BOOTSTRAP.md as
# the repeatable-onboarding doc. A doc you reference but do not ship sends anyone
# who follows the pointer to a 404, so the repo must actually carry it.
#
# The guard judges the *committed* tree (``git ls-files``), not the working
# tree, per the CAL-619 git-aware-guard principle: a BOOTSTRAP.md that exists
# only on an author's disk must still fail on a clean checkout.

BOOTSTRAP_DOC = REPO_ROOT / "BOOTSTRAP.md"


def test_bootstrap_md_is_tracked() -> None:
    """BOOTSTRAP.md is referenced across the docs; it must be a committed file."""
    assert BOOTSTRAP_DOC.resolve() in tracked_files_under("BOOTSTRAP.md"), (
        "BOOTSTRAP.md is referenced by CLAUDE.md / AGENTS.md / GEMINI.md / "
        "RELEASING.md, but git does not track it. Ship the onboarding doc you "
        "reference (CAL-620; the CAL-619 git-aware-guard principle)."
    )


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
        # A superseded row may point at a doc re-homed under specs/retired/
        # (CAL-661) or still at the top level of specs/.
        for match in re.finditer(r"specs/((?:retired/)?[A-Za-z0-9_-]+\.md)", line):
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
LINEAR_SYNC = REPO_ROOT / "skills" / "linear-sync" / "SKILL.md"

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
        "skills/linear-sync/SKILL.md no longer shows a hand-rolled issueUpdate/stateId "
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


# --- One-repo source model (CAL-651) ------------------------------------------
#
# The guidance repo was merged into the harness: the harness *is* the guidance
# source (Decision: "Merge the guidance repo into the harness", D1/D6). The live
# operational docs must therefore not describe a *separate* agents source repo
# the install pulls from — that two-repo framing is stale.

#: Operational docs an onboarding agent reads as current fact. CHANGELOG.md is
#: excluded on purpose: it is a dated history and legitimately records the
#: agents-repo *retirement* as a past event. specs/ and assessments/ are decision
#: and audit records, likewise historical.
ONE_REPO_DOCS = [
    REPO_ROOT / "BOOTSTRAP.md",
    REPO_ROOT / "CONTEXT.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "INSTALLER.md",
]

#: Phrases that assert a separate agents *source* repo (the two-repo world). The
#: `agents` directory (`agents/`, "agent role definitions") is never a match —
#: only "agents" bound to repo/channel/installer/source is the stale claim.
_TWO_REPO_RE = re.compile(r"agents[\s-](repo|channel|installer|source)", re.IGNORECASE)


@pytest.mark.parametrize("doc", ONE_REPO_DOCS, ids=lambda p: p.name)
def test_no_separate_agents_source_repo_claim(doc: Path) -> None:
    """AC-1: no live doc claims a separate agents *source* repo (CAL-651).

    The harness is the guidance source now; the install pulls from this repo and
    runs the in-repo installer (INSTALLER.md), not an external agents repo.
    """
    if not doc.exists():
        pytest.skip(f"{doc.name} not found")
    hits = sorted({m.group(0) for m in _TWO_REPO_RE.finditer(doc.read_text())})
    assert not hits, (
        f"{doc.name} still describes a separate agents source repo: {hits!r}. "
        "The guidance repo was merged into the harness (D1/D6) — the harness is "
        "the source. Point the install at the in-repo installer (INSTALLER.md) "
        "and drop the agents-repo framing (CAL-651, AC-1)."
    )


# --- CHANGELOG freshness anchor (CAL-651, AC-2) -------------------------------

CHANGELOG = REPO_ROOT / "CHANGELOG.md"
FRESHNESS_HOOK = REPO_ROOT / "hooks" / "guidance-freshness.js"


def test_changelog_present_and_referenced_by_freshness_hook() -> None:
    """AC-2: CHANGELOG.md exists and the SOURCE-mode freshness hook nags toward it.

    The freshness hook (SOURCE mode) tells an author to record a version bump in
    CHANGELOG.md. If the hook points there, the file must exist or the pointer is
    a dead end.
    """
    assert CHANGELOG.resolve() in tracked_files_under("CHANGELOG.md"), (
        "CHANGELOG.md must be a committed root file — the SOURCE-mode freshness "
        "hook nags authors toward it (CAL-651, AC-2)."
    )
    assert "CHANGELOG.md" in FRESHNESS_HOOK.read_text(), (
        "hooks/guidance-freshness.js no longer references CHANGELOG.md. The "
        "SOURCE-mode bump reminder must point authors at the changelog (CAL-651, "
        "AC-2)."
    )
