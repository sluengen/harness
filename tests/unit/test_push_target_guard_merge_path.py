"""#539 — the push guard's second acceptance path: a clean merge over a gated parent.

Under v5 a push to a protected branch needed a fresh marker over the **exact**
pushed tree, so every move of the integration branch sent a run back through
reconcile, delta review, the gate, the verdict and the push — each opening a new
window of the same width. The landing posture keeps the guarantee and drops the
exponential: the composite gate covers the candidate as it would land, and at
push time git alone is asked whether the merge added anything nobody has seen.

**What the path proves, and what it does not.** It proves *no agent authored
these bytes; git alone produced them*. It does **not** prove *these bytes were
gated*: a clean merge of two individually green changes can be wrong, and a
``merge=union`` or custom merge driver declared in ``.gitattributes`` is honoured
by both ``git merge`` and ``git merge-tree``, so it can produce a file whose
bytes are in neither parent with an empty authored set. Both need write access to
``.git/config`` or are the semantic-merge case D2 already accepted, and the next
builder's composite gate is the named backstop.

**The instrument is recomputation, not observation.** By push time the index, the
worktree and any resolution are gone, so D2's original four facts named three
things a PreToolUse hook cannot measure. ``git merge-tree --write-tree`` replays
the merge from the two parents and prints the tree git alone would produce;
the paths where the pushed tree differs from it are exactly the authored bytes.

Acceptance criteria, and the shape of each test:

* **AC-1** — the allow (:func:`test_a_clean_merge_over_a_gated_parent_is_allowed`)
  and five denials, each asserting **its own reason**: one byte authored, a
  parent that differs (two routes — a swapped first parent and a second parent
  that is not on the branch being pushed), a merge base that is not unique, a
  stale marker, and authored bytes outside a scoped marker.
* **AC-4** — containment is *subset*, measured in both directions: a scope
  strictly larger than the authored set allows, a scope missing one path denies,
  and a disjoint scope denies. Without the last two an implementation reading
  "the sets intersect" would pass.

**Two traps this module is built around.** A fail-open reads exactly like an
allow — the hook prints ``{"continue": true}`` and a ``fail-open:`` line on
stderr — so every allow here asserts stderr carries no such line; without that a
crash in the new arm turns the whole feature green. And a deny is the *default*,
so a deny test that asserted only the decision would pass against a tree with no
acceptance path at all: every one names the reason it expects.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit._gate_marker_runner import install_internal_gate
from tests.unit._prose import REPO_ROOT

HOOK = REPO_ROOT / "hooks" / "push-target-guard.js"
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


def _try_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _write(repo: Path, name: str, body: str) -> None:
    (repo / name).write_text(body, encoding="utf-8")


def _commit(repo: Path, name: str, body: str) -> str:
    _write(repo, name, body)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"{name}")
    return _git(repo, "rev-parse", "HEAD")


def _marker(repo: Path, *scope: str) -> str:
    """Evidence produced by the **production** writer, never hand-authored.

    A marker written by the test would validate the hook against the test's idea
    of the contract, which is the fixture-agreeing-with-itself the criteria rule
    out. The scoped form goes through the same runner and the same declaration.
    """
    args = ["run"]
    for entry in scope:
        args += ["--scope", entry]
    proc = subprocess.run(
        [_node(), str(WRITER), *args], cwd=repo, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"the production writer failed: {proc.stderr}"
    return proc.stdout.split(":", 1)[1].split("->")[0].strip()


def _hook(
    command: str, cwd: Path, *, path_prefix: Path | None = None
) -> tuple[str | None, str, str]:
    """``(decision, reason, stderr)`` for a Bash call running ``command``."""
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    env = {**os.environ}
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env['PATH']}"
    proc = subprocess.run(
        [_node(), str(HOOK)],
        input=json.dumps(payload),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    block = json.loads(proc.stdout).get("hookSpecificOutput", {})
    return block.get("permissionDecision"), block.get("permissionDecisionReason", ""), proc.stderr


PUSH = "git push origin HEAD:main"


def _allowed(cwd: Path, **kwargs: object) -> None:
    decision, reason, stderr = _hook(PUSH, cwd, **kwargs)  # type: ignore[arg-type]
    assert "fail-open:" not in stderr, (
        "the hook crashed and passed the push through, which reads exactly like "
        f"an allow: {stderr}"
    )
    assert decision != "deny", reason


def _denied_because(cwd: Path, fragment: str, **kwargs: object) -> None:
    decision, reason, _ = _hook(PUSH, cwd, **kwargs)  # type: ignore[arg-type]
    assert decision == "deny", f"expected a deny naming {fragment!r}"
    assert fragment in reason, f"denied for a different cause: {reason}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A candidate on ``work``, a moved ``main``, and a tracking ref for it.

    No ``harness.yaml``, so the conservative fallback set applies and ``main`` is
    protected — the shape a consuming repo has before it has told the guidance
    anything about itself. ``origin`` is a real bare remote, because the
    acceptance path asks whether the second parent is already on the branch being
    pushed and that question is only meaningful against a tracking ref.
    """
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(bare))
    _commit(root, "a.txt", "one\n")
    _git(root, "push", "-q", "origin", "main")

    _git(root, "checkout", "-q", "-b", "work")
    install_internal_gate(root)
    _git(root, "add", "scripts/verify.sh")
    _git(root, "commit", "-q", "-m", "fixture gate")
    _commit(root, "c.txt", "candidate\n")

    _git(root, "checkout", "-q", "main")
    _commit(root, "i.txt", "incoming\n")
    _git(root, "push", "-q", "origin", "main")
    _git(root, "checkout", "-q", "work")
    return root


