"""#266 — `commands/harness.md` states that base movement needs no rebase.

*Source:* ADR 0010's cheapest slice. `close` fetches `origin/<base>` and merges
the run branch into a **detached throwaway worktree** based on that tip, never
touching the run worktree's HEAD — so a base that advances during a run needs no
rebase at all. Nothing in the command doc said so, and its gate-refusal paragraph
actively prescribed *"for a conflict, rebase the run branch on the updated base,
re-review, and close again"*. Sessions followed it, and a rebase rewrites every
SHA on the run branch, invalidating the HEAD-bound passing review for hunks the
rebase never touched — a whole class of self-inflicted re-review.

These guards pin that the command doc — which the orchestrating session reads as
its operating instruction — carries the rule, that the retired prescription is
gone from the file entirely, and that the version stamp moved with the content
(the standing trap: a header bumped without its `registry.yaml` entry).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
COMMAND_DOC = REPO_ROOT / "commands" / "harness" / "run.md"
REGISTRY = REPO_ROOT / "registry.yaml"

_HEADING = "#### Base movement needs no rebase"


def _rule_block() -> str:
    """The `Base movement needs no rebase` block, sliced by its stable heading."""
    text = COMMAND_DOC.read_text()
    assert _HEADING in text, (
        f"commands/harness.md must carry a `{_HEADING}` block stating that "
        "`close` integrates `origin/<base>` itself (#266 AC-3)."
    )
    start = text.index(_HEADING)
    rest = text[start + len(_HEADING) :]
    # The block runs to the next heading of any level, or to end of file.
    nxt = re.search(r"^#{1,6} ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def test_rule_block_states_close_integrates_the_base_itself() -> None:
    block = _rule_block()
    assert "throwaway worktree" in block, (
        "The rule must name the detached throwaway worktree — the mechanism that "
        "makes a rebase unnecessary (#266 AC-3)."
    )
    assert re.search(r"origin/`?<base>`?", block), (
        "The rule must state that `close` integrates `origin/<base>` itself "
        "(#266 AC-3)."
    )


def test_rule_block_forbids_rebasing_for_base_movement() -> None:
    """The block must carry the rule in its **imperative** form.

    Pinned as `must not … rebase` specifically, not a looser "not … rebase"
    proximity match: the block necessarily discusses rebasing in several
    sentences, so a loose match is satisfied by any of them and would survive
    deleting the normative statement itself (caught by mutation).
    """
    block = _rule_block()
    assert re.search(r"must\s+\*{0,2}not\*{0,2}\s+rebase", block, re.S | re.I), (
        "The rule must state that a run **must not** rebase for base movement "
        "(#266 AC-3)."
    )
    assert re.search(r"rewrit", block, re.I), (
        "The rule must say why: a rebase rewrites every SHA on the run branch "
        "and invalidates the HEAD-bound passing review (#266 AC-3)."
    )


def test_rule_block_names_push_rejected_as_a_plain_retry() -> None:
    block = _rule_block()
    assert "push_rejected" in block, (
        "The rule must name `push_rejected` (#266 AC-3)."
    )
    assert re.search(r"retry|close again", block, re.I), (
        "The rule must state that a `push_rejected` failure is a plain retry — "
        "no rebase, no re-review (#266 AC-3)."
    )


def test_the_retired_prescription_is_gone_from_the_whole_file() -> None:
    """Not just the new block — the old instruction must not survive anywhere.

    The defect was one sentence in the gate-refusal paragraph. Adding a correct
    rule elsewhere while leaving that sentence in place would leave the file
    contradicting itself, and a session reading top-to-bottom would hit the
    wrong instruction first.
    """
    text = COMMAND_DOC.read_text()
    assert "rebase the run branch on the updated" not in text, (
        "commands/harness.md still carries the retired prescription 'rebase the "
        "run branch on the updated <base>, re-review, and close again' (#266)."
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
        "entry disagrees — bump both (#266)."
    )
