"""#494 / ERP-349 — hydration preserves the gate's untracked-path boundary.

Repointed at #624, which replaced ``skills/init/`` with ``skills/hydrate/``. The
guard is unchanged in substance and only its second operand's path moved.

**Kept on mutation evidence, against the ticket's own retirement list.** #624
proposed deleting this module as a wording guard, on the 2026-09-08 process
assessment's reading. Three staged probes at that ticket say otherwise, and each
killed this row and only this row: dropping ``.harness/`` from ``.gitignore``
(the hardcoded-set half), dropping it from the hydration block, and adding
``.cache/`` to the hydration block alone (the cross-file half, both directions).
The rename moves the operand; it does not empty the subject.
"""

from __future__ import annotations

from tests._gitutil import indexed_text

_EXPECTED = {".evidence/", ".worktrees/", ".claude/worktrees/", ".harness/"}


def _block(path: str, prefix: str) -> set[str]:
    """Return normalized patterns from one machine-identifiable ignore block."""
    text = indexed_text(path)
    suffix = " -->" if prefix == "<!--" else ""
    begin = f"{prefix} harness:gate-ignore:begin{suffix}"
    end = f"{prefix} harness:gate-ignore:end{suffix}"
    assert text.count(begin) == 1 and text.count(end) == 1, (
        f"{path} must carry exactly one gate-ignore block"
    )
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return {
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "```"))
    }


def test_hydration_and_source_gitignore_carry_the_same_complete_gate_ignore_set() -> None:
    """A consuming repo gets every rule that protects temp-index tree identity.

    The incident behind ERP-349 was a registered nested worktree swept into
    ``git add -A``. Comparing the two enumerated blocks prevents the installer
    and this source checkout from drifting, while the explicit set prevents a
    shared omission from making that comparison vacuous.
    """
    source = _block(".gitignore", "#")
    hydration = _block("skills/hydrate/SKILL.md", "<!--")

    assert source == _EXPECTED
    assert hydration == source
