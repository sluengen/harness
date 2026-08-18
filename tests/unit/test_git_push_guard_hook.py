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

These tests execute the hook as a node subprocess
and assert the decision over two corpora:

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

CAL-1088 pins the hook's **recognition-set membership** so a set cannot gain a
member without a matching deny case. The guard decides push-ness from three sets
(``WRAPPERS`` / ``SHELLS`` / ``GIT_GLOBAL_WITH_ARG``); their membership was
untested, which is how ``WRAPPERS``' lone member (``env``) slipped through with
zero cases. Rather than restate the membership (a copy that drifts), these tests
read the real sets the hook **exports** and derive one canonical deny case per
member:

* **AC-5 — every set member denies a canonical force-push.** The membership is
  read from the hook via ``require()`` (not parsed from source), and each member
  is exercised through its own construct.
  :func:`test_every_set_member_denies_canonical_force_push`.
* **AC-6 — an uncovered member fails the gate.** The same assertion the per-member
  test uses raises for a would-be member the guard does not deny — so a member
  added without a working deny path is a gate failure, demonstrated by execution
  rather than asserted by inspection.
  :func:`test_uncovered_set_member_fails_the_gate`.
* **AC-7 — the derived cases are membership-locked, not a hand-written copy.** One
  canonical case per member, read from the hook, adding coverage the narrative-
  vector corpus omits (``sudo``/``doas``, ``zsh``/``dash``/``ash``/``ksh``, the
  ``git`` global options) rather than duplicating it.
  :func:`test_derived_cases_are_membership_locked_not_a_handwritten_copy`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

