"""#539 — `scripts/land.js`: the three landing cases, decided from git.

The four-step post-verdict procedure in `skills/build/SKILL.md` was a
low-freedom sequence of git invocations written as prose: read on every run,
costing context every time, and deviable anyway. This script is what retires it,
and these tests are the three cases plus the refusals.

Two properties are load-bearing and are asserted here rather than described:

* **It never pushes a branch.** The script runs as one Bash command, so a branch
  push it made internally would be invisible to `hooks/push-target-guard.js` — it
  would become the way around the guard it exists to satisfy. `plan` and `finish`
  print the push for the agent to run through the tool the hook can see. `done`
  does push, and only `refs/harness/*`: a gate record and the green pointer,
  neither of which moves a branch or authorises anything. So the invariant is
  *no verb pushes a branch*, and :func:`test_no_verb_pushes_a_branch` measures it
  over **every** verb with a git shim rather than trusting the source. The
  absolute this sentence used to state was the stronger claim and the weaker
  check: it left `done` — the one verb that reaches a remote — outside the guard
  that named it.
* **It never runs the gate.** Law 3 obliges the agent to run the gate and read
  its output; a script that swallowed the run would take the reading with it.

**AC-6 note.** The pointer half is measured here — it advances on an
uncontended landing and not on a conflicted one. *A new worktree reports its
base* is guidance in `skills/worktree-isolation/SKILL.md`, verified by use rather
than by a predicate over its wording (ADR 0017 D5, and law 2's subject is code);
what is mechanical about it is `harness-refs green-read`, measured in
``test_harness_refs.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._gate_marker_runner import install_internal_gate
from tests.unit._prose import REPO_ROOT

LAND = REPO_ROOT / "scripts" / "land.js"
WRITER = REPO_ROOT / "scripts" / "gate-marker.js"


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


def _land(
    repo: Path, *args: str, path_prefix: Path | None = None
) -> tuple[int, dict[str, object], str]:
    env = {**os.environ}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    proc = subprocess.run(
        [_node(), str(LAND), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    payload: dict[str, object] = {}
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
    return proc.returncode, payload, proc.stderr


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A candidate on ``work`` over a shared ``main``, with a real remote."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(bare))
    (root / "harness.yaml").write_text(
        "branches:\n  integration: main\n  release: prod\n"
        "commands:\n  verify: sh scripts/verify.sh\n  test_scoped: sh scripts/verify.sh\n",
        encoding="utf-8",
    )
    install_internal_gate(root)
    _git(root, "add", "harness.yaml", "scripts/verify.sh")
    _commit(root, "shared.txt", "base\n")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "-b", "work")
    _commit(root, "candidate.txt", "mine\n")
    return root


def _marker(repo: Path, *scope: str) -> str:
    """Evidence produced by the **production** writer, never hand-authored.

    A marker this module wrote itself would validate `land.js` against this
    module's idea of the contract. The path, the freshness stamp and the `scope`
    field are all halves of the thing under test, so they come from
    `scripts/gate-marker.js` — the same writer `verify.sh` invokes, and the same
    one `hooks/push-target-guard.js` reads.
    """
    args = ["run"]
    for entry in scope:
        args += ["--scope", entry]
    proc = subprocess.run(
        [_node(), str(WRITER), *args], cwd=repo, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"the production writer failed: {proc.stderr}"
    return _git(repo, "rev-parse", "HEAD^{tree}")


def _marker_path(repo: Path, tree: str) -> Path:
    """Where the **production** writer says this tree's marker lives."""
    return Path(
        subprocess.run(
            [_node(), str(WRITER), "path", "--tree", tree],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.strip()
    )


def _move_the_tip(repo: Path, name: str, body: str) -> None:
    """Land somebody else's commit on the shared branch, as a concurrent run would."""
    _git(repo, "checkout", "-q", "-B", "other", "origin/main")
    _commit(repo, name, body)
    _git(repo, "push", "-q", "origin", "other:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")


# --- AC-5: the three cases ----------------------------------------------------


def test_an_unchanged_tip_is_a_push(repo: Path) -> None:
    code, payload, _ = _land(repo, "plan")
    assert code == 0, payload
    assert payload["decision"] == "push" and payload["case"] == "unchanged", payload
    assert payload["push_command"] == "git push origin HEAD:main"
    assert payload["tree"] == _git(repo, "rev-parse", "HEAD^{tree}")


def test_a_moved_tip_that_merges_cleanly_is_a_push(repo: Path) -> None:
    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    code, payload, _ = _land(repo, "plan")
    assert code == 0, payload
    assert payload["decision"] == "push" and payload["case"] == "clean-merge", payload
    assert len(payload["parents"]) == 2, payload
    assert (repo / "theirs.txt").exists(), "the merge did not actually happen"
    assert _git(repo, "status", "--porcelain") == ""


def test_a_moved_tip_that_conflicts_asks_for_a_resolution_and_names_its_scope(
    repo: Path,
) -> None:
    """The conflicted paths are the scope, and the third file is the control.

    ``shared.txt`` conflicts; ``theirs.txt`` is changed cleanly by the other side
    only. A script that reported every path the merge touched would be
    indistinguishable from one that reported the conflicted ones without it.
    """
    _git(repo, "checkout", "-q", "-B", "other", "origin/main")
    (repo / "shared.txt").write_text("theirs\n", encoding="utf-8")
    (repo / "theirs.txt").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "their side")
    _git(repo, "push", "-q", "origin", "other:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")
    (repo / "shared.txt").write_text("ours\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "our side")

    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)

    code, payload, _ = _land(repo, "plan")
    assert code == 0, payload
    assert payload["decision"] == "resolve" and payload["case"] == "conflict", payload
    assert payload["conflicts"] == ["shared.txt"], payload["conflicts"]
    assert payload["scope_argv"][-2:] == ["--scope", "shared.txt"], payload["scope_argv"]
    assert "theirs.txt" not in payload["scope_command"], (
        "a cleanly merged path is not a resolution and does not belong in the scope"
    )
    assert "UU shared.txt" in _git(repo, "status", "--porcelain"), (
        "the worktree must be left conflicted for the agent to resolve"
    )


