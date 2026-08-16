"""#457 — the process doc's hook inventory covers every hook, and only refusers refuse.

``process/harness.md``'s *Enforcement hooks* section is the one consumer-facing
description of the hook bundle. Two things were wrong with it, and both were the
kind of wrong that a reader cannot detect from the document itself:

* It said two hooks could refuse and tabled two. Three can: ``push-target-guard``
  and ``git-push-guard`` emit a ``PreToolUse`` deny, and ``gate-evidence-guard``
  emits a ``Stop`` block. An operator deciding what to keep read a table that
  omitted the force-push guard entirely.
* The advisory hooks — the rest of the bundle — appeared in no prose anywhere.
  ``registry.yaml`` lists names and versions; ``BOOTSTRAP.md`` describes wiring.
  Neither says what a hook *does*, so "which of these do I want?" had no answer
  outside the source.

Both halves are guarded here as a **structural correspondence**, never as a
sentence pin (ADR 0016): the roster is derived from the tracked tree and the
refuser set from what the hook sources actually emit, so the guard fails on the
next hook added rather than on the two this change fixed. A hand-kept list would
have shipped a third stale table.

The correspondence runs in both directions on purpose. Omitting a tracked hook
from the inventory fails :func:`test_the_inventory_covers_exactly_the_tracked_hooks`;
so does inventing a row for a hook that does not exist. Listing a refuser as
advisory fails :func:`test_the_refusal_table_lists_exactly_the_hooks_that_refuse`;
so does claiming an advisory hook refuses. A one-directional check on either
axis is an opt-out from the other.

Acceptance criteria:

* **AC-1** — the refusal table covers the hooks that really refuse
  (:func:`test_the_refusal_table_lists_exactly_the_hooks_that_refuse`), and the
  fallback protected set is documented as the source declares it
  (:func:`test_the_documented_fallback_set_is_the_one_the_guard_falls_back_to`).
* **AC-2** — every installed hook has a line in the inventory, in exactly one of
  the two tables (:func:`test_the_inventory_covers_exactly_the_tracked_hooks`,
  :func:`test_the_two_tables_are_read_as_two_tables`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests._gitutil import tracked_files_under  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROCESS_DOC = _REPO_ROOT / "process" / "harness.md"
_HOOKS_DIR = _REPO_ROOT / "hooks"

#: The section that owns the inventory, and the sub-heading that splits it into
#: the hooks that refuse and the hooks that advise.
_SECTION_HEADING = "## Enforcement hooks"
_ADVISORY_HEADING = "### The advisory hooks"

#: A hook *refuses* when its source emits one of the two refusal payloads the
#: host understands: a ``PreToolUse`` deny decision, or a ``Stop`` block. Derived
#: from what the hooks emit rather than from a list here — a hand-kept denier
#: list is the same defect one level down from the table it would be guarding.
#: The colon-and-value form is what makes this an emission rather than a mention:
#: ``git-push-guard``'s docblock names ``permissionDecision`` in prose, and must
#: not be what puts it in this set.
_REFUSAL_EMISSION = re.compile(
    r"""permissionDecision:\s*["']deny["']|\bdecision:\s*["']block["']"""
)

#: The first column of a markdown table row: ``| `name.js` | … |``.
_ROW_SUBJECT = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)

#: ``push-target-guard.js``'s over-broad fallback set, read from the source that
#: applies it. Parsed rather than restated so that adding a branch name to the
#: guard is what makes the documentation red.
_FALLBACK_BLOCK = re.compile(
    r"const FALLBACK_PROTECTED = \[(.*?)\];", re.DOTALL
)
_QUOTED = re.compile(r'"([^"]+)"')


def _tracked_hooks() -> set[str]:
    """Every hook the installer ships, read from the git index.

    The index and not the directory: an untracked scratch copy of a hook, or a
    ``.js`` an editor left behind, is not part of the bundle and must not make
    the inventory red.
    """
    return {path.name for path in tracked_files_under("hooks") if path.suffix == ".js"}


def _hooks_that_refuse() -> set[str]:
    return {
        name
        for name in _tracked_hooks()
        if _REFUSAL_EMISSION.search((_HOOKS_DIR / name).read_text(encoding="utf-8"))
    }


