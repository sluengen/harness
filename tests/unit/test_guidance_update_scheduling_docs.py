"""CAL-1120 — sequenced per-repo ``update-guidance`` jobs are documented.

Guidance propagation across repos is the sibling routine the promotion-routine
section (CAL-1119) explicitly defers to: after a harness release makes a new
guidance version available, each consuming repo runs its **own** scheduled
``/update-guidance`` job, gates the result with its **own** verify gate, and
promotes the update through its **own** ``dev → staging`` promotion path — or
escalates. The scheduler/orchestrator fires those jobs in sequence; the harness
supplies only per-repo promotion mechanics. It is deliberately **not** one
monolithic fleet-wide harness operation (proposal ``local-promotion-steward``
D6 / breakdown item 9).

The routine guidance lives in the operational runbook (``RUNBOOK.md``, the home
of the harness's own loops), as a sibling section to the promotion routine.
These tests are the executable form of the acceptance criteria and the **drift
guard** that keeps the prose tied to real sources: the documented command is
pinned to the live ``commands/update-guidance.md`` surface, so renaming or
removing the command fails this gate until the runbook is updated too.

* **AC-1 — per-repo jobs and their sequencing** are described.
* **AC-2 — each repo uses its own gate and its own promotion path** (``dev →
  staging``), naming the real ``/update-guidance`` command.
* **AC-3 — the failure policy is explicit**: a failing repo creates/updates a
  ticket carrying the repo, the guidance version, the gate output, and the next
  action, and the chain continues/stops per policy rather than wedging silently.
* **AC-4 — no monolithic fleet-wide harness operation**: the sequencing lives in
  the outer scheduler/orchestrator, and the doc frames a fleet-wide harness
  operation as the thing to avoid.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "RUNBOOK.md"
_UPDATE_GUIDANCE_CMD = _REPO_ROOT / "commands" / "update-guidance.md"


def _runbook() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


def _guidance_section() -> str:
    """The ``RUNBOOK.md`` section documenting the guidance-update routine.

    Located by the first ``## `` heading whose text mentions **both** "guidance"
    and "update" (case-insensitive), sliced up to the next ``## `` heading or end
    of file. The promotion-routine heading mentions neither word, so this cannot
    accidentally match it.
    """
    text = _runbook()
    headings = list(re.finditer(r"^## .*$", text, re.MULTILINE))
    for i, h in enumerate(headings):
        head = h.group(0).lower()
        if "guidance" in head and "update" in head:
            start = h.start()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            return text[start:end]
    raise AssertionError(
        "RUNBOOK.md has no '## …guidance…update…' section documenting the "
        "per-repo update-guidance routine"
    )


def _normalized_prose() -> str:
    """The guidance section, lowercased with runs of whitespace collapsed to one
    space — so a phrase check is insensitive to markdown's non-semantic soft
    line-wraps (``fleet-\\nwide`` reads as ``fleet-wide``)."""
    return re.sub(r"\s+", " ", _guidance_section().lower())


def test_guidance_section_exists() -> None:
    """The routine has a home: a top-level guidance-update section in the runbook."""
    section = _guidance_section()
    assert len(section.splitlines()) > 10, (
        "the guidance-update section is a stub — it must document the full routine"
    )


def test_ac1_describes_per_repo_jobs_and_sequencing() -> None:
    """AC-1 — per-repo jobs and their sequencing are described."""
    prose = _normalized_prose()
    assert re.search(r"per-repo|per repo|each repo|each consuming repo", prose), (
        "AC-1: the section does not describe per-repo update-guidance jobs"
    )
    assert re.search(r"sequence|sequenced|in sequence|one after|in turn", prose), (
        "AC-1: the section does not describe the jobs' sequencing"
    )


def test_ac2_own_gate_and_own_promotion_path() -> None:
    """AC-2 — each repo uses its own gate and its own ``dev → staging`` promotion path."""
    prose = _normalized_prose()
    assert "gate" in prose, "AC-2: the section does not mention each repo's gate"
    # Each repo promotes through its own promotion path — the same dev → staging
    # topology the promotion routine documents (tolerate either arrow style).
    assert re.search(r"dev\s*(?:->|→)\s*staging", prose), (
        "AC-2: the section does not name each repo's own dev → staging promotion path"
    )
    assert re.search(r"own gate|its own .*gate|own .*promotion|its own .*promotion", prose), (
        "AC-2: the section does not state each repo uses its OWN gate and promotion path"
    )


def test_ac2_names_the_real_update_guidance_command() -> None:
    """AC-2 (drift guard) — the doc names the live ``/update-guidance`` command.

    Pinned to the real surface: if ``commands/update-guidance.md`` is renamed or
    removed, this fails until the runbook reference is updated too.
    """
    assert _UPDATE_GUIDANCE_CMD.exists(), (
        "commands/update-guidance.md is missing — the runbook references a command "
        "that no longer exists (update the reference, or the command was moved)"
    )
    assert "/update-guidance" in _guidance_section(), (
        "AC-2: the section does not name the real /update-guidance command"
    )


def test_ac3_failure_policy_names_required_evidence() -> None:
    """AC-3 — the failure policy is explicit: ticket + the four evidence fields."""
    prose = _normalized_prose()
    assert re.search(r"ticket|escalat", prose), (
        "AC-3: the failure policy does not create/update a ticket"
    )
    # The four evidence fields a failing repo's ticket must carry.
    assert "repo" in prose, "AC-3: the failure ticket does not record the repo"
    assert re.search(r"guidance version|version", prose), (
        "AC-3: the failure ticket does not record the guidance version"
    )
    assert re.search(r"gate output|gate .*output|gate log", prose), (
        "AC-3: the failure ticket does not record the gate output"
    )
    assert re.search(r"next action|next step", prose), (
        "AC-3: the failure ticket does not record the next action"
    )
    # The chain continues/stops per policy rather than wedging silently.
    assert re.search(r"continue|stop|wedge", prose), (
        "AC-3: the section does not state the continue/stop failure policy"
    )


def test_ac4_no_monolithic_fleet_wide_harness_operation() -> None:
    """AC-4 — the doc frames a fleet-wide harness operation as the thing to avoid.

    The positive statement of AC-4: the sequencing lives in the outer
    scheduler/orchestrator and the harness supplies only per-repo mechanics; a
    single fleet-wide harness operation is explicitly *not* how this works.
    """
    prose = _normalized_prose()
    assert re.search(
        r"(not|never|rather than|instead of|avoids?)[^.]{0,60}"
        r"(fleet-wide|fleet|monolith|one-shot|single .*harness)",
        prose,
    ), (
        "AC-4: the section does not frame a monolithic/fleet-wide harness "
        "operation as the thing to avoid"
    )
    assert re.search(r"scheduler|orchestrator", prose), (
        "AC-4: the section does not place the sequencing in the outer "
        "scheduler/orchestrator (rather than the harness)"
    )
