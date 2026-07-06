"""CAL-1031 — PreToolUse Bash hook that *parses* git-push force forms.

CAL-1001 closed the ``+refspec`` bypass with ``Bash(...)`` deny **globs** in
``.claude/settings.json``. Globs over the raw command string cannot cover the
full force-push bypass class, though: short-flag bundles (``-f``, ``-fq``,
``-qf``), ``--force`` in a trailing position, a ``+refspec`` with the remote
omitted (``git push +HEAD:dev``), and ``git -c … push`` / ``git -C … push``
argument reordering all slip past a fixed set of globs. The durable fix flagged
in CAL-1001's residual is a **hook that tokenizes the command** and decides from
the parse, not from a pattern.

``hooks/git-push-guard.js`` is that parser layer. It runs as a ``PreToolUse``
hook on ``Bash`` and, when a sub-command is a ``git push``, **denies** (emits the
current ``hookSpecificOutput.permissionDecision: "deny"`` contract) if any of:
``-f`` / ``--force`` / ``--force-with-lease`` in any position or short-flag
bundle, or any refspec beginning with ``+``. The existing deny globs stay as
belt-and-braces; this is the parser layer on top.

These tests execute the hook as a node subprocess (in the style of
``test_registry_self_version_hook``) and assert the decision over two corpora:

* **AC-1 — the bypass corpus is denied.** Every force-push spelling in
  :data:`_MUST_DENY`, including the forms a glob cannot reach.
  :func:`test_bypass_corpus_is_denied`.
* **AC-2 — the allowed corpus passes.** Every non-force push and non-push git
  command in :data:`_MUST_ALLOW` — crucially the exact pushes the verbs run
  (``close``'s ``push origin <base>``, ``checkpoint``'s ``push origin <branch>``,
  teardown's ``push origin --delete``) plus ``git worktree remove --force`` (a
  ``--force`` whose sub-command is *not* ``push``) — is **not** denied.
  :func:`test_allowed_corpus_passes`.
* **AC-3 — a non-Bash tool call is passed straight through.**
  :func:`test_non_bash_tool_is_passed_through`.
* **AC-4 — the hook is wired.** Both the repo's own ``.claude/settings.json``
  *and* the installed-surface template ``settings/harness.json`` register the
  hook under a ``PreToolUse`` matcher that covers ``Bash`` — so it is live here
  and delivered to every self-hosting target repo alongside the other hooks.
  :func:`test_hook_is_registered_for_pretooluse_bash`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "git-push-guard.js"
#: Both settings surfaces that must wire the hook: the repo's own live config and
#: the installed-surface template copied into target repos.
_SETTINGS_FILES = [
    _REPO_ROOT / ".claude" / "settings.json",
    _REPO_ROOT / "settings" / "harness.json",
]


# --- corpora ------------------------------------------------------------------

# Force-push spellings that MUST be denied. Every one force-pushes; several are
# forms a fixed deny-glob set cannot reach (short-flag bundles, trailing/leading
# ``--force``, remote-omitted ``+refspec``, ``git -c``/``-C`` reordering,
# env-prefix and compound commands).
_MUST_DENY = [
    # --force flag, every position
    "git push --force origin dev",
    "git push origin dev --force",
    "git push origin --force dev",
    # short-flag bundles containing 'f'
    "git push -f origin dev",
    "git push -fq origin dev",
    "git push -qf origin dev",
    "git push -f",
    # --force-with-lease, plain and with a value, in either position
    "git push --force-with-lease origin dev",
    "git push origin --force-with-lease dev",
    "git push --force-with-lease=refs/heads/dev:abc123 origin dev",
    # +refspec force forms (the CAL-1001 class), incl. remote omitted and quoted
    "git push origin +HEAD:dev",
    "git push origin +refs/heads/x:dev",
    "git push +HEAD:dev",
    'git push origin "+HEAD:dev"',
    # git global-option reordering before the push sub-command
    "git -C /some/worktree push --force origin dev",
    "git -C /some/worktree push origin +HEAD:dev",
    "git -c push.default=simple push --force origin dev",
    # hidden inside a larger shell command
    "FOO=bar git push --force origin dev",
    "cd /tmp && git push --force origin dev",
    "git push origin main && git push --force origin dev",
    "echo start; git push -f origin dev",
]

# Non-force pushes and non-push commands that MUST stay allowed — the exact
# forms the verbs run, plus false-positive traps (a ``--force`` that is not a
# push; the words "force"/"push" as commit-message text; a push-force string
# quoted inside an ``echo``).
_MUST_ALLOW = [
    # the pushes the verbs actually issue
    "git push origin dev",  # close: push origin <base>
    "git push origin HEAD:dev",
    "git push origin abc1234:dev",
    "git -C /some/worktree push origin HEAD:dev",  # checkpoint
    "git push origin --delete my-feature",  # teardown --delete
    "git push -u origin my-feature",  # push -u
    "git push --set-upstream origin my-feature",
    "git push origin :my-feature",  # colon-delete: leading ':' is not '+'
    "git push origin my-feature-branch",
    "git push",
    "git -c user.name=x push origin dev",  # -c reordering, but NOT a force
    # a --force whose sub-command is NOT push
    "git worktree remove --force /some/path",
    # the words force/push appear, but not as a push flag/refspec
    'git commit -m "force the push through"',
    "git status",
    "git log --oneline -5",
    'echo "git push --force origin dev"',
]


# --- runner -------------------------------------------------------------------


def _run_hook(payload: dict) -> dict:
    """Run the hook with ``payload`` on stdin; return its parsed JSON stdout."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    proc = subprocess.run(
        [node, str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored (rc={proc.returncode}): {proc.stderr}"
    assert proc.stdout.strip(), f"hook produced no output for {payload!r}"
    return json.loads(proc.stdout)


def _is_denied(command: str) -> bool:
    """True iff the hook denies a Bash call running ``command``."""
    out = _run_hook({"tool_name": "Bash", "tool_input": {"command": command}})
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    return decision == "deny"


# --- AC-1: the bypass corpus is denied ----------------------------------------


@pytest.mark.parametrize("command", _MUST_DENY)
def test_bypass_corpus_is_denied(command: str) -> None:
    assert _is_denied(command), f"force-push not denied by the hook: {command!r}"


# --- AC-2: the allowed corpus passes ------------------------------------------


@pytest.mark.parametrize("command", _MUST_ALLOW)
def test_allowed_corpus_passes(command: str) -> None:
    assert not _is_denied(command), f"non-force command wrongly denied: {command!r}"


# --- AC-3: a non-Bash tool call is passed straight through --------------------


def test_non_bash_tool_is_passed_through() -> None:
    out = _run_hook(
        {"tool_name": "Edit", "tool_input": {"file_path": "x", "new_string": "git push --force"}}
    )
    assert out.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"


# --- AC-4: the hook is wired for PreToolUse Bash ------------------------------


@pytest.mark.parametrize("settings_path", _SETTINGS_FILES, ids=lambda p: p.name)
def test_hook_is_registered_for_pretooluse_bash(settings_path: Path) -> None:
    settings = json.loads(settings_path.read_text())
    pretooluse = settings.get("hooks", {}).get("PreToolUse", [])
    for entry in pretooluse:
        matcher = entry.get("matcher", "")
        if "Bash" not in matcher.split("|"):
            continue
        commands = " ".join(h.get("command", "") for h in entry.get("hooks", []))
        if "git-push-guard.js" in commands:
            return
    raise AssertionError(
        f"git-push-guard.js is not registered under a PreToolUse Bash matcher in "
        f"{settings_path.relative_to(_REPO_ROOT)}"
    )
