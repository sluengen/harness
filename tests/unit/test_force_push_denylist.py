"""Force-push deny-list — ``.claude/settings.json`` blocks every force-push
spelling to the protected ``dev`` branch, including the plus-refspec form that
carries no flag at all.

CAL-1001: the deny-list denied only the flag spellings (``git push --force …``,
``--force-with-lease …``). The plus-refspec form force-pushes with no flag —
``git push origin +HEAD:dev`` — and matched none of the deny patterns, so under
the blanket ``Bash(*)`` allow a prompt-injected or misbehaving autonomous agent
could force-overwrite ``dev`` (which the deny-list exists to prevent). This guard
pins that the deny-list covers **both** the flag and the refspec force forms, and
that plain (non-force) pushes stay allowed.

The check replicates Claude Code's ``Bash(<pattern>)`` matching: ``*`` is a
wildcard over any run of characters and the pattern is matched against the whole
command string. ``fnmatch`` models that ``*``-glob faithfully for these patterns,
which use only ``*`` wildcards over literal git-command text.
"""

from __future__ import annotations

import fnmatch
import json

from tests.unit._prose import REPO_ROOT

_SETTINGS = REPO_ROOT / ".claude" / "settings.json"

_BASH_PREFIX = "Bash("


def _deny_globs() -> list[str]:
    """The raw command globs of the ``Bash(...)`` deny rules in settings.json."""
    deny = json.loads(_SETTINGS.read_text())["permissions"]["deny"]
    return [
        rule[len(_BASH_PREFIX) : -1]
        for rule in deny
        if rule.startswith(_BASH_PREFIX) and rule.endswith(")")
    ]


def _is_denied(command: str) -> bool:
    """True if any deny glob matches ``command`` (Claude Code ``*``-glob, deny > allow)."""
    return any(fnmatch.fnmatchcase(command, glob) for glob in _deny_globs())


# Force-push spellings that MUST be denied — ``dev`` is the protected branch.
_MUST_DENY = [
    # Plus-refspec force forms — the bypass CAL-1001 closes.
    "git push origin +HEAD:dev",
    "git push origin +refs/heads/x:dev",
    "git -C /some/worktree push origin +refs/heads/x:dev",
    # Flag force forms — regression pin that the pre-existing coverage still holds.
    "git push --force origin dev",
    "git push origin --force-with-lease dev",
    "git -C /some/worktree push --force origin dev",
    # CAL-1142: `git -C <worktree> push --force-with-lease …` — the unattended
    # routine operates on worktrees via `git -C`, and the pre-existing `-C` deny
    # covered only plain `--force`, not `--force-with-lease`, so this walked
    # straight through the guard. Both flag positions.
    "git -C /some/worktree push --force-with-lease origin dev",
    "git -C /some/worktree push origin --force-with-lease dev",
]

# Plain, non-force pushes that MUST stay allowed (never matched by a deny glob).
_MUST_ALLOW = [
    "git push origin dev",
    "git push origin HEAD:dev",
    "git push origin feature:dev",
    "git push origin my-feature-branch",
    "git -C /some/worktree push origin HEAD:dev",
]


def test_force_push_forms_are_denied() -> None:
    for command in _MUST_DENY:
        assert _is_denied(command), f"force-push not denied by the deny-list: {command!r}"


def test_plain_pushes_remain_allowed() -> None:
    for command in _MUST_ALLOW:
        assert not _is_denied(command), f"plain push wrongly denied by the deny-list: {command!r}"
