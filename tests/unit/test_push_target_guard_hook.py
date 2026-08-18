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
  the facts) closes. :func:`test_an_unresolvable_source_is_denied`,
  :func:`test_an_ambiguous_push_directory_is_denied`, and — #452, where it fell
  open on the shipped ``cd "$worktree_path"`` idiom —
  :func:`test_a_variable_in_the_cd_target_is_denied`, floored by
  :func:`test_a_literal_cd_target_still_names_the_push_directory`. A directory is
  a decision slot in **both** of its spellings, so
  :func:`test_an_expansion_in_the_git_dash_c_operand_is_denied` covers the one the
  refusal itself points at; its over-denial floor is
  :func:`test_a_relative_dash_c_is_resolved_against_the_command_not_the_hook_process`.
* **AC-7** — #462, where the blacklist of expansions ran out of blacklist. Four
  more syntaxes — a glob ``*``, a glob ``?``, a character class ``[…]`` and a
  brace ``{…}`` — were allowed with no marker check in **both** directory slots,
  because each resolves statically to a path that does not exist while the shell
  expands it onto one that does. The directory slots are now decided by a
  whitelist, :func:`test_a_glob_in_a_push_directory_is_denied`, floored against
  becoming deny-everything by
  :func:`test_every_directory_this_repo_actually_has_is_readable`,
  :func:`test_the_named_legitimate_directory_idioms_are_readable` and
  :func:`test_a_gated_worktree_whose_path_contains_a_space_still_passes`. The
  refspec slot keeps the blacklist, because ``HEAD~1`` and ``HEAD@{0}`` are built
  from characters the directory whitelist refuses:
  :func:`test_the_directory_whitelist_is_not_applied_to_refspecs` and
  :func:`test_the_refspec_slot_keeps_its_own_expansion_predicate`.
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

from tests.unit._prose import REPO_ROOT

# size: one hook's acceptance matrix, and the hook is the repo's flagship
# mechanical guarantee — seven acceptance criteria, each needing its refusal, its
# never-deny control and (for the directory whitelist #462 added) its over-denial
# floor, because a fail-closed predicate with no floor is a deny-everything rule
# nobody would keep installed. Splitting it would separate a refusal from the
# floor that proves it is not universal, which is the pairing a reviewer reads.

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


