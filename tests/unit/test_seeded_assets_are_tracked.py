"""#537 — a deliverable that never entered the index ships as nothing.

Every guard in this repo reads the git index, deliberately: a guard over the
working tree passes on bytes that are not the bytes that ship. The blind spot in
that posture is a file that is *only* in the working tree. It is present for the
session that wrote it, absent from every clone, and invisible to the whole suite
— so the gate certifies a tree the author believes contains it.

**Twice in one branch, which is why this exists rather than being a hypothetical.**
`.gitignore` carried an unanchored `build/`, so giving the `/build` workflow a
skill of its own put `skills/build/SKILL.md` behind a Python build-artifact
pattern; the plugin would have shipped without its main lifecycle workflow. And a
bare `design.md` in a machine-local `.git/info/exclude` swallowed
`.claude/rules/design.md` while `AGENTS.md` named it — caught at review, not by
the gate. Both are the same shape: a broad ignore pattern meeting a new file
whose name happens to match, with `git add -A` reporting success either way.

**Admitted under ADR 0017 D5 class (c), asset integrity.** The subject is which
files the tree carries, not what any of them says.

**Why these directories.** They are the ones whose contents are *named elsewhere*
— by the spine, by `hooks.json`, by `/harness:init` — so an absent file is a
document describing behaviour the tree does not have. A general "nothing is
untracked" sweep would fail on every scratch file and would be deleted within a
week; this one is scoped to the sets where absence is a defect.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directories whose every shipped file is referenced from somewhere else in the
#: tree, so a missing one is a broken reference rather than a missing convenience.
SHIPPED = (".claude/rules", "hooks", "skills", "agents", "templates", ".codex/agents")


def _tracked() -> set[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", *SHIPPED],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {REPO_ROOT / name for name in out.split("\0") if name}


def _on_disk() -> set[Path]:
    found: set[Path] = set()
    for relative in SHIPPED:
        root = REPO_ROOT / relative
        found |= {p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}
    return found


def test_there_is_something_to_compare() -> None:
    """The floor. Two empty sets compare equal, and a `git ls-files` that silently
    returned nothing would otherwise turn the sweep below green over nothing
    (`craft.md` → the identically-failed-renders class)."""
    tracked = _tracked()
    assert len(tracked) > 50, f"the tracked sweep found only {len(tracked)} files"
    assert _on_disk(), "the on-disk sweep found nothing"


@pytest.mark.parametrize("directory", SHIPPED)
def test_every_shipped_file_is_in_the_index(directory: str) -> None:
    """The failing direction: a file the author wrote, the gate certified, and no
    clone receives."""
    root = REPO_ROOT / directory
    # Not a skip. `test_the_suite_reaches_the_host_only_where_it_declares_the
    # _dependency` is right that a skip is how a suite silently runs less than it
    # claims — and here there is nothing to be conditional *on*: every directory
    # in SHIPPED is named by the spine, `hooks.json`, or `/harness:init`, so one
    # that is missing is the defect this module exists to find.
    assert root.is_dir(), (
        f"{directory}/ is named elsewhere in the tree but does not exist here"
    )
    tracked = _tracked()
    untracked = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in _on_disk()
        if p not in tracked and p.is_relative_to(root)
    )
    assert not untracked, (
        f"{untracked} exist under {directory}/ but are not in the index — a broad "
        "ignore pattern can swallow a new file while `git add -A` reports success. "
        "`git add -f <path>`, and narrow the pattern that caught it."
    )
