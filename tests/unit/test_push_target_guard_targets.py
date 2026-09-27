"""``push-target-guard.js`` reads push operands only up to the end of the git command.

**The occurrence.** ``targets()`` treated every token after ``git ... push`` as a
candidate branch, to the end of the whole shell line. So ``git push origin
feature && echo dev`` warned about a push to ``dev``, which the command never
makes (improvement ledger ``5796689145``). The advisory is non-blocking, so the
cost was noise, but noise is how a warning stops being read.

**Admitted under ADR 0017 D5 class (a), behaviour of executable code.** Each case
calls the exported ``targets`` through node; nothing here reads the hook's source.

**The controls matter as much as the kills.** A fix that stopped scanning at the
first token after the remote would pass the operator cases and lose a real push
target, so the multi-refspec and the push after a ``cd ... &&`` prefix must still
be found.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.unit._prose import REPO_ROOT

HOOK = REPO_ROOT / "hooks" / "push-target-guard.js"


def _targets(command: str) -> list[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    script = (
        f"const {{ targets }} = require({json.dumps(str(HOOK))});"
        "process.stdout.write(JSON.stringify(targets(process.argv[1])));"
    )
    proc = subprocess.run(
        [node, "-e", script, command], capture_output=True, text=True, check=True, timeout=30
    )
    return list(json.loads(proc.stdout))


@pytest.mark.parametrize(
    "command",
    [
        "git push origin feature && echo dev",
        "git push origin feature || git checkout dev",
        "git push origin feature ; git log dev",
        "git push origin feature; git log dev",
        "git push origin feature | tee dev",
    ],
)
def test_a_word_after_a_shell_operator_is_not_a_push_target(command: str) -> None:
    assert "dev" not in _targets(command), (
        f"{command!r} pushes only 'feature'; a token after the shell operator "
        "is another command's argument, not a refspec"
    )


def test_the_real_target_before_the_operator_is_still_found() -> None:
    assert "feature" in _targets("git push origin feature && echo dev")
    assert "feature" in _targets("git push origin feature; git log dev")


def test_a_push_after_a_cd_prefix_is_still_found() -> None:
    assert "dev" in _targets("cd /repo && git push origin dev")


def test_every_refspec_of_one_push_is_found() -> None:
    found = _targets("git push origin +feature:refs/heads/dev main")
    assert "dev" in found and "main" in found