def _gate_and_merge(repo: Path, *merge_args: str) -> None:
    """Certify the candidate, then merge the moved tip into it — the live shape."""
    _marker(repo)
    _git(repo, "merge", "--no-ff", "--no-edit", *merge_args, "origin/main")


# --- AC-1: the allow, and the five denials -----------------------------------


def test_a_clean_merge_over_a_gated_parent_is_allowed(repo: Path) -> None:
    """The control. Everything else in this module is this fixture, changed once."""
    _gate_and_merge(repo)
    _allowed(repo)


def test_one_authored_byte_denies_the_same_merge(repo: Path) -> None:
    """The accept fixture plus one byte, so the deny can come from nothing else."""
    _gate_and_merge(repo)
    _allowed(repo)
    (repo / "a.txt").write_text("one\nauthored\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "--amend", "--no-edit")
    _denied_because(repo, "authored")


def test_a_merge_whose_first_parent_is_not_the_certified_one_is_denied(repo: Path) -> None:
    """Route A of AC-1's *a parent differs*: git's own parent order carries the claim.

    Parent 1 is the branch you were on, which under the land loop is the commit
    that received PASS. Merging the other way round produces the same tree and a
    different claim, so it is refused rather than guessed at.
    """
    _marker(repo)
    candidate = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-B", "reversed", "origin/main")
    _git(repo, "merge", "--no-ff", "--no-edit", candidate)
    _denied_because(repo, "first parent")


def test_a_merge_whose_second_parent_is_not_on_the_branch_is_denied(repo: Path) -> None:
    """Route B — the payload attack, and it is why this check exists.

    Branch from the tip, commit anything, merge it into the gated candidate. Two
    parents, one merge base, `merge-tree` reproduces it exactly, the authored set
    is empty. Without this condition the guard allows it and the push
    fast-forwards, and the payload has never been through a gate.
    """
    _marker(repo)
    _git(repo, "checkout", "-q", "-b", "payload", "origin/main")
    _commit(repo, "payload.txt", "never gated\n")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "--no-ff", "--no-edit", "payload")
    _denied_because(repo, "second parent")


