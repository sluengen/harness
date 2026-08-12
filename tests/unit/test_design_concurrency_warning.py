"""#236 — warn against a nested-background `harness design` invocation.

*Source:* incident observed running `/harness run 233` — a bare `&` chained
inside a command that was also launched via the runtime's own background flag
detached a process the orchestrating session no longer tracked. The command
looked dead (its redirected output read empty), so a clean second invocation
ran too; both completed, and the stray first invocation's later-finishing
write silently became the run's bound design (idempotent-by-append
semantics), diverging from what had already been implemented against.

These guards pin that `commands/harness.md` Step 1.5 documents the trap and
its recovery, and that the version stamp moved with the content (the standing
trap: a header bumped without its `registry.yaml` entry).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
COMMAND_DOC = REPO_ROOT / "commands" / "harness" / "run.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def _step_1_5_block() -> str:
    text = COMMAND_DOC.read_text()
    start = text.index("Step 1.5")
    end = text.index("Step 2 — implement")
    return text[start:end]


def test_step_1_5_warns_against_nested_backgrounding() -> None:
    block = _step_1_5_block()
    assert "&" in block and re.search(r"nested", block, re.I), (
        "commands/harness.md Step 1.5 must warn against chaining a bare `&` "
        "inside a command that is also launched via the runtime's own "
        "background flag (#236)."
    )


def test_step_1_5_states_the_empty_output_trap() -> None:
    block = _step_1_5_block()
    assert re.search(r"empty.{0,80}not finished|not finished.{0,80}empty", block, re.S), (
        "commands/harness.md Step 1.5 must state that an empty redirected "
        "output file means 'not finished yet', never 'dead' — the wrong "
        "reading that caused the incident (#236)."
    )


def test_step_1_5_states_last_completing_wins() -> None:
    block = _step_1_5_block()
    assert "concurrent_prior_at" in block, (
        "commands/harness.md Step 1.5 must name `concurrent_prior_at` — the "
        "machine-readable form of the last-completing-invocation warning "
        "(#236)."
    )
    assert re.search(r"last (?:one|invocation) to finish", block), (
        "commands/harness.md Step 1.5 must state that the last invocation to "
        "finish silently becomes the run's bound design (#236)."
    )


def test_step_1_5_does_not_change_the_rerun_contract() -> None:
    """Out of scope: making `design` reject a legitimate re-run. The doc must
    still say the idempotent re-run contract is unchanged."""
    block = _step_1_5_block()
    assert "re-run contract is unchanged" in block or "idempotent re-run contract" in block, (
        "commands/harness.md Step 1.5 must state the recovery is not a "
        "bypass of the legitimate re-run contract (#236, out of scope)."
    )


def test_guidance_stamp_bumped_with_its_registry_entry() -> None:
    """The standing trap: a header bumped without its `registry.yaml` entry."""
    m = re.search(r"guidance:harness-run@(\d+\.\d+\.\d+)", COMMAND_DOC.read_text())
    assert m, "commands/harness.md must carry a guidance version header"
    version = m.group(1)
    pattern = re.escape("commands/harness/run.md") + r":\s*\{[^}]*\}"
    entry = re.search(pattern, REGISTRY.read_text())
    assert entry, "registry.yaml must have an entry for commands/harness.md"
    assert f"version: {version}" in entry.group(0), (
        f"commands/harness.md header is @{version} but its registry.yaml "
        "entry disagrees — bump both (#236)."
    )
