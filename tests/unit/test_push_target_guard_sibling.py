"""#457 AC-4 — the push-target guard depends on a sibling, and says so.

``hooks/push-target-guard.js`` imports ``git-push-guard.js``'s lexer rather than
growing a weaker twin of it (#436). Its header nevertheless claimed the opposite
— that ``node <path>`` resolves this hook "with no module beside it" — which is
the shape ``craft.md`` calls *a comment asserting an unmeasured precondition*.
The consequence is not cosmetic: delete or rename the sibling and the ``require``
throws, the top-level catch falls open, and the target guard stops refusing
anything at all. Removing the *force*-push guard therefore silently disarms both.

Two halves, and #457 took both rather than either:

* The claim is corrected, and a structural correspondence keeps it corrected —
  a hook that requires a sibling may not carry the no-sibling claim
  (:func:`test_no_hook_claims_to_stand_alone_while_requiring_a_sibling`).
* The disarm is named when it happens. The hook checks for the sibling before
  requiring it and falls open with a message naming the missing file, so the one
  stderr line distinguishes "this guard is gone" from any other fail-open
  (:func:`test_a_missing_sibling_falls_open_naming_the_file_it_needs`).

The fail-open **posture** is unchanged and deliberately so: a hook that crashed
here would wedge every ``Bash`` call in the session. What changes is that the
disarm is legible. :func:`test_the_same_push_is_refused_when_the_sibling_is_there`
is the control that makes the observation mean something — without it, a hook
that fell open for any other reason would satisfy the assertion above.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests._gitutil import tracked_files_under  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "hooks"
_SIBLING = "git-push-guard.js"

#: The claim the header used to make. Read as *negative space* (ADR 0016): the
#: guard asserts this wording is absent from a hook that requires a sibling, and
#: says nothing about what the corrected header affirmatively says — which is the
#: reviewer's to judge.
_STANDALONE_CLAIM = "no module beside it"

#: A relative require is the only way one hook reaches another; the installer
#: copies hooks as flat files, so ``./`` names a sibling by construction.
_SIBLING_REQUIRE = 'require("./'

#: The wording that separates the two fail-open arms. ``_DISARM_NOTICE`` belongs
#: to the explicit sibling check; ``_CRASH_NOTICE`` is the top-level wrapper's,
#: shared by every hook. Asserting one present and the other absent is what makes
#: the observation about *this hook's check* rather than about node's module
#: loader, which names the missing file on its own.
_DISARM_NOTICE = "disarmed"
_CRASH_NOTICE = "crashed before it could decide"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on ``main`` with one commit, no ``CONTEXT.md``, no marker.

    The fallback protected set therefore applies and a push to ``main`` is a
    push the guard refuses — the shape that makes a fail-open visible.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "first")
    return root


@pytest.fixture
def hooks_copy(tmp_path: Path) -> Path:
    """A copy of the shipped hooks directory, safe to delete files from."""
    target = tmp_path / "hooks"
    shutil.copytree(_HOOKS_DIR, target)
    return target


def _run(hooks_dir: Path, repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the copied guard against a push to ``main`` in ``repo``."""
    payload = {
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git push origin HEAD:main"},
    }
    proc = subprocess.run(
        [_node(), str(hooks_dir / "push-target-guard.js")],
        input=json.dumps(payload),
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )
    assert proc.returncode == 0, f"the hook must never exit non-zero: {proc.stderr}"
    assert proc.stdout.strip(), f"the hook wrote no decision at all: {proc.stderr}"
    return proc


def _decision(proc: subprocess.CompletedProcess[str]) -> str | None:
    output: dict[str, str] = json.loads(proc.stdout).get("hookSpecificOutput", {})
    return output.get("permissionDecision")


# --- the disarm is named ------------------------------------------------------


def test_the_same_push_is_refused_when_the_sibling_is_there(
    hooks_copy: Path, repo: Path
) -> None:
    """The control: the copied guard, intact, still refuses this push.

    Without it, the assertion below would be satisfied by a guard that fell open
    for any reason at all — a broken copy, a missing node, an unrelated crash —
    and the missing sibling would be proven to cause nothing.
    """
    assert _decision(_run(hooks_copy, repo)) == "deny"