def test_a_merge_with_two_merge_bases_is_denied(repo: Path) -> None:
    """A criss-cross history: which base the recomputation used is not decidable.

    Two things the fixture has to get right, and both were wrong on the first
    run. The two heads must genuinely have two maximal common ancestors — hence
    the assertion below, which measures the fixture rather than trusting it. And
    the incoming side must carry a byte the candidate does not, or the merged
    tree equals the certified tree and **path one** allows the push before the
    merge path is ever consulted.
    """
    _git(repo, "checkout", "-q", "-b", "left", "main~1")
    left = _commit(repo, "l.txt", "left\n")
    _git(repo, "checkout", "-q", "-b", "right", "main~1")
    right = _commit(repo, "r.txt", "right\n")
    _git(repo, "checkout", "-q", "left")
    _git(repo, "merge", "--no-ff", "--no-edit", right)
    _git(repo, "checkout", "-q", "right")
    _git(repo, "merge", "--no-ff", "--no-edit", left)
    _commit(repo, "only-theirs.txt", "so the trees differ\n")
    _git(repo, "branch", "-f", "main", "right")
    _git(repo, "push", "-q", "-f", "origin", "main")
    _git(repo, "checkout", "-q", "left")
    assert len(_git(repo, "merge-base", "--all", "left", "origin/main").split()) == 2, (
        "the fixture is not criss-crossed, so it measures nothing"
    )
    install_internal_gate(repo)
    _git(repo, "add", "scripts/verify.sh")
    _git(repo, "commit", "-q", "-m", "fixture gate")
    _marker(repo)
    _git(repo, "merge", "--no-ff", "--no-edit", "origin/main")
    assert _git(repo, "rev-parse", "HEAD^{tree}") != _git(repo, "rev-parse", "HEAD^1^{tree}"), (
        "the merge changed nothing, so path one would answer before the merge path"
    )
    _denied_because(repo, "merge base")