def _hook_output(
    command: str,
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    proc_cwd: Path | None = None,
) -> dict[str, str]:
    """The hook's ``hookSpecificOutput`` for a Bash call running ``command``.

    Empty on a pass-through, which carries no such block at all. Most tests only
    need the decision and go through :func:`_decision`; a test that has to
    distinguish *which* refusal was reached reads the reason from here, because a
    deny reached for an unrelated cause satisfies a bare decision check.

    ``proc_cwd`` is the directory the **hook process itself** is launched in, as
    distinct from the payload's ``cwd``. They are the same in every ordinary
    case and the tests leave it alone; it exists because a relative path in the
    command — ``git -C .`` — is resolved by whichever of the two the hook
    consults, and those two answers are only distinguishable when they differ.
    """
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    proc = subprocess.run(
        [_node(), str(HOOK)],
        input=json.dumps(payload),
        cwd=proc_cwd if proc_cwd is not None else cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, f"hook errored (rc={proc.returncode}): {proc.stderr}"
    assert proc.stdout.strip(), f"hook produced no output for {command!r}: {proc.stderr}"
    output: dict[str, str] = json.loads(proc.stdout).get("hookSpecificOutput", {})
    return output


def _decision(
    command: str,
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    proc_cwd: Path | None = None,
) -> str | None:
    """The hook's ``permissionDecision`` for a Bash call running ``command``."""
    return _hook_output(command, cwd, env=env, proc_cwd=proc_cwd).get("permissionDecision")


def _denied(command: str, cwd: Path, **kwargs: object) -> bool:
    return _decision(command, cwd, **kwargs) == "deny"  # type: ignore[arg-type]


# --- AC-1: the allow path, produced by production code ------------------------


def test_a_push_to_a_protected_branch_with_a_marker_passes(repo: Path) -> None:
    """The gate ran green over this exact tree, so the push is authorised.

    There is no command-based exemption for ``/build`` or ``/routine`` and none is
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


def test_mirror_is_denied_even_where_the_repo_has_no_protected_branch(
    repo: Path,
) -> None:
    """``--mirror`` is the one flag whose danger *increases* when the local repo
    holds no protected branch.

    It does not merely push refs; it makes the remote match the local set, so a
    protected branch the local repo does not have is a protected branch
    ``--mirror`` **deletes**. Deciding it on whether a protected branch exists
    locally therefore has the polarity exactly backwards, and this test is the
    one that separates the two readings: the only branch here is ``feat/x``.

    ``--all`` is the opposite case and is allowed in the same repository — it
    pushes the local branches and nothing else, so with no protected branch
    among them there is genuinely no protected target. Asserting both on one
    fixture is what keeps the two flags from being conflated again.
    """
    _git(repo, "checkout", "-q", "-b", "feat/x")
    _git(repo, "branch", "-q", "-D", "main")

    assert _denied("git push --mirror origin", repo), (
        "a mirror push from a repo with no protected branch deletes every "
        "protected branch on the remote — the case the guard most has to refuse"
    )
    assert not _denied("git push --all origin", repo), (
        "--all moves only the local branches; with no protected branch among "
        "them there is no protected target, and denying it would be a false deny"
    )


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


# --- #477: the directory-tracking gap — pushd/popd and --git-dir --------------


def test_pushd_names_the_push_directory(repo: Path, tmp_path: Path) -> None:
    """``pushd`` moves the effective directory exactly as ``cd`` does.

    Until #477 only ``cd`` and ``git -C`` were tracked, so ``pushd <worktree> &&
    git push`` resolved HEAD at the session cwd — the same defect the cd test
    above pins, one builtin along. Both directions on one fixture: the ungated
    worktree is refused through a pushd, and a pushd back into the gated
    checkout still passes.
    """
    _write_marker(repo)
    worktree = tmp_path / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(worktree))
    _commit(worktree, "unverified.txt", "never gated\n")

    assert _denied(f"pushd {worktree} && git push origin HEAD:main", repo), (
        "the guard resolved HEAD at the hook's cwd instead of the directory the "
        "pushd names, so the root checkout's marker authorised a push of the "
        "worktree's ungated tree"
    )
    assert not _denied(f"pushd {repo} && git push origin HEAD:main", repo), (
        "a pushd into the verified checkout must still pass, or the guard is "
        "merely denying every command that contains a pushd"
    )


def test_popd_returns_the_push_to_the_directory_it_left(repo: Path, tmp_path: Path) -> None:
    """``popd`` restores the directory a matching ``pushd`` left.

    The control without the popd proves the deny is the popd being followed,
    not pushd sequences being refused wholesale.
    """
    _write_marker(repo)
    worktree = tmp_path / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(worktree))
    _commit(worktree, "unverified.txt", "never gated\n")

    assert _denied(
        f"cd {worktree} && pushd {repo} && popd && git push origin HEAD:main", repo
    ), (
        "after the popd the push runs back in the ungated worktree, but the "
        "guard read it as still inside the gated checkout"
    )
    assert not _denied(f"cd {worktree} && pushd {repo} && git push origin HEAD:main", repo), (
        "without the popd the push runs in the gated checkout and must pass"
    )


def test_an_unknowable_pushd_or_popd_is_denied(repo: Path) -> None:
    """The directory-stack shapes this guard does not model are refused.

    An expansion target, a bare ``pushd`` (swap), a rotation flag, and a
    ``popd`` with no matching ``pushd`` all leave the effective directory
    unknowable, which is the same answer an unreadable ``cd`` target gets.
    """
    _write_marker(repo)
    for command in (
        'pushd "$W" && git push origin HEAD:main',
        "pushd && git push origin HEAD:main",
        "pushd -n /tmp && git push origin HEAD:main",
        "popd && git push origin HEAD:main",
    ):
        assert _denied(command, repo), command


def test_a_git_dir_operand_is_refused_in_every_spelling(repo: Path, tmp_path: Path) -> None:
    """``--git-dir`` (and ``GIT_DIR=``) aims the push at a repository the
    directory tracking does not follow, so the guard refuses it by name.

    The hook's cwd is gated — its marker must not authorise a push against a
    different repository named by the operand. The refusal is unconditional and
    names the respelling (``git -C``), which the guard *does* resolve.
    """
    _write_marker(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _git(elsewhere, "init", "-q", "--initial-branch=main")
    _git(elsewhere, "config", "user.email", "t@example.com")
    _git(elsewhere, "config", "user.name", "t")
    _commit(elsewhere, "other.txt", "never gated\n")

    for command in (
        f"git --git-dir={elsewhere}/.git push origin HEAD:main",
        f"git --git-dir {elsewhere}/.git push origin HEAD:main",
        f"GIT_DIR={elsewhere}/.git git push origin HEAD:main",
    ):
        output = _hook_output(command, repo)
        assert output.get("permissionDecision") == "deny", command
        assert "git-dir" in output.get("permissionDecisionReason", "").lower(), (
            f"the refusal must name the operand it refused: {output!r}"
        )


def test_a_git_dir_push_is_refused_even_outside_a_repository(
    repo: Path, tmp_path: Path
) -> None:
    """The open half of the gap: outside a work tree the guard passes through,
    while ``--git-dir`` aims the push at a real repository anyway."""
    outside = tmp_path / "outside"
    outside.mkdir()

    assert _denied(f"git --git-dir={repo}/.git push origin HEAD:main", outside), (
        "a non-repo cwd read as 'not my concern' while the --git-dir operand "
        "carried the push into a real repository with no marker check at all"
    )


# --- the refspec the guard has to infer rather than read ----------------------


def _with_upstream(repo: Path, tmp_path: Path, branch: str) -> None:
    """Give ``repo``'s current branch a tracking branch called ``branch``.

    A bare ``git push`` names no refspec at all, so the target has to be inferred
    from ``@{upstream}``. That inference is the only part of the predicate with
    no literal text to read, which is why it needs a fixture of its own.
    """
    bare = tmp_path / "origin.git"
    _git(repo, "init", "-q", "--bare", str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    _git(repo, "branch", "--set-upstream-to", f"origin/{branch}")


def test_a_bare_push_to_a_protected_upstream_is_denied(repo: Path, tmp_path: Path) -> None:
    """``git push`` with no arguments is the commonest spelling there is, and it
    is the one shape where the target is not written down anywhere in the
    command.

    Both directions on the same command, so the deny is attributable to the
    evidence rather than to the guard refusing every argument-less push: with no
    marker the push to the protected upstream is refused, and the identical
    command over the identical tree is allowed once the gate has covered it.
    """
    _with_upstream(repo, tmp_path, "dev")

    assert _denied("git push", repo), (
        "a bare push resolves its target through @{upstream}; the upstream here "
        "is a protected branch and no marker covers the tree"
    )

    _write_marker(repo)

    assert not _denied("git push", repo)


def test_a_bare_push_to_an_unprotected_upstream_passes(repo: Path, tmp_path: Path) -> None:
    """The negative control on the inferred target. Without it a guard that
    denied every refspec-less push would satisfy the case above."""
    _with_upstream(repo, tmp_path, "feat/x")

    assert not _denied("git push", repo)


def test_a_variable_in_the_target_slot_is_denied(repo: Path) -> None:
    """A parameter expansion is as unreadable as a command substitution.

    ``git push origin HEAD:$T`` reads statically as a push to a branch named
    ``$T`` — a name no protected set contains — while at run time the shell hands
    git whatever ``T`` holds. The guard cannot establish the target, and a target
    it cannot establish is state 2 of the design's fail-open split, which closes.
    A marker is present, so the deny is about the ambiguity and not about
    missing evidence.
    """
    _write_marker(repo)

    assert _denied("T=main; git push origin HEAD:$T", repo)
    assert _denied("git push origin HEAD:${T}", repo)
    assert _denied("git push origin $T", repo)


def test_a_relative_dash_c_is_resolved_against_the_command_not_the_hook_process(
    repo: Path, tmp_path: Path
) -> None:
    """``git -C .`` means *the directory this command runs in*, not the directory
    the hook happens to have been launched in.

    The two are set to different repositories on purpose, and the hook process's
    one is the **verified** one: a guard that resolved a relative ``-C`` against
    its own cwd would find that repo's marker and authorise a push of a tree it
    has never seen. That is the same defect as ignoring the ``cd``, one operand
    further along.
    """
    _write_marker(repo)  # the hook process's own cwd IS verified
    ungated = tmp_path / "ungated"
    ungated.mkdir()
    _git(ungated, "init", "-q", "--initial-branch=main")
    _git(ungated, "config", "user.email", "t@example.com")
    _git(ungated, "config", "user.name", "t")
    _commit(ungated, "never-gated.txt", "no gate has seen this\n")

    assert _denied(f"cd {ungated} && git -C . push origin HEAD:main", repo, proc_cwd=repo), (
        "the guard resolved a relative -C against its own working directory, so "
        "a marker belonging to an entirely different repository authorised this "
        "push"
    )
    absolute = f"cd {ungated} && git -C {repo} push origin HEAD:main"
    assert not _denied(absolute, repo, proc_cwd=repo), (
        "an absolute -C into the verified checkout must still pass, or the guard "
        "is merely denying every command that carries a -C"
    )


# --- AC-6: state 2 closes -----------------------------------------------------


def test_an_unresolvable_source_is_denied(repo: Path) -> None:
    """The hook ran and could not establish the facts. A push guard that denies
    on ambiguity costs one command to clear and protects the irreversible act,
    which is why it fails closed where the Stop hook fails open."""
    _write_marker(repo)

    assert _denied("git push origin no-such-ref:main", repo)


def test_an_ambiguous_push_directory_is_denied(repo: Path) -> None:
    """A ``cd`` target carrying a shell expansion cannot be resolved statically,
    so the tree the push carries is unknowable.

    Three spellings, because the predicate is two conditions and ``$(…)`` alone
    cannot tell them apart: ``token.includes("$")`` already catches it, so a
    ``$(…)``-only suite certifies a predicate with no command-substitution arm at
    all. The backtick is the input that separates the arms. The tilde is the
    third expansion a shell performs on a bare word, and the one that reads least
    like an expansion — which is why it survived the first widening.
    """
    _write_marker(repo)

    assert _denied("cd $(mktemp -d) && git push origin HEAD:main", repo)
    assert _denied("cd `mktemp -d` && git push origin HEAD:main", repo), (
        "a backtick is the only input that distinguishes hasCommandSubstitution "
        "from the bare-$ arm beside it; without it that arm has no killer"
    )
    assert _denied("cd ~/nowhere && git push origin HEAD:main", repo), (
        "the shell expands a leading tilde, so the guard reading it as a literal "
        "path segment resolves a directory that does not exist and falls open"
    )


def test_a_variable_in_the_cd_target_is_denied(repo: Path) -> None:
    """#452 — a parameter expansion in a ``cd`` target is as unreadable as ``$(…)``.

    ``/build``'s ship step is literally ``cd "$worktree_path" && git push origin
    HEAD:dev``, the idiom the directory tracking exists for at all. After lexing,
    the quotes are gone and the target is the literal string ``$worktree_path``,
    which resolved against the payload's cwd to a path that does not exist; the
    guard then asked git about a non-directory, got no answer, and **allowed the
    push with no marker check at all**. State 2 of the design's fail-open split
    fell open on the one shape the tracking was written for.

    A marker is present, so the deny is attributable to the ambiguity rather than
    to missing evidence — the construction
    :func:`test_an_ambiguous_push_directory_is_denied` and
    :func:`test_a_variable_in_the_target_slot_is_denied` both use. The **reason**
    is asserted rather than the bare decision: a deny reached for any other cause
    would satisfy a decision-only check, and here the cause is the whole claim.

    Two assertions, because the refusal carries two obligations. The first is the
    cause; the second is the *remedy*, which is what makes this deny clearable
    rather than a wall — an agent that cannot see what to do instead re-runs the
    same command. Only the actionable half is pinned: the prose around it must
    stay free to be rewritten, and a mutation of that prose is expected to
    survive both assertions.
    """
    _write_marker(repo)

    output = _hook_output('cd "$worktree_path" && git push origin HEAD:main', repo)
    reason = output.get("permissionDecisionReason", "")

    assert output.get("permissionDecision") == "deny"
    assert "working directory cannot be resolved" in reason
    assert "Spell the directory literally" in reason, (
        "a refusal that does not name the way out is not clearable. The remedy is "
        "pinned rather than the surrounding prose, and it is the *literal* "
        "spelling rather than a git -C rewrite — that slot is refused too "
        "(:func:`test_an_expansion_in_the_git_dash_c_operand_is_denied`), so a "
        "message offering it as the escape would route the reader at a deny"
    )


def test_a_literal_cd_target_still_names_the_push_directory(repo: Path, tmp_path: Path) -> None:
    """The floor under the deny above: an *expansion* makes the directory
    unknowable, a ``cd`` on its own does not.

    The literal target is a second worktree at a **different tree**, gated by the
    production writer, while the checkout the payload names is gated by nothing.
    So this passes only if the guard both followed the ``cd`` and found that
    directory's own marker: a fix that collapsed every ``cd`` to ``dir: null``
    denies here, and one that ignored the ``cd`` reads the ungated checkout the
    second assertion proves is refused.
    """
    worktree = tmp_path / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(worktree))
    _commit(worktree, "gated.txt", "the gate covers this\n")
    _write_marker(worktree)

    assert not _denied(f"cd {worktree} && git push origin HEAD:main", repo)
    assert _denied("git push origin HEAD:main", repo), (
        "the checkout the payload names must itself be refused, or the assertion "
        "above would hold for a guard that simply never denies"
    )


def test_an_expansion_in_the_git_dash_c_operand_is_denied(repo: Path) -> None:
    """The **other** directory decision slot — and the one the refusal above
    names as the way out.

    ``cd`` and ``git -C`` answer the same question, so an expansion makes the
    directory equally unknowable in either. Only the ``cd`` half was closed, and
    that asymmetry is worse than a plain gap: the deny an expanded ``cd`` now
    earns tells its reader to spell the directory literally, and the mechanical
    rewrite an agent reaches for first — ``cd "$w" && git push`` becoming
    ``git -C "$w" push`` — moved the expansion into the slot with no predicate on
    it. Measured before the fix, with **no marker anywhere in the repository**:
    ``git push origin HEAD:main`` denied while all three spellings below were
    allowed with no marker check at all. So the refusal was one guided rewrite
    from being fully bypassable.

    The over-denial floor for this slot is
    :func:`test_a_relative_dash_c_is_resolved_against_the_command_not_the_hook_process`,
    whose second assertion requires a literal ``-C`` into a gated checkout to
    still pass.
    """
    _write_marker(repo)

    assert _denied('git -C "$worktree_path" push origin HEAD:main', repo)
    assert _denied("git -C $(mktemp -d) push origin HEAD:main", repo)
    assert _denied("git -C `mktemp -d` push origin HEAD:main", repo)


# --- #462: the directory slots are a whitelist, not a blacklist ---------------


def _is_literal_dir(tokens: list[str]) -> list[bool]:
    """Judge every token with the **production** ``isLiteralDir``, in one node run.

    The predicate is imported from the hook rather than re-implemented here: a
    control that re-applies the shipped character class in its own loop measures
    the class and agrees with itself about everything else
    (``craft.md``, *Exercise the production path, not merely a production
    constant*). One process for the whole corpus, because the corpus is the
    repo's entire directory set and a process per token would dominate the suite.
    """
    script = (
        "const {isLiteralDir} = require(process.argv[1]);"
        "const tokens = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(tokens.map((t) => isLiteralDir(t))));"
    )
    proc = subprocess.run(
        [_node(), "-e", script, str(HOOK)],
        input=json.dumps(tokens),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"the production predicate could not be driven: {proc.stderr}"
    verdicts: list[bool] = json.loads(proc.stdout)
    assert len(verdicts) == len(tokens)
    return verdicts


def test_a_glob_in_a_push_directory_is_denied(repo: Path) -> None:
    """#462 — the four expansion syntaxes a *blacklist* of expansions never had.

    ``isUnreadable`` refuses ``$``, ``$(…)``, a backtick and a leading ``~``, and
    a blacklist has no completion condition. Measured live against 0.3.0 with the
    fixture below, **all five** of the commands asserted here were allowed *with
    no marker check at all* — a glob ``*``, a glob ``?``, a character class
    ``[…]`` and a brace ``{…}`` in a ``cd`` target, and a glob in a ``git -C``
    operand. Each resolves statically to a path that does not exist, so
    ``git rev-parse --is-inside-work-tree`` failed there and ``verdict`` returned
    null.

    The fixture is the #452 shape one syntax further along, and it is what makes
    this a live evasion rather than a curiosity: the root checkout **is** gated,
    a worktree at ``.worktrees/work-462`` sits inside it at a *divergent,
    ungated* HEAD, and every glob here expands at run time onto that real
    unverified tree. So the shell would push bytes no gate has seen.

    Three controls hold the reading in place:

    * the **never-deny** control — the gated root still pushes, so a guard that
      simply refused everything would fail here;
    * the **literal** control — the same directory spelled out reaches the
      *evidence* rule (``No gate marker covers tree``), which proves the literal
      path is still judged readable and that the deny below is not "any command
      containing a cd";
    * the **reason** is asserted rather than the bare decision, because a deny
      reached for an unrelated cause satisfies a decision-only check and here the
      cause is the whole claim.
    """
    _write_marker(repo)  # the root checkout IS verified, before the worktree exists
    worktree = repo / ".worktrees" / "work-462"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(worktree))
    _commit(worktree, "unverified.txt", "never gated\n")

    assert not _denied("git push origin HEAD:main", repo), (
        "the gated root checkout must still push, or every assertion below holds "
        "for a guard that never allows anything"
    )
    literal = _hook_output("cd .worktrees/work-462 && git push origin HEAD:main", repo)
    assert literal.get("permissionDecision") == "deny"
    assert "No gate marker covers tree" in literal.get("permissionDecisionReason", ""), (
        "the literal spelling must be judged readable and refused on the "
        "*evidence*, or the whitelist has become a deny-everything rule and the "
        "glob denials below prove nothing about globs"
    )

    for command in (
        "cd .worktrees/work-* && git push origin HEAD:main",
        "cd .worktrees/work-4?2 && git push origin HEAD:main",
        "cd .worktrees/[w]ork-462 && git push origin HEAD:main",
        "cd .worktrees/{work-462} && git push origin HEAD:main",
        "git -C .worktrees/work-* push origin HEAD:main",
    ):
        output = _hook_output(command, repo)
        assert output.get("permissionDecision") == "deny", command
        assert "working directory cannot be resolved" in output.get(
            "permissionDecisionReason", ""
        ), f"denied for the wrong reason: {command}"


def test_every_directory_this_repo_actually_has_is_readable() -> None:
    """The over-denial floor, derived rather than guessed.

    Fail-closed becomes deny-everything unless something pins the legitimate
    side, and the honest corpus is the repo's own: every directory of the tracked
    tree, plus every path ``git worktree list`` reports — the two sets a real
    ``cd`` or ``git -C`` in this repo actually names.

    The membership anchors are named rather than counted: a count rots on the
    next directory added, while ``tests/unit`` and ``specs/features`` disappearing
    from the corpus is a rename that names itself (``craft.md``, *Floors decay
    into decoration*). The main checkout anchors the worktree half, which is
    otherwise a set that can silently empty.
    """
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    directories = set()
    for entry in tracked:
        parent = os.path.dirname(entry.strip())
        while parent:
            directories.add(parent)
            parent = os.path.dirname(parent)

    porcelain = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    worktrees = {line.split(" ", 1)[1] for line in porcelain if line.startswith("worktree ")}

    assert "tests/unit" in directories
    assert "specs/features" in directories
    assert os.path.realpath(REPO_ROOT) in {os.path.realpath(p) for p in worktrees}, (
        "the worktree half of the corpus must contain the checkout this suite "
        "runs in, or it could derive to the empty set and judge nothing"
    )

    corpus = sorted(directories | worktrees)
    refused = [d for d, ok in zip(corpus, _is_literal_dir(corpus), strict=True) if not ok]
    assert refused == [], f"the whitelist refuses directories this repo really has: {refused}"


def test_the_named_legitimate_directory_idioms_are_readable() -> None:
    """The named half of the over-denial floor: idioms the derived corpus cannot
    contain.

    ``.``, ``..`` and a relative sibling never appear in ``git ls-files``, and an
    absolute path outside this checkout never appears in ``git worktree list`` —
    yet all four are ordinary spellings of a push directory. The space-bearing
    and non-ASCII entries are the two admissions the character class makes
    deliberately: after lexing, a space inside a token was *quoted* (``cd "my
    dir"``), and every shell expansion trigger is ASCII by the POSIX grammar, so
    refusing non-ASCII would be a pure false-deny class for anyone whose paths
    are not English.

    **Every character the class admits is sampled here, and that is the point.**
    An allowlist has two failure directions and a green corpus can only ever see
    one: the derived floor above catches a class that has become too *narrow*,
    and nothing catches one that has quietly grown too *wide* — the repo's own
    directories would keep passing whatever else were admitted alongside them.
    So each of ``+ @ % , = :`` has a sample of its own, and dropping any single
    character from the class is what this test exists to make red. The
    corresponding widening direction is proven by mutation rather than by a test,
    because a test asserting a character is *refused* would have to name a
    character nobody has thought of yet.
    """
    idioms = [
        ".",
        "..",
        "../sibling",
        "/Users/someone/Code/harness",
        ".worktrees/work-462",
        "under_score/task",
        "my dir/task",
        "工作區/分支",
        "/opt/build+cache",
        "/srv/user@host",
        "/tmp/50%off",
        "/tmp/a,b",
        "/tmp/k=v",
        "C:/repos/harness",
    ]

    assert _is_literal_dir(idioms) == [True] * len(idioms), idioms


def test_a_cd_with_no_target_at_all_is_not_a_readable_directory(repo: Path) -> None:
    """A bare ``cd`` goes to ``$HOME``, which is not the directory that was named.

    The one shape that reaches :func:`isLiteralDir` with something that is not a
    string, and the reason that arm returns false rather than letting the regex
    coerce ``undefined`` into the six-letter word: a readable answer here would
    hand ``path.resolve`` an undefined operand, which throws — and a throw lands
    in this hook's *crash* arm, which fails **open**. So the degenerate command
    would be waved through by the one path that must never wave anything through.

    A marker is present, so the deny is the directory rule rather than missing
    evidence.
    """
    _write_marker(repo)

    output = _hook_output("cd && git push origin HEAD:main", repo)

    assert output.get("permissionDecision") == "deny"
    assert "working directory cannot be resolved" in output.get("permissionDecisionReason", "")


def test_a_gated_worktree_whose_path_contains_a_space_still_passes(
    repo: Path, tmp_path: Path
) -> None:
    """The live end of the over-denial floor — the whole path, not the predicate.

    A unit test can say the character class admits a space; only the hook can say
    the *lexer* hands that space through as one token and the directory is then
    resolved and gated. The worktree is at a different tree from the payload's
    checkout and is the only one with a marker, so this passes only if the guard
    followed the ``cd`` into it. The second assertion is the never-deny control
    on the same fixture.

    Like the other floors this is a **characterisation** test — it passed before
    the whitelist existed and its job is that it still passes after — so its
    evidence is the mutation that kills it (dropping the space from the safe
    class) rather than a RED.
    """
    worktree = tmp_path / "task dir"
    _git(repo, "worktree", "add", "-q", "-b", "task", str(worktree))
    _commit(worktree, "gated.txt", "the gate covers this\n")
    _write_marker(worktree)

    assert not _denied(f'cd "{worktree}" && git push origin HEAD:main', repo), (
        "a quoted, space-bearing directory survives lexing as one literal token; "
        "refusing it would deny the ordinary macOS home-directory shape"
    )
    assert _denied("git push origin HEAD:main", repo), (
        "the ungated checkout the payload names must itself be refused, or the "
        "assertion above would hold for a guard that simply never denies"
    )


def test_the_directory_whitelist_is_not_applied_to_refspecs(repo: Path) -> None:
    """AC-3 — a refspec is not a directory, and the two predicates must not merge.

    ``HEAD~1``, ``HEAD^`` and ``HEAD@{0}`` are ordinary, correct pushes whose
    characters — ``~``, ``^``, ``{``, ``}`` — are all *outside* the directory
    whitelist. Applying that whitelist to the refspec slot would refuse every one
    of them, which is why ``isUnreadable`` survives this change scoped to
    refspecs instead of being replaced everywhere. Each of the three dies the
    moment someone reaches for one predicate where the design has two.

    This is a **characterisation** test: it passed before the change and must go
    on passing, so its evidence is the mutation table rather than a RED. The
    fixture is two commits with a marker over each tree, so ``HEAD~1`` and
    ``HEAD^`` name a gated tree of their own rather than borrowing HEAD's, and
    ``no-such-ref`` is the never-allow control on the same fixture.
    """
    _write_marker(repo)  # covers commit 1's tree
    _commit(repo, "b.txt", "two\n")
    _write_marker(repo)  # covers commit 2's tree

    for refspec in ("HEAD~1:main", "HEAD^:main", "HEAD@{0}:main"):
        assert not _denied(f"git push origin {refspec}", repo), (
            f"{refspec} names a gated tree; refusing it means the directory "
            "whitelist has been applied to the refspec slot"
        )
    assert _denied("git push origin no-such-ref:main", repo), (
        "an unresolvable refspec must still be refused on the same fixture, or "
        "the three allows above hold for a guard that never denies"
    )


def test_the_refspec_slot_keeps_its_own_expansion_predicate(repo: Path) -> None:
    """The other half of #462: the blacklist did not go away, it moved.

    ``isUnreadable`` has three arms, and two of them were only ever killed
    through a *directory*: the backtick by ``cd `mktemp -d` `` and the leading
    tilde by ``cd ~/nowhere``. Both of those are now refused by ``isLiteralDir``
    before ``isUnreadable`` is consulted at all, so without this test deleting
    either arm leaves the suite green — the change would have removed the killers
    of the predicate it left behind.

    The **reason** is asserted rather than the decision, because the two arms
    fail differently once deleted and only one of the two failures hides from a
    decision check. Measured at review with the tilde arm removed, ``~1:main``
    still denies — the ``~1`` source resolves to no tree, so the refusal arrives
    from a different rule and a decision-only check would certify that arm's
    absence. Measured with the substitution arm removed, a backtick refspec is
    **allowed**: the target it reads statically is a branch name no protected
    set holds, so that deletion is a live evasion rather than a reworded
    refusal. Asserting the reason on both is what makes the pair uniform instead
    of depending on which arm someone deletes. A marker is present, so the deny
    is attributable to the refspec rather than to missing evidence.
    """
    _write_marker(repo)

    backtick = _hook_output("git push origin HEAD:`echo main`", repo)
    assert backtick.get("permissionDecision") == "deny"
    assert "refspec carries a shell expansion" in backtick.get("permissionDecisionReason", ""), (
        "a backtick refspec is the only input left that proves the command-"
        "substitution arm is live: the bare-$ arm beside it cannot see one"
    )

    tilde = _hook_output("git push origin ~1:main", repo)
    assert tilde.get("permissionDecision") == "deny"
    assert "refspec carries a shell expansion" in tilde.get("permissionDecisionReason", ""), (
        "a leading tilde is expanded by the shell, so the refspec git receives is "
        "not the one written; the arm that says so has no other killer left"
    )


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
