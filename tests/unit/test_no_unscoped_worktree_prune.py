"""No module under ``harness/`` may issue a repo-wide ``git worktree prune`` (#371).

``git worktree prune`` takes no path. There is no scoped form of the command —
it sweeps the *whole* registry, deregistering every worktree whose directory it
cannot see. So the token pair is not an argument to check, it **is** the defect,
and this guard is a flat ban rather than a call-shape check.

What that cost. Every verb runs inside the container, where the repo is mounted
at ``/workspace`` and nothing else on the host filesystem exists. A prune issued
there classifies every worktree registered outside the mount as missing, and
deletes its admin entry under ``.git/worktrees/<name>/``. The directory survives
on the host, so nothing looks wrong until something reads the tree and git
answers ``fatal: not a git repository: <repo>/.git/worktrees/<name>`` with exit
128 — which arrives as a wall of red in tracked-tree guards the change never
touched. A **host-side** prune does not do this (the path exists there), which is
why the failure was twice recorded as a race between concurrent sessions before
the mechanism was found.

Three sites carried it when this guard was written: the shared teardown
primitive (``harness/_git.py``) and the two ``worktree add`` rollback paths
(``harness/worktree.py``, ``harness/promotion.py``). Each is now scoped to the
one path it was asked to touch — ``git worktree remove --force <path>``, which
clears that path's admin entry and provably touches no other.

**Predicate choice.** The detector reads the AST, not the text. A ban on the
*words* would fire on this module's own prose and on the teardown docstrings
that must explain the retired step — so the cheaper predicate cannot be used
here, and :func:`test_prose_naming_the_retired_prune_is_not_a_call` pins that by
feeding the detector a docstring a regex would flag.

**Residual, stated rather than left implicit.** A caller that assembled the argv
out of a shell string (``run_git(root, *shlex.split("worktree prune"))``) or
concatenated the tokens at runtime would not be seen. No git site in this repo
builds argv that way — every one is list-form literals, which is also what
``S603``/``S607`` keep it to — so widening the detector would be guarding a
shape the codebase does not have.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._gitutil import tracked_py_sources

#: The scanned package. ``harness/`` is where every git invocation lives; the
#: ban is about what a *verb* may do to a registry it shares with the operator.
_SCANNED_BASE = "harness"

#: An anchor the derivation must still reach. Non-empty alone would go green on
#: a scan narrowed to nothing; a named member fails loudly on a rename instead
#: of quietly shrinking the subject set.
_ANCHOR = "harness/_git.py"

#: The banned argv, in order. Adjacent string constants in a single call.
_BANNED_TOKENS = ("worktree", "prune")


def unscoped_prune_calls(source: str, relpath: str) -> list[str]:
    """``<relpath>:<lineno>`` for every call issuing ``git worktree prune``.

    Named once so the real assertion and every control below route through the
    same predicate: a control carrying its own inline copy of the detector would
    keep passing while the detector it is supposed to protect became a no-op.

    The string constants a call passes positionally are read *in order* and the
    non-literal ones (``repo_root``, ``str(path)``) dropped, so the ban matches
    however the surrounding argv is spelled — ``run_git(root, "worktree",
    "prune")`` and ``await _git(root, "worktree", "prune")`` alike — while
    ``"worktree", "remove", "--force"`` is untouched.
    """
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        literals = [
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        ]
        window = len(_BANNED_TOKENS)
        for start in range(len(literals) - window + 1):
            if tuple(literals[start : start + window]) == _BANNED_TOKENS:
                hits.append(f"{relpath}:{node.lineno}")
                break
    return hits


def _scanned_sources() -> list[Path]:
    return tracked_py_sources(_SCANNED_BASE)


def test_no_harness_module_issues_an_unscoped_worktree_prune() -> None:
    """The ban itself. A verb must not be able to deregister a worktree it was
    not asked to touch — least of all one it cannot even see."""
    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in _scanned_sources():
        relpath = str(path.relative_to(repo_root))
        offenders += unscoped_prune_calls(path.read_text(encoding="utf-8"), relpath)

    assert offenders == [], (
        "`git worktree prune` takes no path — it sweeps the whole registry, and "
        "in the container every worktree outside the /workspace mount reads as "
        "missing and is deregistered (#371). Scope the call to the one path it "
        "was asked to touch: `git worktree remove --force <path>` clears that "
        f"path's admin entry and no other. Offending sites: {offenders}"
    )


def test_the_scan_reaches_the_sources_it_claims_to() -> None:
    """Non-vacuity floor. A ban is free against an empty subject set: if
    ``tracked_py_sources`` derived to ``[]`` the assertion above would pass
    having read nothing, with no skip and no warning."""
    repo_root = Path(__file__).resolve().parents[2]
    scanned = {str(p.relative_to(repo_root)) for p in _scanned_sources()}

    assert len(scanned) > 1, f"the {_SCANNED_BASE}/ scan derived to {scanned}"
    assert _ANCHOR in scanned, (
        f"the scan no longer reaches {_ANCHOR}, the module that owns the shared "
        f"teardown primitive; it found {len(scanned)} sources"
    )


def test_the_detector_flags_a_synchronous_prune_call() -> None:
    """Positive control: the exact shape ``harness/_git.py`` carried."""
    sample = 'run_git(repo_root, "worktree", "prune")\n'

    assert unscoped_prune_calls(sample, "sample.py") == ["sample.py:1"]


def test_the_detector_flags_an_awaited_prune_call() -> None:
    """Positive control for the async rollback shape (``harness/worktree.py``).
    The call sits inside an ``Await``, so a detector inspecting only top-level
    statements would miss it while the synchronous control still passed."""
    sample = 'async def roll():\n    await _git(repo_root, "worktree", "prune")\n'

    assert unscoped_prune_calls(sample, "sample.py") == ["sample.py:2"]


def test_the_detector_leaves_the_scoped_removal_alone() -> None:
    """Negative control. The replacement must stay legal, or the ban would be
    banning the fix: ``remove`` names the one path it is entitled to act on."""
    sample = 'run_git(repo_root, "worktree", "remove", "--force", str(path))\n'

    assert unscoped_prune_calls(sample, "sample.py") == []


def test_prose_naming_the_retired_prune_is_not_a_call() -> None:
    """The control written out of the rejected predicate's blind spot.

    A text or regex ban — the cheaper detector — would flag this sample, because
    it spells the banned tokens adjacently in a docstring and a comment. That is
    not hypothetical prose: the teardown primitive has to explain what it stopped
    doing, and this module has to name the ban in order to state it. The sample
    therefore asserts *both* directions, so the blind spot is explicit rather
    than implied by a bare non-match.
    """
    sample = (
        '"""Step 2 used to be ``git worktree prune`` — see #371."""\n'
        "# The repo-wide `git worktree prune` is banned.\n"
        'BANNED = ("worktree", "prune")\n'
    )

    assert "worktree prune" in sample, (
        "the sample must contain the banned words, which is exactly why a text "
        "ban would certify this file as an offender"
    )
    assert unscoped_prune_calls(sample, "sample.py") == []