def test_a_stale_marker_on_the_certified_parent_denies(repo: Path) -> None:
    """Backdated past the bound, with a control one second inside it.

    Backdating the file is the honest instrument: lowering
    ``HARNESS_GATE_MARKER_MAX_AGE_SECONDS`` would move the *reader's* bound too
    and the test would pass whatever the guard read.
    """
    _gate_and_merge(repo)
    _allowed(repo)
    certified = _git(repo, "rev-parse", "HEAD^1^{tree}")
    path = Path(
        subprocess.run(
            [_node(), str(WRITER), "path", "--tree", certified],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    inside = time.time() - 86000
    os.utime(path, (inside, inside))
    _allowed(repo)
    outside = time.time() - 90000
    os.utime(path, (outside, outside))
    _denied_because(repo, "first parent")


def test_a_scoped_marker_never_authorises_an_ordinary_push(repo: Path) -> None:
    """The whole reason path one demands an **unscoped** marker.

    A scoped marker naming the pushed tree exists and is fresh; the commit has
    one parent, so there is no merge for the scope to be about. Allowing it would
    make the scope field decorative — the marker's filename would authorise a
    push the run never covered.
    """
    _declare_scoped(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "declare the scoped gate")
    _marker(repo, "c.txt")
    _denied_because(repo, "two-parent")


# --- AC-4: the scoped conflict path, containment measured both ways ----------


def _declare_scoped(repo: Path) -> None:
    (repo / "scoped.sh").write_text(
        "#!/usr/bin/env sh\ntest \"${HARNESS_GATE_MARKER_RUNNER:-}\" = \"1\"\n", encoding="utf-8"
    )
    (repo / "harness.yaml").write_text(
        "commands:\n  verify: sh scripts/verify.sh\n  test_scoped: sh scoped.sh\n",
        encoding="utf-8",
    )


def _conflict_fixture(repo: Path, prefix: str = "") -> list[str]:
    """Two files conflicting, a third changed cleanly by one side only.

    The third file is what makes the authored set a real measurement: if every
    path in the fixture conflicted, "records the conflicted paths" and "records
    every path the merge touched" would be the same answer.

    ``prefix`` puts the three under a directory, for the one test that measures
    containment by path prefix rather than by exact name.
    """
    _declare_scoped(repo)
    if prefix:
        (repo / prefix.rstrip("/")).mkdir(parents=True, exist_ok=True)
    for name in (f"{prefix}x.txt", f"{prefix}y.txt", f"{prefix}z.txt"):
        _write(repo, name, "base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "shared base")
    _git(repo, "push", "-q", "-f", "origin", "work:main")
    _git(repo, "fetch", "-q", "origin")

    _git(repo, "checkout", "-q", "-B", "moved", "origin/main")
    _write(repo, f"{prefix}x.txt", "theirs\n")
    _write(repo, f"{prefix}y.txt", "theirs\n")
    _write(repo, f"{prefix}z.txt", "theirs only\n")
    _git(repo, "commit", "-qam", "their side")
    _git(repo, "push", "-q", "-f", "origin", "moved:main")
    _git(repo, "fetch", "-q", "origin")

    _git(repo, "checkout", "-q", "work")
    _write(repo, f"{prefix}x.txt", "ours\n")
    _write(repo, f"{prefix}y.txt", "ours\n")
    _git(repo, "commit", "-qam", "our side")
    _marker(repo)

    merged = _try_git(repo, "merge", "--no-ff", "--no-edit", "origin/main")
    assert merged.returncode != 0, "the fixture did not conflict"
    for name in (f"{prefix}x.txt", f"{prefix}y.txt"):
        _write(repo, name, "resolved\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-edit")
    return [f"{prefix}x.txt", f"{prefix}y.txt"]


def test_a_resolved_conflict_lands_under_a_marker_naming_the_resolved_paths(
    repo: Path,
) -> None:
    conflicted = _conflict_fixture(repo)
    _denied_because(repo, "authored")
    _marker(repo, *conflicted)
    _allowed(repo)


def test_a_scope_wider_than_the_authored_set_still_lands(repo: Path) -> None:
    """Containment is subset, not equality — a repo may re-gate more than it must."""
    conflicted = _conflict_fixture(repo)
    _marker(repo, *conflicted, "z.txt")
    _allowed(repo)


def test_a_scope_missing_one_authored_path_is_denied(repo: Path) -> None:
    conflicted = _conflict_fixture(repo)
    _marker(repo, conflicted[0])
    _denied_because(repo, "outside the scope")


def test_a_scope_naming_a_directory_covers_the_paths_beneath_it(repo: Path) -> None:
    """Containment is by path prefix, not only by exact name.

    A repo whose scoped command is directory-granular — ``pytest tests/unit`` —
    can only describe what it ran as a directory, and a guard that understood
    exact filenames alone would force that scope to be dishonest. Found because a
    mutation of the containment predicate survived every fixture: every scope in
    them was a list of exact files, so the prefix branch was never reached.
    """
    conflicted = _conflict_fixture(repo, prefix="nested/")
    assert conflicted == ["nested/x.txt", "nested/y.txt"]
    _marker(repo, "elsewhere")
    _denied_because(repo, "outside the scope")
    _marker(repo, "nested")
    _allowed(repo)


def test_a_scope_disjoint_from_the_authored_set_is_denied(repo: Path) -> None:
    """The other direction. Without it, containment written as *the sets
    intersect* passes every test above."""
    _conflict_fixture(repo)
    _marker(repo, "z.txt")
    _denied_because(repo, "outside the scope")


def test_a_merge_over_a_parent_covered_only_by_a_scoped_marker_is_denied(repo: Path) -> None:
    """The certified parent's marker must claim the **whole** tree, not a scope.

    This is the second attempt shape: a run that resolved a conflict and re-gated
    over the conflicted paths, then found the tip had moved again. Its own tree is
    covered by a scoped marker, which authorised the merge that produced it and
    nothing further — carrying it into a *second* merge would let a scope granted
    for two files stand as coverage of everything. The allow before the tip moves
    is the control: the deny below belongs to the second merge, not to the fixture.
    """
    conflicted = _conflict_fixture(repo)
    _marker(repo, *conflicted)
    _allowed(repo)

    _git(repo, "checkout", "-q", "-B", "later", "origin/main")
    _commit(repo, "later.txt", "moved again\n")
    _git(repo, "push", "-q", "-f", "origin", "later:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "--no-ff", "--no-edit", "origin/main")
    _denied_because(repo, "first parent")


# --- the marker body is now parsed, so its failures are decisions -------------


def test_an_unparseable_marker_body_authorises_nothing(repo: Path) -> None:
    _gate_and_merge(repo)
    _allowed(repo)
    certified = _git(repo, "rev-parse", "HEAD^1^{tree}")
    path = subprocess.run(
        [_node(), str(WRITER), "path", "--tree", certified],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    Path(path).write_text('{"tree": "trunc', encoding="utf-8")
    _denied_because(repo, "first parent")


def test_a_scope_that_is_not_a_list_of_paths_authorises_nothing(repo: Path) -> None:
    """Distinct from an unparseable body: this one is valid JSON and still unusable."""
    conflicted = _conflict_fixture(repo)
    tree = _marker(repo, *conflicted)
    path = subprocess.run(
        [_node(), str(WRITER), "path", "--tree", tree],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["scope"] = "x.txt"
    Path(path).write_text(json.dumps(payload), encoding="utf-8")
    _denied_because(repo, "outside the scope")


# --- shapes git alone did not produce ----------------------------------------


def test_a_three_parent_octopus_merge_is_denied(repo: Path) -> None:
    _marker(repo)
    # From the base rather than from the tip: git drops a head another head
    # already contains, so a `third` descended from `origin/main` would reduce to
    # an ordinary two-parent merge and this fixture would measure the wrong rule.
    _git(repo, "checkout", "-q", "-b", "third", "main~1")
    _commit(repo, "t.txt", "third\n")
    _git(repo, "checkout", "-q", "work")
    _git(repo, "merge", "--no-ff", "--no-edit", "origin/main", "third")
    assert len(_git(repo, "rev-parse", "HEAD^@").split()) == 3, "not an octopus"
    _denied_because(repo, "two-parent")


def test_a_merge_made_with_a_strategy_option_is_denied(repo: Path) -> None:
    """``merge-tree`` recomputes an ort merge. ``-X ours`` is not one, and the
    difference is authored bytes as far as this guard can tell — which is the
    honest answer, because nothing verified the side that was silently dropped."""
    _declare_scoped(repo)
    _write(repo, "x.txt", "base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "push", "-q", "-f", "origin", "work:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "-B", "moved", "origin/main")
    _write(repo, "x.txt", "theirs\n")
    # A second, non-conflicting file, so `-X ours` still produces a tree the
    # candidate's marker does not already cover — without it the merged tree is
    # byte-identical to the gated one and path one answers first, correctly.
    _write(repo, "extra.txt", "theirs only\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "theirs")
    _git(repo, "push", "-q", "-f", "origin", "moved:main")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "work")
    _write(repo, "x.txt", "ours\n")
    _git(repo, "commit", "-qam", "ours")
    _marker(repo)
    _git(repo, "merge", "--no-ff", "--no-edit", "-X", "ours", "origin/main")
    _denied_because(repo, "authored")


def test_without_merge_tree_the_path_is_absent_and_the_old_deny_stands(
    repo: Path, tmp_path: Path
) -> None:
    """git < 2.38 has no ``merge-tree --write-tree``: no new fallback, just no path.

    This also floors the deny table. Every denial above would pass on a host
    without the subcommand, so the allow control and this test are what say which
    of the two worlds the suite measured.
    """
    _gate_and_merge(repo)
    _allowed(repo)
    shim = tmp_path / "shim"
    shim.mkdir()
    real = shutil.which("git")
    assert real is not None
    (shim / "git").write_text(
        "#!/usr/bin/env sh\n"
        'for a in "$@"; do\n'
        '  if [ "$a" = "merge-tree" ]; then\n'
        "    echo \"git: 'merge-tree' is not a git command\" >&2; exit 1\n"
        "  fi\n"
        "done\n"
        f'exec {real} "$@"\n',
        encoding="utf-8",
    )
    (shim / "git").chmod(0o755)
    _denied_because(repo, "recomputed", path_prefix=shim)
