"""#562 — the two Bash guards compose, and one test says so.

``hooks/push-target-guard.js`` does not refuse a **bare shell fed a script it
cannot read** — a pipe into ``sh``, a here-string, a process substitution.
:func:`pushesIn` destructures only ``{ tokens }`` from the lexer, never reads
``pipedInto``, and never calls ``isBareShellFedExternally``. Read alone, that is
a hole in the control that stops unverified work reaching a protected branch.

**It is not a hole in the control of record, and #562 was reclassified for that
reason.** ``hooks/hooks.json`` registers *both* guards on every ``Bash`` call,
and a deny from either blocks it. ``git-push-guard.js`` already refuses this
shape unconditionally — in a repo, outside a repo, push or no push — so the
composed refusal is total and adding a second copy of the check to
``pushesIn`` would be an enforcement branch that can never fire (P2).

What was missing was not the refusal but any record that the target guard
*depends* on its sibling for this class. Narrow ``isBareShellFedExternally``, or
drop the force guard from the ``Bash`` matcher, and the hole opens with nothing
going red. This module is that record.

**The pair is derived from ``hooks.json``, never named here.** That is the whole
mechanism: the claim under test is "the shipped registration refuses these
shapes", so the registration is the input. Hardcoding the two filenames would
still pass after the force guard was unregistered — pinning the derived answer
instead of the derivation (#458/#466).

**What this module deliberately does not assert:** that the *target* guard
allows these shapes. That is today's gap, not a contract, and pinning it would
freeze the hole into the suite — the same call #557 made when it removed rather
than weakened an assertion here. Every assertion below is about the pair, so
closing the gap in ``pushesIn`` later leaves this module green.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit._prose import REPO_ROOT  # noqa: E402

_HOOKS_DIR = REPO_ROOT / "hooks"
_HOOKS_JSON = _HOOKS_DIR / "hooks.json"

#: The three shapes #562 measured walking past the target guard. Each carries a
#: push to a protected branch on a channel no static lexer can read, so the only
#: honest verdict is a refusal.
_UNREADABLE_SHAPES = [
    pytest.param('sh <<< "git push origin HEAD:main"', id="here-string"),
    pytest.param('echo "git push origin HEAD:main" | sh', id="pipe-into-sh"),
    pytest.param(
        'cat <(echo "git push origin HEAD:main") | bash', id="process-substitution"
    ),
]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on ``main`` with one commit and no gate marker.

    The fallback protected set applies and no marker covers the tree, so a
    readable ``git push origin HEAD:main`` from here is a push the target guard
    refuses. That is what makes an *unrefused* shape meaningful rather than an
    artefact of a permissive fixture.
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


def _bash_hooks() -> list[Path]:
    """Every hook ``hooks.json`` registers against the ``Bash`` tool.

    Derived, not listed. A matcher is a regex over the tool name, so this asks
    each ``PreToolUse`` matcher whether it matches ``Bash`` rather than assuming
    the literal string — and returns the hook scripts in registration order.
    """
    spec = json.loads(_HOOKS_JSON.read_text())
    found: list[Path] = []
    for entry in spec.get("hooks", {}).get("PreToolUse", []):
        if not re.search(entry.get("matcher", ""), "Bash"):
            continue
        for hook in entry.get("hooks", []):
            name = Path(hook.get("command", "").split()[-1]).name
            script = _HOOKS_DIR / name
            if script.is_file():
                found.append(script)
    return found


def _decisions(command: str, repo: Path) -> dict[str, str | None]:
    """Each registered ``Bash`` guard's verdict on ``command``, by filename."""
    payload = json.dumps(
        {"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": command}}
    )
    verdicts: dict[str, str | None] = {}
    for script in _bash_hooks():
        proc = subprocess.run(
            [_node(), str(script)],
            input=payload,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ},
        )
        assert proc.returncode == 0, (
            f"{script.name} must never exit non-zero: {proc.stderr}"
        )
        assert proc.stdout.strip(), (
            f"{script.name} wrote no decision at all: {proc.stderr}"
        )
        output = json.loads(proc.stdout).get("hookSpecificOutput", {})
        verdicts[script.name] = output.get("permissionDecision")
    return verdicts


@pytest.mark.parametrize("command", _UNREADABLE_SHAPES)
def test_the_registered_bash_guards_refuse_an_unreadable_script(
    command: str, repo: Path
) -> None:
    """Some registered guard refuses each shape — which one is not the contract.

    The assertion is deliberately over the *set*: #562's decision was that the
    refusal lives in one guard and is relied on by the other, so requiring a
    particular guard to be the one that denies would re-import the duplication
    the decision refused. What must hold is that the shipped registration, run
    as the session runs it, does not let an unreadable script through.
    """
    verdicts = _decisions(command, repo)

    assert verdicts, (
        "no hook is registered against Bash at all — the composed control this "
        "module documents does not exist"
    )
    assert "deny" in verdicts.values(), (
        f"{command!r} runs a script no lexer can read, and every registered Bash "
        f"guard allowed it: {verdicts}. Either the force guard's "
        "isBareShellFedExternally was narrowed or it is no longer registered; "
        "#562 records that push-target-guard.js does not cover this class alone."
    )


def test_the_registered_bash_guards_allow_an_ordinary_command(repo: Path) -> None:
    """The control, and the reason the assertion above is an observation.

    Without it a pair that denied *everything* — a crashing guard, a fixture that
    made every command look like a push — would satisfy every case above and
    prove nothing (#538: a control that never reaches the predicate is vacuous).
    ``git status`` is readable, is not a push, and must pass all the way through.
    """
    verdicts = _decisions("git status", repo)

    assert verdicts, "no hook is registered against Bash at all"
    assert "deny" not in verdicts.values(), (
        f"an ordinary readable command was refused: {verdicts}. The guards are "
        "denying for some reason other than the one under test, so the refusals "
        "asserted above are not evidence."
    )
