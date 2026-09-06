"""#568 — the marked cut, on the arm the `uncovered` caller makes reachable.

`reportable()` bounds a path a refusal hands the operator. Cycle 1 excused the
over-cap arm as unreachable: every argument was `markerPath()`, built on
`realpathSync`, which throws `ENAMETOOLONG` past PATH_MAX. Cycle 2's own fix
added the caller that falsified it — `uncovered`, a repo-relative path out of
`git diff-tree`, which compares two tree oids, is never checked out, and passes
no syscall that would cap it. Git accepts and prints back a 5000-character path.

So the arm is reachable, which means AC-1's second disjunct — *or makes the
truncation visible* — is owed evidence rather than a comment. This is that
evidence, and it is deliberately a direct exercise of the production function
rather than a refusal fixture: the property is the helper's, both hooks share
it, and driving it through a 5000-character merge tree twice would measure the
same three lines at a great deal more cost.

Both hooks are covered because both carry the helper. `push-target-guard.js`
has the reachable caller; `gate-evidence-guard.js` fires on every completion
claim, and a body that silently diverged from its twin is exactly what #568's
review found the first time.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.unit._prose import REPO_ROOT


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


_HOOKS = ("push-target-guard.js", "gate-evidence-guard.js")
_CAP = 4096


def _reportable(hook: str, value: str) -> str:
    """Run the **production** helper, imported from the shipped hook."""
    script = (
        "const {reportable} = require(process.argv[1]);"
        "const v = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(reportable(v)));"
    )
    proc = subprocess.run(
        [_node(), "-e", script, str(REPO_ROOT / "hooks" / hook)],
        input=json.dumps(value),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"could not drive the production helper: {proc.stderr}"
    return json.loads(proc.stdout)


@pytest.mark.parametrize("hook", _HOOKS)
def test_a_path_at_the_cap_is_returned_whole(hook: str) -> None:
    """The control. Without it, a helper that truncated everything would pass."""
    value = "/" + "d" * (_CAP - 1)
    assert len(value) == _CAP
    assert _reportable(hook, value) == value


@pytest.mark.parametrize("hook", _HOOKS)
def test_a_path_past_the_cap_is_cut_visibly(hook: str) -> None:
    """AC-1's second arm: past the cap the reader is told, never handed a stump.

    The whole defect was a cut nobody could see, so the assertion is that the
    result cannot be mistaken for a path: it is longer than the cap, it says so
    in words, and it still opens with the bytes the caller passed.
    """
    value = "/" + "d" * 5000
    answer = _reportable(hook, value)

    assert answer != value[:_CAP], "the cut is the silent one #568 exists to remove"
    assert str(_CAP) in answer, f"the cut does not say where it happened: {answer[-80:]}"
    assert "truncated" in answer, f"the cut is not named as one: {answer[-80:]}"
    assert answer.startswith(value[:_CAP]), "the retained prefix is not the caller's"
