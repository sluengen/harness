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


# --- ONBOARDING.md must be shipped (CAL-620) ----------------------------------
#
# RELEASING.md links to ONBOARDING.md (§Updating) as the repeatable-onboarding
# doc. A doc you reference but do not ship sends anyone who follows the pointer
# to a 404, so the repo must actually carry it.
#
# The guard judges the *committed* tree (``git ls-files``), not the working
# tree, per the CAL-619 git-aware-guard principle: an ONBOARDING.md that exists
# only on an author's disk must still fail on a clean checkout.

ONBOARDING_DOC = REPO_ROOT / "ONBOARDING.md"


def test_onboarding_md_is_tracked() -> None:
    """ONBOARDING.md is referenced across the docs; it must be a committed file."""
    assert ONBOARDING_DOC.resolve() in tracked_files_under("ONBOARDING.md"), (
        "ONBOARDING.md is referenced by RELEASING.md (§Updating), but git does "
        "not track it. Ship the onboarding doc you reference (CAL-620; the "
        "CAL-619 git-aware-guard principle)."
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
#: form ``> **Superseded YYYY-MM-DD** …`` (the format `hermes-control-model.md`
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
        "hermes-control-model.md",
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
        "form '> **Superseded YYYY-MM-DD** by …' (see hermes-control-model.md)."
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
LINEAR_SKILL = REPO_ROOT / "skills" / "linear" / "SKILL.md"

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
    text = LINEAR_SKILL.read_text()
    assert "issueUpdate" in text and "stateId" in text, (
        "skills/linear/SKILL.md no longer shows a hand-rolled issueUpdate/stateId "
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
    REPO_ROOT / "ONBOARDING.md",
    REPO_ROOT / "CONTEXT.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "BOOTSTRAP.md",
]

#: Phrases that assert a separate agents *source* repo (the two-repo world). The
#: `agents` directory (`agents/`, "agent role definitions") is never a match —
#: only "agents" bound to repo/channel/installer/source is the stale claim.
_TWO_REPO_RE = re.compile(r"agents[\s-](repo|channel|installer|source)", re.IGNORECASE)


@pytest.mark.parametrize("doc", ONE_REPO_DOCS, ids=lambda p: p.name)
def test_no_separate_agents_source_repo_claim(doc: Path) -> None:
    """AC-1: no live doc claims a separate agents *source* repo (CAL-651).

    The harness is the guidance source now; the install pulls from this repo and
    runs the in-repo installer (BOOTSTRAP.md), not an external agents repo.
    """
    if not doc.exists():
        pytest.skip(f"{doc.name} not found")
    hits = sorted({m.group(0) for m in _TWO_REPO_RE.finditer(doc.read_text())})
    assert not hits, (
        f"{doc.name} still describes a separate agents source repo: {hits!r}. "
        "The guidance repo was merged into the harness (D1/D6) — the harness is "
        "the source. Point the install at the in-repo installer (BOOTSTRAP.md) "
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


# --- Cross-repo execution (CAL-675) -------------------------------------------
#
# `/harness run` is universal across repo types: one harness checkout (+ the
# `~/bin/harness` wrapper) drives a Linear ticket in *any* repo, because the
# verbs are repo-agnostic — the wrapper mounts the target repo's CWD at
# /workspace and the verbs operate there. These guards keep that capability and
# the docs that promise it honest:
#   - the wrapper must pin HARNESS_WORKSPACE_ROOTS to the in-container /workspace
#     (a host-side value is a host path, meaningless inside, and would reject the
#     mounted repo — the exact regression a review of CAL-675 caught); and
#   - the onboarding doc must tell a consuming repo to ignore *both* run-state
#     directories (.harness/ ledger and .worktrees/ worktrees), which sit at
#     different paths.

DOCKER_README = REPO_ROOT / "docker" / "README.md"

#: The wrapper enables cross-repo execution with two moves: mount the caller's
#: CWD at /workspace, and pin the fail-closed allowlist (workspace.py, CAL-584)
#: to that same /workspace so the mounted repo is admitted.
_WRAPPER_MOUNTS_CWD_RE = re.compile(r'-v\s+"\$\(pwd\)":/workspace')
#: The fix must be a *literal* /workspace, not a forwarded host value. The
#: ``${HARNESS_WORKSPACE_ROOTS:-/workspace}`` default and a bare
#: ``-e HARNESS_WORKSPACE_ROOTS`` both forward whatever the host exported — a
#: host path the container's verbs then reject. Pin ``=/workspace`` instead.
_WRAPPER_PINS_ALLOWLIST_RE = re.compile(r"-e\s+HARNESS_WORKSPACE_ROOTS=/workspace")
_WRAPPER_FORWARDS_HOST_RE = re.compile(
    # bare `-e HARNESS_WORKSPACE_ROOTS \` (env-passthrough), or the old
    # `export HARNESS_WORKSPACE_ROOTS="${HARNESS_WORKSPACE_ROOTS:-…}"` default —
    # the optional quote after `=` is what made the original guard miss the
    # real (quoted) export line.
    r'-e\s+HARNESS_WORKSPACE_ROOTS\s*\\|HARNESS_WORKSPACE_ROOTS="?\$\{HARNESS_WORKSPACE_ROOTS'
)


def test_wrapper_pins_allowlist_to_container_workspace() -> None:
    """The cross-repo claim is backed by the documented wrapper (CAL-675).

    `/harness run` runs cross-repo only because the ``~/bin/harness`` wrapper
    (canonical text in ``docker/README.md``) mounts the caller's CWD at
    ``/workspace`` *and* sets the ``HARNESS_WORKSPACE_ROOTS`` allowlist to that
    same in-container ``/workspace`` — so the fail-closed guard in
    ``workspace.py`` (CAL-584) admits the mounted repo. The allowlist must be a
    **literal** ``/workspace``: forwarding the host's value (the old
    ``${HARNESS_WORKSPACE_ROOTS:-/workspace}`` default / bare
    ``-e HARNESS_WORKSPACE_ROOTS``) leaks a host path into the container, which
    then rejects ``/workspace`` and breaks every verb — the regression a review
    of CAL-675 caught. Lock both the mount and the pin.
    """
    text = DOCKER_README.read_text()
    assert _WRAPPER_MOUNTS_CWD_RE.search(text), (
        "docker/README.md's wrapper no longer mounts the CWD at /workspace "
        '(`-v "$(pwd)":/workspace`). That mount is what makes the verbs '
        "repo-agnostic — without it the cross-repo claim (CAL-675) is false."
    )
    assert _WRAPPER_PINS_ALLOWLIST_RE.search(text), (
        "docker/README.md's wrapper no longer pins "
        "`-e HARNESS_WORKSPACE_ROOTS=/workspace`. It must set the in-container "
        "allowlist to a literal /workspace (CAL-584/CAL-675)."
    )
    assert not _WRAPPER_FORWARDS_HOST_RE.search(text), (
        "docker/README.md's wrapper forwards the host's HARNESS_WORKSPACE_ROOTS "
        "into the container (bare `-e HARNESS_WORKSPACE_ROOTS` or a "
        "`${HARNESS_WORKSPACE_ROOTS:-…}` default). Inside the container the repo "
        "is /workspace, so a host path rejects it — pin `=/workspace` instead "
        "(CAL-675 regression)."
    )


def test_onboarding_ignores_both_run_state_dirs() -> None:
    """AC-3 (CAL-675): the onboarding doc tells a consuming repo to ignore both
    run-state directories.

    A run writes the SQLite ledger to ``<repo>/.harness/`` and its worktrees to
    ``<repo>/.worktrees/harness/`` — *different* paths. ONBOARDING step 5 must
    list both in the `.gitignore` it scaffolds, or a `git add .` after a run can
    stage worktree contents in the consuming repo (the rough edge the cross-repo
    smoke surfaced).
    """
    text = ONBOARDING_DOC.read_text()
    assert ".worktrees/" in text and ".harness/" in text, (
        "ONBOARDING.md must tell a consuming repo to gitignore both `.harness/` "
        "(ledger) and `.worktrees/` (run worktrees) — they sit at different "
        "paths, so ignoring only one leaves the other committable (CAL-675, AC-3)."
    )


# --- ssh-agent forwarding gate --------------------------------------
#
# The close verb pushes over SSH from inside the container. Docker Desktop
# bridges the host ssh-agent into the container at the fixed in-VM path
# /run/host-services/ssh-auth.sock — a path that exists ONLY inside the Docker
# VM, never on the macOS host. The wrapper must therefore NOT gate the forward on
# the host-side existence of that socket (`[[ -S /run/host-services/... ]]`):
# evaluated host-side that test is *always* false, so forwarding silently never
# enables and every `close` push falls back to the tokenized-https detour
# (mis-read for months as "this host has no ssh-agent"). Gate on the host
# actually having a reachable agent instead, and let Docker Desktop supply the
# socket at mount time.

#: The buggy *active* gate — `if [[ -S /run/host-services/ssh-auth.sock ]]`.
#: Anchored on the `if` so a prose mention of the old form (e.g. this guard's own
#: rationale, or an explanatory comment in the wrapper) is not a false positive;
#: only a live gate keying off the VM-only socket trips it.
_SSH_VM_SOCKET_TEST_RE = re.compile(
    r"if\s+\[\[\s*-S\s+/run/host-services/ssh-auth\.sock\s*\]\]"
)
#: The corrected gate keys off the host's own agent (SSH_AUTH_SOCK + ssh-add) on
#: a single line.
_SSH_HOST_AGENT_GATE_RE = re.compile(r"SSH_AUTH_SOCK[^\n]*\bssh-add\b")
#: Docker Desktop still supplies the socket — the mount must remain.
_SSH_SOCKET_MOUNT = "/run/host-services/ssh-auth.sock:/ssh-agent"


def test_wrapper_ssh_gate_keys_off_host_agent() -> None:
    """The documented wrapper gates ssh-agent forwarding on the *host* agent, not
    on the VM-only magic socket.

    Testing `[[ -S /run/host-services/ssh-auth.sock ]]` host-side is always false
    — that path lives inside the Docker VM, never on the macOS host — so the old
    gate silently disabled forwarding and forced the tokenized-https fallback on
    every close. The fix keys the gate off the host's own agent and lets Docker
    Desktop provide the socket at mount time; the mount itself must stay.
    """
    text = DOCKER_README.read_text()
    assert not _SSH_VM_SOCKET_TEST_RE.search(text), (
        "docker/README.md's wrapper still gates ssh forwarding on "
        "`[[ -S /run/host-services/ssh-auth.sock ]]`. That socket exists only "
        "inside the Docker VM, so the host-side test is always false and "
        "forwarding never enables. Gate on the host agent "
        "(`[[ -n \"${SSH_AUTH_SOCK:-}\" ]] && ssh-add -l`) instead."
    )
    assert _SSH_HOST_AGENT_GATE_RE.search(text), (
        "docker/README.md's wrapper no longer gates on the host's own agent "
        "(SSH_AUTH_SOCK + ssh-add). The forward must enable when the host has a "
        "reachable agent holding a key."
    )
    assert _SSH_SOCKET_MOUNT in text, (
        "docker/README.md's wrapper no longer mounts "
        f"`{_SSH_SOCKET_MOUNT}`. Docker Desktop supplies the host agent at that "
        "in-VM path at mount time — the mount must remain."
    )
