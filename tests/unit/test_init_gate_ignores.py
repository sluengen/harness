"""#494 / ERP-349 — hydration preserves the gate's untracked-path boundary."""

from __future__ import annotations

from tests._gitutil import indexed_text

_EXPECTED = {".evidence/", ".worktrees/", ".claude/worktrees/"}


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
    hydration = _block("commands/init.md", "<!--")

    assert source == _EXPECTED
    assert hydration == source