_HOOK = REPO_ROOT / "hooks" / "git-push-guard.js"
#: Both settings surfaces that must wire the hook: the repo's own live config and
#: the installed-surface template copied into target repos.
_SETTINGS_FILES = [
    REPO_ROOT / ".claude" / "settings.json",
    REPO_ROOT / "settings" / "harness.json",
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
    # command substitution: it executes inline, so these really force-push. The
    # guard captures the substitution opaquely (not as a separator), recurses
    # into its body, and fails closed when one lands in a push decision slot.
    "git push origin $(printf dev) --force",  # subst operand + literal --force
    "git $(printf push) --force origin dev",  # sub-command hidden in a subst
    "git push origin $(printf '+HEAD:dev')",  # the +refspec is inside the subst
    "echo $(git push --force origin dev)",  # inner force-push (recursion)
    "out=$(git push -f origin dev)",  # inner force-push in an assignment subst
    "echo `git push -f origin dev`",  # backtick form (recursion)
    "git push origin `printf dev` --force",  # backtick operand + literal --force
    # inline shell scripts: sh -c / bash -c / eval run their string as a shell
    # command, so the force-push hides behind an 'sh'/'eval' executable.
    'sh -c "git push --force origin dev"',
    'bash -c "git push -f origin dev"',
    'bash -lc "git push --force origin dev"',  # bundled -lc still means -c
    'eval "git push --force origin dev"',
    "eval git push -f origin dev",  # unquoted eval
    # ANSI-C quoting decodes escapes: $'\x67it' -> 'git', $'\x2df' -> '-f'.
    r"$'\x67it' push --force origin dev",  # 'git' hex-obfuscated
    r"git push $'\x2df' origin dev",  # '-f' hex-obfuscated
    r"$'\147it' push -f origin dev",  # 'git' octal-obfuscated
    # brace group / function body: the force-push runs inline in the shell.
    "{ git push --force origin dev; }",
    "f() { git push --force origin dev; }; f",
    "function f() { git push -f origin dev; }; f",
    # a bare shell fed a script it can't read (pipe / here-string / heredoc /
    # process substitution) fails closed.
    'echo "git push --force origin dev" | bash',
    'printf "%s\\n" "git push --force origin dev" | sh',
    'sh <<< "git push --force origin dev"',
    'cat <(echo "git push --force origin dev") | bash',
    # a path-qualified git is still git: the executable is matched on its
    # basename, the way nested shells already are.
    "/usr/bin/git push --force origin dev",
    "./git push -f origin dev",
    "/usr/local/bin/git push origin +HEAD:dev",
    # command wrappers run their operands as the real command, so the force-push
    # is one token further along. Each wrapper is pinned here, because an
    # unpinned member of the set is how the whole class went unnoticed.
    "env git push --force origin dev",  # the set's original member, previously unpinned
    "nohup git push --force origin dev",
    "command git push --force origin dev",
    "exec git push -f origin dev",
    "nice git push --force origin dev",
    "ionice git push --force origin dev",
    "setsid git push -f origin dev",
    "stdbuf -o0 git push --force origin dev",  # wrapper carrying its own option
    "xargs git push --force origin dev",
    "nice -n 5 git push --force origin dev",  # option that consumes its argument
    "exec -a fakename git push -f origin dev",
    "timeout 60 git push --force origin dev",  # wrapper with a mandatory operand
    "timeout --signal=KILL 60 git push -f origin dev",
    # wrappers compose, with each other and with the existing prefix classes
    "env nohup git push --force origin dev",
    "nohup env FOO=bar git push -f origin dev",
    "env /usr/bin/git push --force origin dev",  # wrapper + path-qualified git
    "nohup git -C /some/worktree push --force origin dev",  # wrapper + git global opt
    # a wrapper inside a nested shell script is caught by the same recursion
    'sh -c "nohup git push --force origin dev"',
    'bash -c "timeout 60 git push -f origin dev"',
    'eval "nohup git push --force origin dev"',
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
    # a command substitution in a NON-push git command (or no git push at all)
    # must NOT fail closed — only pushes are the guard's concern.
    'git commit -m "$(printf msg)"',
    'git tag -m "$(whoami)" v1',
    "echo $(date)",
    # shell-wrapper recursion must not over-deny a non-force nested command
    'sh -c "git push origin dev"',
    'bash -c "git status"',
    # ANSI-C quoting in a non-push git command is fine
    r"git commit -m $'fix\ttabbed'",
    # ${VAR} parameter expansion is captured opaquely, not severed like a brace
    # group — a plain push with a computed branch is not force and stays allowed.
    "git push origin ${BRANCH}",
    # a brace group whose body is a non-force push is fine
    "{ git push origin dev; }",
    # a pipeline whose sink is NOT a shell is untouched
    "git log --oneline | cat",
    # a bare shell running a script FILE (no pipe / redirect) is out of scope
    "bash deploy.sh",
    # wrapper-stripping must not over-deny: the verbs' own pushes stay allowed
    # when wrapped, and a wrapper on a non-push git command is untouched.
    "nohup git push origin dev",
    "timeout 60 git push origin HEAD:dev",
    "env git status",
    "nice git commit -m 'force the push through'",
    "/usr/bin/git push origin dev",  # path-qualified, but not a force
    "/usr/bin/git worktree remove --force /some/path",  # --force, sub-command not push
    # a wrapper name used as an ordinary operand is not a wrapper prefix
    "git commit -m 'add nohup to the wrapper set'",
    "echo nohup git push --force origin dev",  # echo is not a wrapper
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
        f"{settings_path.relative_to(REPO_ROOT)}"
    )


# --- CAL-1088: recognition-set membership is pinned by a derived deny corpus ---
#
# The guard decides push-ness from three recognition sets. Their *membership* is
# the thing that silently went short (``WRAPPERS`` held only ``env`` and had no
# cases). Instead of restating the membership here — a copy that drifts from the
# source — these tests read the real sets the hook exports and derive the deny
# corpus from them, so a set that gains a member gains a matching case for free.

#: Turn one member of a recognition set into a canonical force-push that reaches
#: ``git push --force`` *through that member's construct* — a wrapper prefix, a
#: shell ``-c`` script, or a ``git`` global option that consumes its argument.
#: ``x`` is an arbitrary operand for the global options that take one; the guard
#: does not validate it, it only must be consumed so the ``push`` sub-command is
#: read correctly.
_CONSTRUCTS = {
    "WRAPPERS": lambda m: f"{m} git push --force origin dev",
    "SHELLS": lambda m: f'{m} -c "git push --force origin dev"',
    "GIT_GLOBAL_WITH_ARG": lambda m: f"git {m} x push --force origin dev",
}


