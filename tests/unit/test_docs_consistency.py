"""Docs consistency checks — catch stale bootstrap phrases in key docs.

Scans README.md and CLAUDE.md for phrases that indicate the repo is in a
pre-implementation state. If the harness has shipped, these should be absent.

Also enforces (DOC-3, CAL-593) that every spec the SPEC.md index marks as
superseded carries an in-file dated supersede banner, so an agent opening the
file directly is not misled into reading retired-engine content as live.

**#435 removed the cross-repo-execution and ssh-forwarding sections.** Both read
their invariants off ``harness.hostenv.spawn`` — the argv it built for the
Docker container — and ADR 0015 retires the container and the package that
constructed it. The mount, the ``HARNESS_WORKSPACE_ROOTS`` pin and the
ssh-agent gate they locked no longer exist to be locked. Everything else here
guards a surviving file, including the two ``--extra dev`` guards below, which
are what hold ``CONTEXT.md``'s ``commands:`` block and ``scripts/verify.sh``
together as this repo becomes a gate and nothing else.
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
        "spec-engine.md",  # SPEC.md's own retired-engine sections (CAL-1010)
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
    """AC-2: the changelog exists and the SOURCE-mode freshness hook nags toward it.

    The freshness hook (SOURCE mode) tells an author where to record a version
    bump. If the hook points somewhere, that place must exist or the pointer is
    a dead end — which is exactly what #324 would have left behind: the hook
    named ``changelog.d/<ticket>.md`` in all three of its branches, and the
    directory is deleted.

    Since #324 there is no changelog artifact to nag for. The entry is derived
    from the commit at release (ADR 0014), so the reminder points at the commit
    body. ``CHANGELOG.md`` itself remains a tracked root file: it is the
    released history the release assembly writes into, and naming *it* would
    send an author to the one file the ratchet forbids them to grow.
    """
    assert CHANGELOG.resolve() in tracked_files_under("CHANGELOG.md"), (
        "CHANGELOG.md must be a committed root file — it holds the released "
        "history the release assembly writes into (CAL-651, AC-2)."
    )
    hook = FRESHNESS_HOOK.read_text()
    assert "changelog.d" not in hook, (
        "hooks/guidance-freshness.js still points authors at changelog.d/, "
        "which #324 deleted. A reminder naming a path that does not exist is "
        "worse than none: it sends an author to create the directory the "
        "deletion removed."
    )
    assert "commit body" in hook, (
        "hooks/guidance-freshness.js must tell an author where the changelog "
        "entry goes. Since #324 that is the commit body, which the release "
        "assembles from (ADR 0014) — without it the bump reminder names a "
        "version to change and no record to change it in (CAL-651, AC-2)."
    )


# --- CONTEXT.md gate commands must match scripts/verify.sh (CAL-1003) ----------
#
# CONTEXT.md is the agent-facing file of record for how to run this repo's gate.
# Its `commands:` block once listed the bare `uv run pytest` / `uv run ruff …` /
# `uv run mypy …` forms — all missing `--extra dev`, while scripts/verify.sh (the
# canonical gate) runs every step with `uv run --extra dev`. Bare `uv run pytest`
# is a documented failure mode in this repo (dependency resolution pulls a typer
# version where a surface test fails for all commands), so the file of record was
# teaching the failure mode. These guards pin CONTEXT.md's gate invocations to the
# known-good `--extra dev` form that verify.sh — the canonical gate — uses, so the
# two cannot drift.

CONTEXT_MD = REPO_ROOT / "CONTEXT.md"
VERIFY_SH = REPO_ROOT / "scripts" / "verify.sh"

#: A `uv run` invocation — the form that needs `--extra dev` to resolve the dev
#: dependency group. `uv sync --extra dev` is a different subcommand and already
#: carries the flag, so the guard keys on `uv run` specifically (it must not flag
#: the `install: "uv sync --extra dev"` command).
_UV_RUN_RE = re.compile(r"\buv run\b")
_UV_RUN_EXTRA_DEV_RE = re.compile(r"\buv run --extra dev\b")


def _context_commands() -> dict[str, str]:
    """Parse CONTEXT.md's ``commands:`` block into ``{name: invocation}``.

    The block lives inside the front-matter ```yaml fence as ``name: "value"``
    lines; parsed by regex (there is no yaml dependency) the same way the other
    doc guards here read these files. The block ends at the next unindented key.
    """
    cmds: dict[str, str] = {}
    in_block = False
    for line in CONTEXT_MD.read_text().splitlines():
        if re.match(r"^commands:\s*$", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^\S", line):  # next top-level key ends the block
                break
            m = re.match(r'^\s+(\w+):\s+"([^"]*)"', line)
            if m:
                cmds[m.group(1)] = m.group(2)
    return cmds


def test_verify_sh_uv_run_steps_use_extra_dev() -> None:
    """Anchor: scripts/verify.sh runs every ``uv run`` step with ``--extra dev``.

    This is the known-good form CONTEXT.md's gate commands are pinned to below.
    If the canonical gate itself stopped using ``--extra dev``, the parity target
    would be wrong — anchor the premise here (CAL-1003).
    """
    uv_runs = [
        ln.strip()
        for ln in VERIFY_SH.read_text().splitlines()
        if _UV_RUN_RE.search(ln)
    ]
    assert uv_runs, "scripts/verify.sh has no `uv run` steps — parser or gate changed."
    offenders = [ln for ln in uv_runs if not _UV_RUN_EXTRA_DEV_RE.search(ln)]
    assert not offenders, (
        "scripts/verify.sh has `uv run` steps missing `--extra dev`: "
        f"{offenders!r}. The gate's known-good form is `uv run --extra dev` "
        "(CAL-1003)."
    )


def test_context_gate_commands_use_extra_dev() -> None:
    """CONTEXT.md's ``uv run`` gate commands carry ``--extra dev``, matching verify.sh.

    Bare ``uv run pytest`` / ``uv run ruff …`` / ``uv run mypy …`` are a
    documented failure mode (dependency resolution pulls a typer version where a
    surface test fails for all commands). CONTEXT.md is the agent-facing file of
    record — its gate invocations must be the known-good ``--extra dev`` forms the
    canonical gate (scripts/verify.sh) uses, or the file teaches the failure mode
    (CAL-1003).
    """
    cmds = _context_commands()
    assert cmds, "Could not parse CONTEXT.md `commands:` block — parser drifted."
    offenders = {
        name: inv
        for name, inv in cmds.items()
        if _UV_RUN_RE.search(inv) and not _UV_RUN_EXTRA_DEV_RE.search(inv)
    }
    assert not offenders, (
        "CONTEXT.md `commands:` block has `uv run` invocations missing "
        f"`--extra dev`: {offenders!r}. Bare `uv run` pulls a typer version where "
        "a surface test fails for all commands — match scripts/verify.sh's "
        "`uv run --extra dev` form (CAL-1003)."
    )


# --- Hermes is design-only, not a built trigger (CAL-1009) --------------------
#
# The README once presented Hermes as a live trigger equal to `/harness run` —
# a bullet ("the autonomous dispatcher occupying the same trigger slot") and an
# ASCII diagram (`trigger ( /harness run CAL-42 | Hermes )`). But Hermes was
# never built: its launcher was removed in CAL-712 and the design is retired to
# specs/retired/hermes-orchestration.md. A reader must not mistake it for a
# shipped trigger. Wherever the README names Hermes, a design-only caveat must
# sit nearby (the same proximity-guard idiom the other doc checks here use).

README_MD = REPO_ROOT / "README.md"

#: Tokens that mark a Hermes mention as not-built. Lower-cased match.
_HERMES_CAVEAT_TOKENS = ("design-only", "not built", "not yet built", "retired")

#: Chars scanned on each side of a "Hermes" mention for a caveat token. Wide
#: enough to let one caveat cover the adjacent bullet + diagram mentions.
_HERMES_CAVEAT_WINDOW = 600


def test_readme_does_not_present_hermes_as_built() -> None:
    """Every README mention of Hermes carries a design-only caveat nearby.

    Hermes is design-only — the launcher was removed (CAL-712) and the design is
    retired (specs/retired/hermes-orchestration.md). The README must not present
    it as a live/built trigger equal to `/harness run` (CAL-1009).
    """
    lowered = README_MD.read_text().lower()
    uncaveated: list[int] = []
    idx = lowered.find("hermes")
    while idx != -1:
        window = lowered[
            max(0, idx - _HERMES_CAVEAT_WINDOW) : idx + _HERMES_CAVEAT_WINDOW
        ]
        if not any(tok in window for tok in _HERMES_CAVEAT_TOKENS):
            uncaveated.append(idx)
        idx = lowered.find("hermes", idx + len("hermes"))
    assert not uncaveated, (
        "README.md mentions Hermes without a design-only caveat nearby "
        f"(char offsets {uncaveated}). Hermes was never built — the launcher was "
        "removed in CAL-712 and the design is retired to "
        "specs/retired/hermes-orchestration.md. Caveat every mention as "
        "design-only, not a live trigger (CAL-1009)."
    )