def test_the_scope_command_quotes_the_paths_git_chose(repo: Path) -> None:
    """The workflow hands this string to Bash, and the operands are filenames.

    Git will hand back whatever bytes a filename holds. A conflicted path
    carrying shell syntax, spliced unquoted into a command the agent then runs,
    is a command-injection hole one merge away.
    """
    nasty = "a b;touch pwned.txt"
    _git(repo, "checkout", "-q", "-B", "other", "origin/main")
    (repo / nasty).write_text("theirs\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "their side")
    _git(repo, "push", "-q", "origin", "other:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")
    (repo / nasty).write_text("ours\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "our side")

    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)

    payload = _land(repo, "plan")[1]
    assert payload["decision"] == "resolve", payload
    assert payload["conflicts"] == [nasty], payload["conflicts"]
    assert payload["scope_argv"][-1] == nasty, payload["scope_argv"]

    # Round-tripped through a real shell rather than pattern-matched: the claim
    # is about what Bash does with the string, not about which quotes are in it.
    # A `node` on PATH that only prints its argv, so the command runs as written.
    shim = repo / "shim"
    shim.mkdir()
    (shim / "node").write_text('#!/usr/bin/env sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    (shim / "node").chmod(0o755)
    echoed = subprocess.run(
        ["sh", "-c", str(payload["scope_command"])],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"},
    ).stdout.splitlines()
    assert echoed[-2:] == ["--scope", nasty], echoed
    assert not (repo / "pwned.txt").exists(), "a conflicted path reached the shell as syntax"


def test_finish_hands_over_the_push_once_nothing_has_moved_again(repo: Path) -> None:
    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    assert _land(repo, "plan")[0] == 0
    code, payload, _ = _land(repo, "finish")
    assert code == 0, payload
    assert payload["decision"] == "push" and payload["case"] == "regated", payload


def test_finish_sends_a_moved_tip_back_for_another_attempt(repo: Path) -> None:
    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    assert _land(repo, "plan")[0] == 0
    _move_the_tip(repo, "later.txt", "moved again\n")
    code, payload, _ = _land(repo, "finish", "--attempt", "1")
    assert code == 2, payload
    assert payload["decision"] == "resolve" and payload["case"] == "tip-moved", payload
    spent_code, spent, _ = _land(repo, "finish", "--attempt", "2")
    assert spent_code == 2 and spent["decision"] == "hold", spent


# --- AC-5: every other shape is refused --------------------------------------


def test_a_third_attempt_is_held_not_tried(repo: Path) -> None:
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    code, payload, _ = _land(repo, "plan", "--attempt", "3")
    assert code == 2, payload
    assert payload["decision"] == "hold" and payload["case"] == "attempts", payload
    assert _git(repo, "status", "--porcelain") == "", "a held run must not have merged"


def test_a_dirty_worktree_is_refused(repo: Path) -> None:
    (repo / "candidate.txt").write_text("uncommitted\n", encoding="utf-8")
    code, payload, _ = _land(repo, "plan")
    assert code == 2 and payload["decision"] == "refused", payload
    assert "not clean" in str(payload["reason"])


def test_a_detached_head_is_refused(repo: Path) -> None:
    _git(repo, "checkout", "-q", "--detach")
    code, payload, _ = _land(repo, "plan")
    assert code == 2 and payload["decision"] == "refused", payload
    assert "detached" in str(payload["reason"])


def test_a_branch_the_repo_declares_no_role_for_is_refused(repo: Path) -> None:
    code, payload, _ = _land(repo, "plan", "--branch", "somewhere-else")
    assert code == 2 and payload["decision"] == "refused", payload
    assert "somewhere-else" in str(payload["reason"])
    ok, _, _ = _land(repo, "plan", "--branch", "main")
    assert ok == 0, "a declared role must still be accepted, or the check is deny-everything"


def test_outside_a_repository_it_refuses(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()
    code, payload, _ = _land(outside, "plan")
    assert code == 2 and payload["decision"] == "refused", payload


def test_an_unknown_subcommand_is_a_usage_error(repo: Path) -> None:
    code, _, stderr = _land(repo, "ship-it")
    assert code == 64, stderr


# --- it never pushes a branch, and never gates --------------------------------


def test_no_verb_pushes_a_branch(repo: Path, tmp_path: Path) -> None:
    """Every verb, under a shim — and `done` is the one that had to be in it.

    A **branch** push this script made would run inside one Bash tool call and
    the PreToolUse guard would never see it, so the script would be the way
    around the guard it exists to satisfy. `done` does push: a gate record and
    the green pointer, both under `refs/harness/`, neither able to move a branch.
    So the invariant a guard can hold is *no verb pushes a branch*, not *no verb
    pushes* — and the first version of this test asserted the second while
    running only `plan` and `finish`, which is a coverage claim over the one verb
    it did not reach.

    The assertion is on every push's **destination**, so appending
    `git push origin HEAD:main` to any verb fails here.
    """
    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    shim = tmp_path / "shim"
    shim.mkdir()
    log = tmp_path / "git.log"
    real = shutil.which("git")
    assert real is not None
    (shim / "git").write_text(
        '#!/usr/bin/env sh\nprintf "%s\\n" "$*" >> "' + str(log) + '"\nexec ' + real + ' "$@"\n',
        encoding="utf-8",
    )
    (shim / "git").chmod(0o755)
    assert _land(repo, "plan", path_prefix=shim)[0] == 0
    assert _land(repo, "finish", path_prefix=shim)[0] == 0
    _git(repo, "push", "-q", "origin", "HEAD:main")
    assert _land(repo, "done", path_prefix=shim)[0] == 0

    seen = log.read_text(encoding="utf-8").splitlines()
    assert seen, "the shim recorded nothing, so it observed nothing"
    pushes = [entry.split() for entry in seen if entry.split()[0] == "push"]
    assert pushes, (
        "no verb pushed anything, so this measured nothing — `done` publishes a "
        "gate record and the green pointer and must reach the shim"
    )
    destinations: list[str] = []
    for push in pushes:
        for operand in push[2:]:
            if operand.startswith("-"):
                continue
            destinations.append(operand.split(":")[-1] if ":" in operand else operand)
    assert destinations, f"a push carried no refspec this test can read: {pushes}"
    stray = [ref for ref in destinations if not ref.startswith("refs/harness/")]
    assert stray == [], f"the landing script pushed outside refs/harness/: {stray}"


# --- AC-6: the green pointer --------------------------------------------------


def _green(repo: Path) -> str:
    proc = subprocess.run(
        [_node(), str(REPO_ROOT / "scripts" / "harness-refs.js"), "green-read"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_the_pointer_does_not_advance_before_the_push_has_landed(repo: Path) -> None:
    """`done` run out of order, or after a push that failed.

    The pointer names the last integration commit known green and
    `worktree-isolation` hands it to every new worktree as its base. A commit
    that is not on the shared branch is not a base anybody can start from, and
    nothing else would have caught it: the run that calls `done` is the same run
    whose push may have been refused.
    """
    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    assert _land(repo, "plan")[0] == 0
    code, payload, stderr = _land(repo, "done")
    assert code == 0, stderr
    assert payload["green_pointer_advanced"] is False, payload
    assert _green(repo) == "", payload
    _git(repo, "push", "-q", "origin", "HEAD:main")
    landed, after, _ = _land(repo, "done")
    assert landed == 0 and after["green_pointer_advanced"] is True, after


def test_the_pointer_advances_on_an_uncontended_landing(repo: Path) -> None:
    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    assert _land(repo, "plan")[0] == 0
    _git(repo, "push", "-q", "origin", "HEAD:main")
    code, payload, stderr = _land(repo, "done")
    assert code == 0, stderr
    assert payload["contended"] is False, payload
    assert payload["green_pointer_advanced"] is True, payload
    assert _green(repo) == _git(repo, "rev-parse", "HEAD")


def test_the_pointer_does_not_advance_on_a_conflicted_landing(repo: Path) -> None:
    """A resolution's only evidence is a scoped gate, and the pointer claims the
    whole tree — so it stays where it was, which is the control this needs."""
    _git(repo, "checkout", "-q", "-B", "other", "origin/main")
    (repo / "shared.txt").write_text("theirs\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "their side")
    _git(repo, "push", "-q", "origin", "other:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")
    (repo / "shared.txt").write_text("ours\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "our side")

    #: The candidate passed its gate before landing (law 3); `plan` now reads
    #: that marker to choose the parent it merges into (#566).
    _marker(repo)

    assert _land(repo, "plan")[1]["decision"] == "resolve"
    (repo / "shared.txt").write_text("resolved\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit")
    _git(repo, "push", "-q", "origin", "HEAD:main")

    code, payload, stderr = _land(repo, "done")
    assert code == 0, stderr
    assert payload["contended"] is True, payload
    assert payload["green_pointer_advanced"] is False, payload
    assert _green(repo) == "", payload


def test_a_landing_publishes_its_gate_record(repo: Path) -> None:
    code, payload, stderr = _land(repo, "done")
    assert code == 0, stderr
    assert payload["record_published"] is True, (payload, stderr)
    listed = subprocess.run(
        [_node(), str(REPO_ROOT / "scripts" / "harness-refs.js"), "gate-list"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert f"{_git(repo, 'rev-parse', 'HEAD^{tree}')} green" in listed, listed


# --- #566: `plan` must not build a merge onto an uncertified first parent -----
#
# `hooks/push-target-guard.js` accepts a reconciliation merge only when its
# **first parent's** tree carries a fresh, unscoped gate marker
# (`mergeAcceptance`). `plan` merged the tip into whatever `HEAD` was, with no
# notion of the certified commit, so a re-run after a lost push race stacked a
# second merge on the first and produced a first parent no gate ever covered —
# a new unpushable shape on every attempt. These measure the refusal that
# replaces it, and the recovery it names.


def _stack_a_lost_race(repo: Path) -> str:
    """Certify the candidate, then reproduce the losing first attempt.

    Returns the certified commit — the one `plan` should have merged into, and
    the one the refusal has to name.
    """
    _marker(repo)
    certified = _git(repo, "rev-parse", "HEAD")
    _move_the_tip(repo, "theirs.txt", "concurrent\n")
    code, payload, _ = _land(repo, "plan")
    assert code == 0 and payload["case"] == "clean-merge", payload
    # The push that would have followed is the one the race loses; the tip moves
    # again underneath it.
    _move_the_tip(repo, "later.txt", "and again\n")
    return certified


def test_plan_refuses_to_stack_a_merge_on_an_uncertified_head(repo: Path) -> None:
    """AC-1, AC-2, AC-3: the reported defect, and the recovery it now names."""
    certified = _stack_a_lost_race(repo)
    before = _git(repo, "rev-parse", "HEAD")

    code, payload, _ = _land(repo, "plan", "--attempt", "2")

    assert code == 2, payload
    assert payload["case"] == "uncertified-head", payload
    assert payload["certified"] == certified, payload
    assert certified in str(payload["recovery_command"]), payload
    # AC-1's second half: a refusal that had already committed the merge would
    # leave the branch in the shape it refused.
    assert _git(repo, "rev-parse", "HEAD") == before


def test_a_certified_head_still_merges_the_moved_tip(repo: Path) -> None:
    """AC-5's control. Without it the refusal above could be refusing everything."""
    _marker(repo)
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 0, payload
    assert payload["decision"] == "push" and payload["case"] == "clean-merge", payload


def test_a_chain_with_no_gated_commit_at_all_names_none(repo: Path) -> None:
    """AC-2's null arm: nothing to point at, so nothing is claimed."""
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 2, payload
    assert payload["case"] == "uncertified-head", payload
    assert payload["certified"] is None, payload
    assert "recovery_command" not in payload, payload


def test_a_scoped_marker_on_head_is_refused_without_offering_a_discard(
    repo: Path,
) -> None:
    """AC-3's second half — and the path `finish` itself sends a run down.

    `finish` on a moved tip prints ``run `land.js plan --attempt 2` ``, and after
    a conflict resolution `HEAD` is the resolved merge whose only evidence is a
    **scoped** gate. Merging onto it produces the same denied shape; rebuilding
    from the certified commit would throw the resolution away. So: refuse, and
    offer no recovery that discards.
    """
    _marker(repo, "candidate.txt")
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 2, payload
    assert payload["case"] == "uncertified-head", payload
    assert "recovery_command" not in payload, payload
    assert "scope" in str(payload["next"]).lower(), payload


def test_a_commit_authored_after_the_verdict_is_never_offered_a_discard(
    repo: Path,
) -> None:
    """AC-4. The certified commit is an ancestor, but reaching it drops work."""
    _marker(repo)
    certified = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "late.txt", "after the verdict\n")
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 2, payload
    assert payload["certified"] == certified, payload
    assert "recovery_command" not in payload, payload


def test_a_marker_past_its_freshness_bound_does_not_certify(repo: Path) -> None:
    """AC-6. The bound is the marker helper's; `land.js` must not widen it."""
    tree = _marker(repo)
    marker = _marker_path(repo, tree)
    assert marker.exists(), marker
    stale = marker.stat().st_mtime - 86400 - 60
    os.utime(marker, (stale, stale))
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 2, payload
    assert payload["case"] == "uncertified-head", payload


def _resolve_a_conflict_under_a_scoped_gate(repo: Path) -> str:
    """The real case 3, carried to the point `finish` sends a run back to `plan`.

    Certify the candidate, let the tip move and conflict, resolve it by hand,
    commit the merge and gate **only the resolved path** — which is exactly what
    `plan`'s own `scope_command` tells the agent to run. Returns the certified
    commit, which is now a genuine first-parent ancestor of HEAD.
    """
    _git(repo, "checkout", "-q", "-B", "other", "origin/main")
    (repo / "shared.txt").write_text("theirs\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "their side")
    _git(repo, "push", "-q", "origin", "other:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")
    (repo / "shared.txt").write_text("ours\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "our side")
    #: The gate runs over the finished candidate, which is what `plan` then reads.
    _marker(repo)
    certified = _git(repo, "rev-parse", "HEAD")
    assert _land(repo, "plan")[1]["decision"] == "resolve"
    (repo / "shared.txt").write_text("resolved by hand\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit")
    _marker(repo, "shared.txt")
    return certified


def test_a_hand_resolution_is_never_offered_a_discard_even_below_a_certified_commit(
    repo: Path,
) -> None:
    """AC-3's second half, with the ancestor that makes it a real measurement.

    Cycle 1 shipped a `droppable` test that inferred "a merge this script made"
    from parent count alone. A hand-resolved merge is two-parented too, and the
    only reason the shipped test passed was that its chain had no certified
    ancestor at all — so `certified is None` short-circuited the answer and the
    property was never exercised. Here the ancestor exists, which is the shape
    `finish` itself produces when it prints ``run `land.js plan --attempt 2` ``.
    Offering a rebuild here would throw the resolution away.
    """
    certified = _resolve_a_conflict_under_a_scoped_gate(repo)
    _move_the_tip(repo, "later.txt", "and again\n")

    code, payload, _ = _land(repo, "plan", "--attempt", "2")

    assert code == 2, payload
    assert payload["case"] == "uncertified-head", payload
    assert payload["certified"] == certified, (
        "the ancestor must be found, or this test degenerates into the vacuous one it replaces"
    )
    assert "recovery_command" not in payload, payload


def test_a_marker_body_the_guard_calls_unreadable_does_not_certify(repo: Path) -> None:
    """`certifies()` and `hooks/push-target-guard.js`'s `markerFor` must agree.

    A JSON array parses, and has no `scope` key. Reading "no scope" off it as
    "unscoped, therefore certified" is the disagreement: `markerFor` calls the
    same body unreadable and denies the push. Any body this script calls
    certified and the guard denies puts back the defect #566 removed.
    """
    tree = _marker(repo)
    _marker_path(repo, tree).write_text("[]", encoding="utf-8")
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 2, payload
    assert payload["case"] == "uncertified-head", payload


def test_a_merged_sibling_branch_is_never_offered_a_discard(repo: Path) -> None:
    """The other half of `recomputable`: where the dropped bytes would come from.

    A merge git alone made is safe to drop only because the rebuilt merge brings
    its content back — and that holds only for a second parent the tip already
    carries. Merge a sibling branch into the candidate instead and the content
    lives nowhere else, so rebuilding from the certified commit would lose the
    whole branch. Recomputability alone cannot see this: the merge is perfectly
    clean.
    """
    _marker(repo)
    certified = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side.txt", "a sibling branch\n")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "-q", "--no-ff", "--no-edit", "side")
    _move_the_tip(repo, "theirs.txt", "concurrent\n")

    code, payload, _ = _land(repo, "plan")

    assert code == 2, payload
    assert payload["certified"] == certified, payload
    assert "recovery_command" not in payload, payload
    assert (repo / "side.txt").exists()