def _section() -> str:
    text = _PROCESS_DOC.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(_SECTION_HEADING)}\b.*?(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, (
        f"process/harness.md has no '{_SECTION_HEADING}' section, so the hook "
        "inventory this guard reads does not exist. If the section was renamed, "
        "re-point this guard and every document that cites the old name."
    )
    return match.group(0)


def _tables() -> tuple[set[str], set[str]]:
    """``(refusal-table subjects, advisory-table subjects)``.

    Split at the advisory sub-heading rather than by counting tables: the
    position of a row in the section is the claim being made about it, so the
    split has to be the same one a reader performs.
    """
    section = _section()
    assert _ADVISORY_HEADING in section, (
        f"the '{_SECTION_HEADING}' section has no '{_ADVISORY_HEADING}' "
        "sub-heading, so there is no advisory inventory to read and every hook "
        "in the section reads as one that refuses"
    )
    head, _, tail = section.partition(_ADVISORY_HEADING)
    return set(_ROW_SUBJECT.findall(head)), set(_ROW_SUBJECT.findall(tail))


def _documented_fallback() -> set[str]:
    match = _FALLBACK_BLOCK.search(
        (_HOOKS_DIR / "push-target-guard.js").read_text(encoding="utf-8")
    )
    assert match, (
        "hooks/push-target-guard.js no longer declares FALLBACK_PROTECTED as a "
        "literal array, so this guard cannot read the set the documentation is "
        "measured against. Re-point it at wherever the fallback now lives — do "
        "not delete this assertion, which is what keeps the failure loud."
    )
    return set(_QUOTED.findall(match.group(1)))


# --- non-vacuity floors -------------------------------------------------------


def test_the_hook_roster_this_guard_reads_is_live() -> None:
    """Both derived sets are populated and anchored.

    Every correspondence below is a set comparison, and a set comparison over
    two empty sets holds forever. Membership is pinned, not cardinality — a
    count is the drift this guard exists to remove.
    """
    tracked = _tracked_hooks()
    refusers = _hooks_that_refuse()

    assert {"push-target-guard.js", "prompt-guard.js"} <= tracked, (
        f"the hook roster derived from the git index lost its anchors; got {sorted(tracked)}"
    )
    assert {
        "push-target-guard.js",
        "git-push-guard.js",
        "gate-evidence-guard.js",
    } <= refusers, (
        "the refusal-emission scanner no longer recognises the three hooks that "
        f"demonstrably refuse; got {sorted(refusers)}. A scanner that matches "
        "nothing makes every table assertion below constant-true."
    )
    assert refusers < tracked, (
        "every tracked hook now reads as a refuser, so the advisory half of the "
        f"inventory is unmeasured; got {sorted(refusers)}"
    )


def test_the_fallback_set_this_guard_reads_is_live() -> None:
    """The documented-fallback comparison consumes a non-empty set.

    Its own floor, separate from the roster's: a parse that derived to ``[]``
    would leave :func:`test_the_documented_fallback_set_is_the_one_the_guard_falls_back_to`
    passing over nothing at all (``craft.md`` → *The empty comparison set*).
    """
    fallback = _documented_fallback()

    assert {"main", "staging", "production"} <= fallback, (
        f"FALLBACK_PROTECTED parsed to {sorted(fallback)}, which has lost the "
        "names the parser was written against"
    )


# --- AC-1 ---------------------------------------------------------------------


def test_the_refusal_table_lists_exactly_the_hooks_that_refuse() -> None:
    """Both directions, because they are two different documentation defects.

    A hook that refuses and is missing from the table meets its operator as an
    unexplained refusal — the shape #457 was filed for, where ``git-push-guard``
    was the third denier and the doc claimed there were two. A hook listed as a
    refuser that cannot refuse is the opposite lie, and the one that makes an
    operator keep a hook for protection it does not provide.
    """
    tabled, _ = _tables()
    refusers = _hooks_that_refuse()

    assert refusers - tabled == set(), (
        f"hooks that emit a refusal but are absent from the refusal table: "
        f"{sorted(refusers - tabled)}. A deterministic refusal a reader has never "
        "been told about is indistinguishable from a broken tool."
    )
    assert tabled - refusers == set(), (
        f"hooks tabled as refusing that emit no refusal: {sorted(tabled - refusers)}. "
        "The table promises enforcement the source does not deliver."
    )


def test_the_documented_fallback_set_is_the_one_the_guard_falls_back_to() -> None:
    """The more security-relevant half, because it covers the unconfigured repo.

    ``push-target-guard`` protects a fixed set of branch names when
    ``CONTEXT.md`` declares none — which is exactly the state of every repo that
    skipped configuration. A name in that set the document does not print is a
    push an operator cannot predict will be refused.
    """
    section = _section()
    undocumented = sorted(name for name in _documented_fallback() if f"`{name}`" not in section)

    assert not undocumented, (
        f"branch names in FALLBACK_PROTECTED that the hooks section never prints: "
        f"{undocumented}. The fallback applies to every repo that declared no "
        "branches:, so its membership is the part an operator most needs stated."
    )
    assert "`origin/HEAD`" in section, (
        "the fallback also protects whatever origin/HEAD resolves to, which is "
        "not in FALLBACK_PROTECTED and so is invisible to the sweep above"
    )


# --- AC-2 ---------------------------------------------------------------------


def test_the_inventory_covers_exactly_the_tracked_hooks() -> None:
    """One line per installed hook, and no line for anything else."""
    refusal, advisory = _tables()
    tracked = _tracked_hooks()
    inventoried = refusal | advisory

    assert tracked - inventoried == set(), (
        f"installed hooks with no line in the process doc's inventory: "
        f"{sorted(tracked - inventoried)}. An operator deciding what to keep has "
        "no prose to decide from."
    )
    assert inventoried - tracked == set(), (
        f"the inventory names hooks the tree does not ship: "
        f"{sorted(inventoried - tracked)}. A row for a deleted hook is a promise "
        "of protection nothing provides."
    )


def test_the_two_tables_are_read_as_two_tables() -> None:
    """Placement is the claim, so the two halves must be disjoint.

    Without this, a hook listed in *both* tables would satisfy every membership
    assertion above — they only ever admit names — while the document said a
    hook both refuses and never refuses.
    """
    refusal, advisory = _tables()
    overlap = sorted(refusal & advisory)

    assert not overlap, (
        f"hooks listed as both refusing and advisory: {overlap}. The sub-heading "
        "split is the claim each row makes; a hook belongs to exactly one side."
    )