def test_a_missing_sibling_falls_open_naming_the_file_it_needs(
    hooks_copy: Path, repo: Path
) -> None:
    """Deleting the sibling disarms this guard entirely; the message says which.

    Fail-open is the right posture and is not what changes here. What changes is
    which arm reports it. **This assertion was written against the generic crash
    arm first and passed** — node's own ``Cannot find module './git-push-guard.js'``
    already carries the filename, so a bare "names the sibling" check is born
    green and measures node's error text rather than this hook's check. So the
    assertion is on the *distinct* wording the explicit check emits, plus the
    absence of the crash arm's wording: together those can only both hold if the
    hook looked for the sibling before requiring it.

    The distinction is worth the check because the two arms mean different
    things. A crash is *this hook broke*; a missing sibling is *this guard is
    disarmed and one named file restores it*, which is the only one an operator
    can act on.
    """
    (hooks_copy / _SIBLING).unlink()

    proc = _run(hooks_copy, repo)

    assert _decision(proc) is None, (
        "with the sibling gone the guard cannot parse a command and must fall "
        f"open, not decide; got {proc.stdout!r}"
    )
    assert "fail-open" in proc.stderr and _SIBLING in proc.stderr, (
        "the disarm must be announced in the hooks' fail-open form and name the "
        f"missing sibling; got {proc.stderr!r}"
    )
    assert _DISARM_NOTICE in proc.stderr, (
        f"the fail-open must come from the explicit sibling check, whose message "
        f"says {_DISARM_NOTICE!r}; got {proc.stderr!r}"
    )
    assert _CRASH_NOTICE not in proc.stderr, (
        "the hook reached the generic crash arm, so it required the sibling "
        "before checking for it — the check either is not there or runs too "
        f"late; got {proc.stderr!r}"
    )


def test_the_crash_arm_still_reports_when_something_else_breaks(
    hooks_copy: Path, repo: Path
) -> None:
    """The negative control for the assertion above.

    It pins that :data:`_CRASH_NOTICE` is live wording the hook really emits, so
    ``_CRASH_NOTICE not in stderr`` above is a discriminating observation rather
    than a check against a string this tree never produces. Breaking the sibling
    *module* — present, but unloadable — reaches the crash arm precisely because
    the existence check is satisfied.
    """
    (hooks_copy / _SIBLING).write_text("throw new Error('sibling is broken');\n")

    proc = _run(hooks_copy, repo)

    assert _decision(proc) is None, f"a broken sibling must fall open; got {proc.stdout!r}"
    assert _CRASH_NOTICE in proc.stderr, (
        f"the generic crash arm no longer reports, so the assertion that the "
        f"sibling check avoids it measures nothing; got {proc.stderr!r}"
    )


# --- the header no longer claims otherwise ------------------------------------


def _hook_sources() -> dict[str, str]:
    """Every tracked hook's source, keyed by filename.

    The git index rather than the directory: an untracked scratch copy is not
    part of the bundle (``craft.md`` → *Assert absence from the git index*).
    """
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in tracked_files_under("hooks")
        if path.suffix == ".js"
    }


def _standalone_claims_that_are_false(sources: dict[str, str]) -> list[str]:
    """Hooks asserting they resolve alone while requiring a sibling."""
    return sorted(
        name
        for name, text in sources.items()
        if _SIBLING_REQUIRE in text and _STANDALONE_CLAIM in text
    )


def test_the_predicate_flags_a_hook_that_makes_the_false_claim() -> None:
    """Positive control, fed the pre-fix shape rather than a restatement of it.

    It exercises :func:`_standalone_claims_that_are_false` itself, so a predicate
    degraded to "flag nothing" fails here rather than reading as a clean sweep
    over the real tree.
    """
    synthetic = {
        "fake-guard.js": (
            f"// node <path> must resolve this hook with {_STANDALONE_CLAIM}.\n"
            f'const parser = {_SIBLING_REQUIRE}{_SIBLING}");\n'
        ),
        "innocent-guard.js": f"// resolves with {_STANDALONE_CLAIM}, and requires nothing.\n",
    }

    assert _standalone_claims_that_are_false(synthetic) == ["fake-guard.js"], (
        "the predicate must flag exactly the hook that both requires a sibling "
        "and claims it needs none — an innocent hook making the claim truthfully "
        "is not a defect"
    )


def test_the_hook_corpus_this_guard_reads_is_live() -> None:
    """Floor: the sweep below runs over a populated corpus that really requires.

    A corpus deriving to ``{}``, or one in which no hook requires a sibling at
    all, would make the sweep constant-true — and "no hook requires a sibling"
    is exactly the false belief this module exists to correct.
    """
    sources = _hook_sources()
    requirers = sorted(name for name, text in sources.items() if _SIBLING_REQUIRE in text)

    assert "push-target-guard.js" in sources, (
        f"the tracked hook corpus lost its anchor; got {sorted(sources)}"
    )
    assert requirers == ["push-target-guard.js"], (
        "the set of hooks depending on a sibling has changed. That is a real "
        "architectural change — it multiplies the disarm this module guards — so "
        f"give the new one the same existence check and update this floor; got {requirers}"
    )


def test_no_hook_claims_to_stand_alone_while_requiring_a_sibling() -> None:
    """The correspondence, in the direction that matters.

    A hook that genuinely resolves alone may say so; ``gate-evidence-guard.js``
    does, truthfully. The defect is the conjunction, and it is invisible to a
    reader of either half on its own.
    """
    false_claims = _standalone_claims_that_are_false(_hook_sources())

    assert not false_claims, (
        f"hooks claiming to resolve with no module beside them while requiring a "
        f"sibling: {false_claims}. The claim is false, and a reader who trusts it "
        "will delete the sibling and silently disarm the guard."
    )
