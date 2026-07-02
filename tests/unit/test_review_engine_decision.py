"""CAL-925 — record the in-container review-engine decision: Claude, not Codex.

The `harness:dev` image runs Codex via its bundled `bwrap`, but the unprivileged
container blocks `CLONE_NEWUSER`, so a real `--engine codex` review fails
per-command and yields no usable verdict (CAL-866). The decision is **option (b)**:
formally accept Claude-only reviews in-container and document `--engine codex` as
a host-only / cross-model option — rather than loosening container privileges
(bubblewrap + a new user namespace / a looser seccomp profile) on a container
that reviews untrusted diffs.

This guards the recorded decision (ADR 0002) and the three docs the ticket names
(`commands/harness.md`, `agents/reviewer.md`, `specs/features/verb-model.md`),
plus the CONTEXT decisions index — the same shape as
`test_loop_substrate_decision.py` guards ADR 0001.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "specs" / "decisions" / "0002-in-container-review-engine.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
HARNESS_CMD = REPO_ROOT / "commands" / "harness.md"
REVIEWER = REPO_ROOT / "agents" / "reviewer.md"
VERB_MODEL = REPO_ROOT / "specs" / "features" / "verb-model.md"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _host_only(text: str) -> bool:
    low = text.lower()
    return "host-only" in low or "host only" in low


# --- The ADR records the decision -------------------------------------------


def test_adr_present() -> None:
    """The in-container review-engine decision is recorded as an ADR."""
    assert ADR.exists(), (
        "the in-container review-engine decision must be recorded in "
        "specs/decisions/0002-in-container-review-engine.md"
    )


def test_adr_chooses_claude_in_container_codex_host_only() -> None:
    """ADR records option (b): in-container engine is Claude; Codex is host-only."""
    text = _read(ADR)
    low = text.lower()
    assert "claude" in low, "ADR must name Claude as the in-container review engine"
    assert "in-container" in low or "in container" in low, (
        "ADR must frame the decision as the in-container engine"
    )
    assert "codex" in low, "ADR must name Codex (the rejected in-container engine)"
    assert _host_only(text), (
        "ADR must document --engine codex as a host-only / cross-model option"
    )


def test_adr_records_rejected_privilege_path_and_its_cost() -> None:
    """ADR records *why* (a) was rejected: privilege loosening on an untrusted-diff
    container is too costly."""
    low = _read(ADR).lower()
    assert "bubblewrap" in low or "bwrap" in low, (
        "ADR must name the bubblewrap/bwrap sandbox path it declines to enable"
    )
    assert "seccomp" in low or "cap_sys_admin" in low or "privilege" in low, (
        "ADR must name the privilege/seccomp loosening it rejects"
    )
    assert "untrusted" in low, (
        "ADR must record the security cost — the container reviews untrusted diffs"
    )


def test_adr_cites_the_ticket() -> None:
    """The ADR traces to the deciding ticket."""
    assert "CAL-925" in _read(ADR), "ADR must cite CAL-925"


# --- The three named docs state the contract --------------------------------


def test_harness_command_states_codex_host_only() -> None:
    """commands/harness.md states the in-container engine is Claude; codex host-only."""
    text = _read(HARNESS_CMD)
    assert _host_only(text) and "codex" in text.lower(), (
        "commands/harness.md must document --engine codex as host-only"
    )


def test_reviewer_agent_states_codex_host_only() -> None:
    """agents/reviewer.md states the in-container engine is Claude; codex host-only."""
    text = _read(REVIEWER)
    low = text.lower()
    assert _host_only(text) and "codex" in low and "claude" in low, (
        "agents/reviewer.md must state the in-container engine is Claude and "
        "--engine codex is host-only"
    )


def test_verb_model_states_codex_host_only() -> None:
    """specs/features/verb-model.md states the in-container engine is Claude."""
    text = _read(VERB_MODEL)
    low = text.lower()
    assert _host_only(text) and "codex" in low, (
        "verb-model.md must document the in-container engine as Claude and "
        "--engine codex as host-only"
    )


# --- CONTEXT decisions index names the ADR ----------------------------------


def test_context_index_names_adr_0002() -> None:
    """The CONTEXT.md decisions index lists ADR 0002 alongside 0001."""
    text = _read(CONTEXT)
    assert "0002" in text and "specs/decisions/" in text, (
        "CONTEXT.md decisions index must name ADR 0002"
    )
