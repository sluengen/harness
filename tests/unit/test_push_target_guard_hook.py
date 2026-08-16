"""#436 — the push-target guard: no push to a protected branch without evidence.

``hooks/git-push-guard.js`` refuses a push that *rewrites* history. This one
refuses a push that *lands unverified work*: a ``git push`` whose **target** is a
protected branch is denied unless a gate marker covers the tree of the commit
being pushed.

Three things make this a real guard rather than a gesture, and each has tests
here.

**It reuses the hardened parser.** A second, naive ``split(" ")`` parser would be
walked past by ``sh -c "git push origin HEAD:dev"`` — a push the *force* guard
catches and a *target* guard with its own parser would not. That asymmetry is an
invitation, so this hook imports ``git-push-guard.js``'s lexer rather than
growing a weaker twin. :func:`test_a_nested_shell_is_not_a_way_around_the_guard`
and :func:`test_a_substitution_in_a_decision_slot_is_denied`.

**It resolves the directory the push will run in.** ``/build`` ships with
``cd "$worktree_path" && git push origin HEAD:dev``, so resolving ``HEAD`` at the
session cwd reads the wrong branch — and would happily find a marker for a tree
nobody is pushing. :func:`test_the_push_directory_is_the_one_the_cd_names` puts
two worktrees at *divergent* HEADs, which is the only shape where that bug is
visible at all.

**The allow path is produced by production code.** Every test here that expects
a pass runs ``scripts/gate_marker.py write`` — the writer ``verify.sh`` runs — and
never hand-authors a marker file. A test that wrote its own marker would be
validating the hook against the *test's* idea of the contract, which is the
"fixture agreeing with itself" the acceptance criteria rule out. The path
equivalence that makes this work is measured in ``test_gate_marker_contract.py``.

Acceptance criteria:

* **AC-1** — the refusal and the allow are both exercised for real, and the
  refusal is reached three different ways: no marker at all
  (:func:`test_a_push_to_a_protected_branch_without_a_marker_is_denied`), a
  marker made stale by one more commit
  (:func:`test_one_more_commit_makes_the_marker_stale`), and a marker deleted
  (:func:`test_deleting_the_marker_denies_the_same_push`). The allow is
  :func:`test_a_push_to_a_protected_branch_with_a_marker_passes`.
* **AC-2** — the guard is not simply denying everything. A push to an
  unprotected branch passes *with no marker present at all*
  (:func:`test_a_push_to_an_unprotected_branch_passes_without_any_marker`) —
  the failure mode a refusal-only suite cannot see.
* **AC-3** — the protected set comes from ``CONTEXT.md`` first and a
  conservative fallback second, and the fallback is over-broad on purpose: a
  false deny costs one gate run, a false allow lands unverified work on the
  integration branch of a repo that told the guidance nothing about itself.
  :func:`test_context_md_declares_the_protected_set` and
  :func:`test_without_context_md_the_conservative_fallback_applies`.
* **AC-4** — the unconditional refusals: deleting a protected branch, and
  ``--mirror`` / ``--all``, which move protected refs with no visible refspec.
  No evidence authorises those. :func:`test_deleting_a_protected_branch_is_denied`,
  :func:`test_mirror_and_all_are_denied`.
* **AC-5** — the hook is wired into both settings surfaces.
  :func:`test_hook_is_registered_for_pretooluse_bash`.
* **AC-6** — the fail-open/fail-closed split of the design's §8. State 1 (the
  hook could not run) opens loudly and is owned by
  ``test_hooks_fail_open_is_loud.py``; state 2 (it ran but could not establish
  the facts) closes. :func:`test_an_unresolvable_source_is_denied` and
  :func:`test_an_ambiguous_push_directory_is_denied`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "push-target-guard.js"
WRITER = REPO_ROOT / "scripts" / "gate_marker.py"

#: Both settings surfaces that must wire the hook: the repo's own live config
#: and the installed-surface template copied into target repos.
SETTINGS_FILES = [REPO_ROOT / ".claude" / "settings.json", REPO_ROOT / "settings" / "harness.json"]


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


def _commit(repo: Path, name: str, body: str) -> None:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on ``main`` with one commit and no ``CONTEXT.md``.

    No ``CONTEXT.md``, so the conservative fallback set applies and ``main`` is
    protected — the shape a consuming repo has before it has told the guidance
    anything about itself.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _commit(root, "a.txt", "one\n")
    return root


def _write_marker(cwd: Path) -> str:
    """Produce a marker with the **production** writer and return its tree.

    Never a hand-authored file: the marker contract is what is under test, and a
    test that authored its own copy of it would agree with itself no matter what
    the hook did.
    """
    proc = subprocess.run(
        [sys.executable, str(WRITER), "write"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"the production writer failed: {proc.stderr}"
    # "gate marker: <tree> -> <path>"
    return proc.stdout.split(":", 1)[1].split("->")[0].strip()


def _decision(command: str, cwd: Path, *, env: dict[str, str] | None = None) -> str | None:
    """The hook's ``permissionDecision`` for a Bash call running ``command``."""
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    proc = subprocess.run(
        [_node(), str(HOOK)],
        input=json.dumps(payload),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, f"hook errored (rc={proc.returncode}): {proc.stderr}"
    assert proc.stdout.strip(), f"hook produced no output for {command!r}: {proc.stderr}"
    return json.loads(proc.stdout).get("hookSpecificOutput", {}).get("permissionDecision")


def _denied(command: str, cwd: Path, **kwargs: object) -> bool:
    return _decision(command, cwd, **kwargs) == "deny"  # type: ignore[arg-type]


# --- AC-1: the allow path, produced by production code ------------------------


def test_a_push_to_a_protected_branch_with_a_marker_passes(repo: Path) -> None:
    """The gate ran green over this exact tree, so the push is authorised.

    There is no command-based exemption for ``/ship`` or ``/routine`` and none is
    needed: those paths push a gated tree, and a gated tree is the only
    authorisation a hook can actually verify.
    """
    _write_marker(repo)

    assert not _denied("git push origin HEAD:main", repo)


# --- AC-1: three roads to the refusal -----------------------------------------


def test_a_push_to_a_protected_branch_without_a_marker_is_denied(repo: Path) -> None:
    assert _denied("git push origin HEAD:main", repo)


def test_one_more_commit_makes_the_marker_stale(repo: Path) -> None:
    """The control that changes the **input**, not the evidence.

    The marker is still there and still valid; the tree moved out from under it.
    This is the whole difference between "a gate ran recently" and "the gate ran
    over these bytes", and it is the single case that distinguishes tree
    identity from marker presence.
    """
    _write_marker(repo)
    assert not _denied("git push origin HEAD:main", repo), "the fixture never allowed"

    _commit(repo, "b.txt", "two\n")

    assert _denied("git push origin HEAD:main", repo)


def test_deleting_the_marker_denies_the_same_push(repo: Path) -> None:
    """The control that changes the **evidence**, not the input. Together with
    the case above it pins the marker as load-bearing rather than incidental."""
    tree = _write_marker(repo)
    assert not _denied("git push origin HEAD:main", repo), "the fixture never allowed"

    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    (common / "harness" / "gate" / f"{tree}.json").unlink()

    assert _denied("git push origin HEAD:main", repo)


def test_a_marker_older_than_the_bound_is_not_evidence(repo: Path) -> None:
    """The freshness bound exists for toolchain drift under an unchanged tree —
    the venv is not in the tree, ``uv.lock`` is.

    Both directions on the *same* back-dated file, so the deny is attributable to
    the age rather than to anything else about the marker: with the default bound
    a two-day-old marker is refused, and with a bound wide enough to cover it the
    identical file authorises the identical push.
    """
    tree = _write_marker(repo)
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    marker = common / "harness" / "gate" / f"{tree}.json"
    two_days_ago = time.time() - 2 * 86400
    os.utime(marker, (two_days_ago, two_days_ago))

    assert _denied("git push origin HEAD:main", repo)
    assert not _denied(
        "git push origin HEAD:main", repo, env={"HARNESS_GATE_MARKER_MAX_AGE_SECONDS": "1000000"}
    ), "the same marker under a wider bound must authorise the same push"


# --- AC-2: the guard is not simply denying everything -------------------------


def test_a_push_to_an_unprotected_branch_passes_without_any_marker(repo: Path) -> None:
    """The negative control the refusal cases cannot supply. Task branches are
    where nearly all pushing happens; a guard that denied them would be
    uninstalled within a day."""
    assert not _denied("git push origin HEAD:feat/x", repo)
    assert not _denied("git push origin feat/x", repo)


def test_a_non_bash_tool_is_passed_through(repo: Path) -> None:
    payload = {
        "tool_name": "Edit",
        "cwd": str(repo),
        "tool_input": {"file_path": "x", "new_string": "git push origin HEAD:main"},
    }
    proc = subprocess.run(
        [_node(), str(HOOK)],
        input=json.dumps(payload),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert json.loads(proc.stdout) == {"continue": True}


def test_a_command_that_is_not_a_push_is_passed_through(repo: Path) -> None:
    for command in ("git status", "git commit -m 'push to main'", "echo git push origin main"):
        assert not _denied(command, repo), command


def test_outside_a_repository_the_guard_passes_through(tmp_path: Path) -> None:
    """Nothing to verify and nothing to protect. Denying here would break every
    ``git push`` a session makes from a directory that is not a checkout."""
    assert not _denied("git push origin HEAD:main", tmp_path)


# --- AC-3: which branches are protected ---------------------------------------


def test_context_md_declares_the_protected_set(repo: Path) -> None:
    """``CONTEXT.md``'s ``branches:`` block is authoritative where it exists.

    The branch name is one the fallback set has never heard of, so a guard that
    ignored ``CONTEXT.md`` and leaned on the fallback would pass this push and
    fail here. That is the point: the assertion cannot be satisfied by the
    fallback.
    """
    (repo / "CONTEXT.md").write_text(
        "# CONTEXT\n\n```yaml\nbranches:\n"
        "  integration: canary   # inline comment\n"
        "  release: main\n"
        "```\n"
    )

    assert _denied("git push origin HEAD:canary", repo)
    assert not _denied("git push origin HEAD:dev", repo), (
        "dev is not in this repo's declared branches, so the declared set must "
        "replace the fallback rather than union with it"
    )


def test_without_context_md_the_conservative_fallback_applies(repo: Path) -> None:
    """Deliberately over-broad. A false deny is recoverable in one command; a
    false allow lands unverified work on someone's integration branch."""
    for branch in ("main", "master", "dev", "develop", "trunk", "staging", "release", "production"):
        assert _denied(f"git push origin HEAD:{branch}", repo), branch


# --- AC-4: the unconditional refusals -----------------------------------------


def test_deleting_a_protected_branch_is_denied(repo: Path) -> None:
    """No evidence authorises deleting ``main``, so the marker is not consulted:
    both spellings are denied *with* a fresh marker in place."""
    _write_marker(repo)

    assert _denied("git push origin --delete main", repo)
    assert _denied("git push origin :main", repo)


def test_mirror_and_all_are_denied(repo: Path) -> None:
    """Both move protected refs with no visible refspec, so there is no target
    to evaluate and no tree to check. Denied with a fresh marker present."""
    _write_marker(repo)

    assert _denied("git push --mirror origin", repo)
    assert _denied("git push --all origin", repo)


def test_tags_alone_are_allowed(repo: Path) -> None:
    """A tag is not a branch. Denying ``--tags`` would block release tagging for
    no protection at all."""
    assert not _denied("git push --tags origin", repo)


# --- the parser reuse, which is why there is only one shell parser here -------


def test_a_nested_shell_is_not_a_way_around_the_guard(repo: Path) -> None:
    """``sh -c "git push origin HEAD:main"`` is a push the force guard already
    sees. A target guard with its own naive parser would not, and that asymmetry
    is exactly the hole an evader looks for."""
    assert _denied('sh -c "git push origin HEAD:main"', repo)
    assert _denied('bash -lc "git push origin HEAD:main"', repo)


def test_a_substitution_in_a_decision_slot_is_denied(repo: Path) -> None:
    """A command substitution executes inline, so the guard cannot statically
    prove what the refspec resolves to. Fails closed, with a marker present, to
    show the deny is about the ambiguity and not about missing evidence.

    **Both slots, and the second one is the one that matters.** The mutation run
    caught this: with the substitution check disabled, the *source*-slot case
    below is still denied — for an unrelated reason, because
    ``$(echo HEAD)^{tree}`` does not resolve — so on its own it certifies a guard
    that has no substitution check at all. The *target*-slot case has no such
    understudy: ``HEAD`` resolves, the marker covers it, and ``$(echo main)`` is
    not a member of the protected set, so without the check this push to a
    protected branch is waved straight through.
    """
    _write_marker(repo)

    assert _denied("git push origin $(echo HEAD):main", repo)
    assert _denied("git push origin HEAD:$(echo main)", repo), (
        "a substitution in the target slot resolves to a protected branch at run "
        "time while reading as an unknown branch name statically — the one shape "
        "where nothing else in the predicate closes the hole"
    )


def test_git_dash_c_names_the_push_directory(repo: Path, tmp_path: Path) -> None:
    """``git -C <path> push`` runs in ``<path>``. The unattended routine drives
    worktrees this way, so reading the tree at the hook's cwd would check the
    wrong one.

    The hook's cwd is a **second, ungated repository** rather than a plain
    directory. That distinction is load-bearing and was found by predicting the
    mutation: with a non-repo cwd the guard passes through, so a hook that
    ignored ``-C`` entirely would still satisfy this test. Against an ungated
    repo, ignoring ``-C`` denies.
    """
    _write_marker(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _git(elsewhere, "init", "-q", "--initial-branch=main")
    _git(elsewhere, "config", "user.email", "t@example.com")
    _git(elsewhere, "config", "user.name", "t")
    _commit(elsewhere, "other.txt", "never gated\n")

    assert not _denied(f"git -C {repo} push origin HEAD:main", elsewhere)
    assert _denied("git push origin HEAD:main", elsewhere), (
        "the ungated control repo must itself be refused, or the assertion above "
        "would hold for a guard that simply never denies"
    )


def test_the_push_directory_is_the_one_the_cd_names(repo: Path, tmp_path: Path) -> None:
    """The bug that is invisible without two divergent HEADs.

    ``/build``'s ship step is literally ``cd "$worktree_path" && git push origin
    HEAD:dev``. A guard that resolved ``HEAD`` at the session cwd would read the
    *root* checkout's tree — and here that tree has a marker, so it would happily
    authorise a push of a completely different, unverified tree.
    """
    _write_marker(repo)  # the root checkout IS verified
    worktree = tmp_path / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(worktree))
    _commit(worktree, "unverified.txt", "never gated\n")

    assert _denied(f"cd {worktree} && git push origin HEAD:main", repo), (
        "the guard resolved HEAD at the hook's cwd instead of the directory the "
        "cd names, so the root checkout's marker authorised a push of the "
        "worktree's ungated tree"
    )
    assert not _denied(f"cd {repo} && git push origin HEAD:main", repo), (
        "a cd back into the verified checkout must still pass, or the guard is "
        "merely denying every command that contains a cd"
    )


# --- AC-6: state 2 closes -----------------------------------------------------


def test_an_unresolvable_source_is_denied(repo: Path) -> None:
    """The hook ran and could not establish the facts. A push guard that denies
    on ambiguity costs one command to clear and protects the irreversible act,
    which is why it fails closed where the Stop hook fails open."""
    _write_marker(repo)

    assert _denied("git push origin no-such-ref:main", repo)


def test_an_ambiguous_push_directory_is_denied(repo: Path) -> None:
    """A ``cd`` target carrying a command substitution cannot be resolved
    statically, so the tree the push carries is unknowable."""
    _write_marker(repo)

    assert _denied("cd $(mktemp -d) && git push origin HEAD:main", repo)


# --- AC-5: the hook is wired --------------------------------------------------


@pytest.mark.parametrize("settings_path", SETTINGS_FILES, ids=lambda p: p.name)
def test_hook_is_registered_for_pretooluse_bash(settings_path: Path) -> None:
    settings = json.loads(settings_path.read_text())
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        if "Bash" not in entry.get("matcher", "").split("|"):
            continue
        commands = " ".join(h.get("command", "") for h in entry.get("hooks", []))
        if "push-target-guard.js" in commands:
            return
    raise AssertionError(
        "push-target-guard.js is not registered under a PreToolUse Bash matcher "
        f"in {settings_path.relative_to(REPO_ROOT)}, so it is installed and inert"
    )


def test_the_force_push_guard_still_decides_its_own_class(repo: Path) -> None:
    """Widening ``git-push-guard.js``'s exports must not change its decisions.

    Stated here rather than only in that hook's own suite, because this hook is
    the reason the exports widened: if importing the parser had side effects, the
    force guard is what would silently stop denying.
    """
    proc = subprocess.run(
        [_node(), str(REPO_ROOT / "hooks" / "git-push-guard.js")],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git push --force origin dev"}}
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )

    decision = json.loads(proc.stdout).get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny"
