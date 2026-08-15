"""Docs consistency checks — catch stale bootstrap phrases in key docs.

Scans README.md and CLAUDE.md for phrases that indicate the repo is in a
pre-implementation state. If the harness has shipped, these should be absent.

Also enforces (DOC-3, CAL-593) that every retired spec carries an in-file dated
supersede banner, so an agent opening the file directly is not misled into
reading superseded content as live.

**#435 removed the cross-repo-execution and ssh-forwarding sections.** Both read
their invariants off ``harness.hostenv.spawn`` — the argv it built for the
Docker container — and ADR 0015 retires the container and the package that
constructed it. The mount, the ``HARNESS_WORKSPACE_ROOTS`` pin and the
ssh-agent gate they locked no longer exist to be locked. Everything else here
guards a surviving file, including the two ``--extra dev`` guards below, which
are what hold ``CONTEXT.md``'s ``commands:`` block and ``scripts/verify.sh``
together as this repo becomes a gate and nothing else.

**#435 also re-anchored the banner guard on the tree instead of an index.** Its
subject set came from a "Superseded" table inside ``SPEC.md``, and ADR 0015
deletes ``SPEC.md`` with the design it described. The set is now every tracked
``specs/retired/*.md``, which is a stronger subject than the table ever was: the
table listed the specs someone remembered to add a row for, while the directory
*is* the retired set by definition, so a spec retired without a banner is caught
on the commit that retires it rather than on the commit that indexes it.
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

#: A spec file carries a banner if one of its first lines is a blockquote of the
#: form ``> **Superseded YYYY-MM-DD** …`` (the format `hermes-control-model.md`
#: established). The date requirement is what makes it a *dated* banner.
_BANNER_RE = re.compile(r"^>\s*\*\*Superseded\s+\d{4}-\d{2}-\d{2}")

#: Only the top of the file matters — a marker buried mid-document would not warn
#: an agent who opens the file and reads the lede.
_BANNER_SCAN_LINES = 12


def _retired_specs() -> list[Path]:
    """Every tracked ``specs/retired/*.md``.

    Derived from the tracked tree, so a spec retired tomorrow is held to the
    banner rule the moment it lands. Judged over the *index* rather than the
    working tree, so an untracked scratch file next door is not a subject.
    """
    return sorted(p for p in tracked_files_under("specs/retired") if p.suffix == ".md")


def test_the_retired_spec_set_is_not_empty() -> None:
    """Guard the derivation itself: the retired tree really is populated.

    The banner check below is parametrized over a derived set, and an empty
    parametrize collects zero cases and reports ``skipped``, which reads as
    green. A wrong pathspec would therefore certify the banner rule while
    checking nothing.
    """
    names = {p.name for p in _retired_specs()}
    assert len(names) >= 10, (
        f"only {len(names)} tracked specs/retired/*.md — the derivation has "
        f"stopped finding the tree: {sorted(names)}"
    )


@pytest.mark.parametrize("spec", _retired_specs(), ids=lambda p: p.name)
def test_retired_spec_has_in_file_banner(spec: Path) -> None:
    """Every spec under ``specs/retired/`` carries a dated in-file banner.

    The directory is exempt *by category* from every retirement prose sweep in
    this suite, which is what lets these files keep describing a deleted design
    in the present tense of their own day. The banner is the condition of that
    exemption, not a formatting preference.
    """
    head = spec.read_text().splitlines()[:_BANNER_SCAN_LINES]
    assert any(_BANNER_RE.match(line) for line in head), (
        f"{spec.name} sits under specs/retired/ but has no in-file supersede "
        "banner near the top. Prepend a dated banner of the form "
        "'> **Superseded YYYY-MM-DD** — …' (see hermes-control-model.md)."
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


# --- Version-bump freshness anchor (CAL-651, AC-2) ----------------------------

FRESHNESS_HOOK = REPO_ROOT / "hooks" / "guidance-freshness.js"


def test_the_freshness_hook_names_a_record_that_exists() -> None:
    """AC-2: the SOURCE-mode freshness hook nags toward a real place.

    The freshness hook (SOURCE mode) tells an author where to record a version
    bump. If the hook points somewhere, that place must exist or the pointer is
    a dead end — which is exactly what #324 would have left behind: the hook
    named ``changelog.d/<ticket>.md`` in all three of its branches, and the
    directory is deleted.

    Since #324 there is no changelog artifact to nag for. The entry is derived
    from the commit at release (ADR 0014), so the reminder points at the commit
    body — the one destination that cannot rot, because every change has one.
    ``CHANGELOG.md`` was still a tracked root file until #435, when ADR 0015
    left nothing to release and the file went with the release path. Both
    forbidden spellings are asserted rather than one: a hook repaired by
    swapping ``changelog.d/`` for ``CHANGELOG.md`` would have satisfied the
    older form of this guard while naming a file that no longer exists.
    """
    hook = FRESHNESS_HOOK.read_text()
    assert "CHANGELOG" not in hook, (
        "hooks/guidance-freshness.js points authors at a CHANGELOG, which #435 "
        "deleted along with the release path that wrote it. The entry is the "
        "commit body (ADR 0014)."
    )
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