def _hook_sets() -> dict[str, list[str]]:
    """The hook's recognition sets, read from the module it exports.

    Runs a tiny node introspection subprocess that ``require()``s the hook and
    dumps each set — the alternative the ticket rejected (regex-parsing the
    ``new Set([...])`` literals) couples the test to source formatting. Requiring
    the module does **not** run the hook: its auto-run is guarded by
    ``require.main === module``. Skips when node is unavailable; fails loudly if
    the hook does not export the sets (the mechanism this ticket adds).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    script = (
        "const h = require(process.env.HOOK_PATH);"
        "const names = ['WRAPPERS', 'SHELLS', 'GIT_GLOBAL_WITH_ARG'];"
        "const out = {};"
        "for (const k of names) {"
        "  if (!(h[k] instanceof Set)) {"
        "    console.error('hook does not export set: ' + k);"
        "    process.exit(3);"
        "  }"
        "  out[k] = [...h[k]];"
        "}"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [node, "-e", script],
        text=True,
        capture_output=True,
        env={**os.environ, "HOOK_PATH": str(_HOOK)},
        timeout=30,
    )
    assert proc.returncode == 0, (
        "could not read the hook's recognition sets via require() — the hook must "
        f"export WRAPPERS/SHELLS/GIT_GLOBAL_WITH_ARG (rc={proc.returncode}): "
        f"{proc.stderr.strip()}"
    )
    return json.loads(proc.stdout)


def _assert_member_denies(set_name: str, member: str, command: str) -> None:
    """The single assertion both the per-member sweep (AC-5) and the teeth test
    (AC-6) run: a recognition-set member must deny its canonical force-push."""
    assert _is_denied(command), (
        f"{set_name} member {member!r} does not deny a canonical force-push — "
        f"a recognition-set member with no working deny path: {command!r}"
    )


# --- AC-5: every set member denies a canonical force-push ---------------------


@pytest.mark.parametrize("set_name", list(_CONSTRUCTS))
def test_every_set_member_denies_canonical_force_push(set_name: str) -> None:
    members = _hook_sets()[set_name]
    assert members, f"the hook exported no members for {set_name}"
    template = _CONSTRUCTS[set_name]
    for member in members:
        _assert_member_denies(set_name, member, template(member))


# --- AC-6: an uncovered member fails the gate (demonstrated, not inspected) ----


def test_uncovered_set_member_fails_the_gate() -> None:
    """A would-be set member the guard does not deny makes the very assertion the
    per-member sweep uses raise — so adding a member without a working deny path
    is a gate failure, shown by execution. ``definitelynotawrapper`` stands in
    for such a member: it is not in ``WRAPPERS``, so its operands are not scanned
    and the canonical force-push is *not* denied."""
    bogus = "definitelynotawrapper"
    command = _CONSTRUCTS["WRAPPERS"](bogus)
    assert not _is_denied(command), (
        "demonstration precondition failed: the stand-in member was denied, so it "
        f"cannot represent an uncovered member: {command!r}"
    )
    with pytest.raises(AssertionError):
        _assert_member_denies("WRAPPERS", bogus, command)


# --- AC-7: the derived corpus is membership-locked, not a hand-written copy ----


def test_derived_cases_are_membership_locked_not_a_handwritten_copy() -> None:
    """One canonical case per member, read from the hook — not a re-listing of the
    hand-written per-member deny lines. Proven two ways: the derived corpus is
    exactly one command per member (minimal), and it covers members the
    narrative-vector corpus omits entirely (``sudo``/``doas``, ``zsh``/``dash``/
    ``ash``/``ksh``, the ``git`` global options), so it cannot be a copy of
    :data:`_MUST_DENY`."""
    sets = _hook_sets()
    generated = [_CONSTRUCTS[name](m) for name, members in sets.items() for m in members]
    total_members = sum(len(members) for members in sets.values())
    assert len(generated) == total_members, (
        "the derived corpus must be exactly one canonical case per member "
        f"({total_members}), not a broader re-listing: got {len(generated)}"
    )
    novel = [command for command in generated if command not in _MUST_DENY]
    assert novel, (
        "every derived case already appears verbatim in _MUST_DENY — the derived "
        "corpus must add coverage for members the hand-written cases omit, not "
        "duplicate them"
    )
