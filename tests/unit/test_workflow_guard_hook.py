"""The workflow guard's branch vocabulary, its non-source set, and its debounce.

CAL-1106 wrote this module for one defect: ``hooks/workflow-guard.js`` warns
(advisory, never blocks) when source is edited on a *default* branch, and its set
was ``main|master|dev|develop`` — overfit to the common names and blind to
``trunk``. The tests execute the hook as a node subprocess (the style of
``test_registry_self_version_hook``) against a real git repo on the branch under
test and read the warning it produces.

#457 added the rest of the guard's contract, all three parts measured the same
way — by running the hook, never by reading its regex:

* **AC-5 — the vocabulary is the push guard's fallback set.** The set was still
  narrower than ``push-target-guard.js``'s ``FALLBACK_PROTECTED``, missing
  ``staging``, ``release`` and ``production``; the push guard's own comment said
  its set "extends the vocabulary ``workflow-guard.js`` already hardcodes",
  acknowledging the gap rather than closing it. Editing source directly on
  ``staging`` violates ``worktree-isolation`` exactly as editing it on ``main``
  does, so narrower was not correct — it was stale. The corpus is **derived from
  the push guard's export**, so adding a branch name there is what makes this
  red (:func:`test_the_vocabulary_covers_the_push_guards_fallback_set`).
* **AC-6 — the debounce is per repository.** The marker was a fixed name in the
  machine-wide temp directory, so two sessions in two checkouts shared one, and
  the second session's warning was suppressed by the first's — silently, and
  most often under exactly the unattended concurrency this repo runs
  (:func:`test_two_checkouts_do_not_share_one_debounce`).
* **AC-6 — the non-source set still holds after two dead regexes went.**
  ``CONTEXT\\.md$`` and ``README\\.md$`` were subsumed by the trailing
  ``/\\.md$/``; :func:`test_markdown_paths_are_not_source` is what makes
  deleting them safe rather than merely plausible.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "hooks"
_HOOK = _HOOKS_DIR / "workflow-guard.js"
_PUSH_HOOK = _HOOKS_DIR / "push-target-guard.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo_on(tmp_path: Path, branch: str, *, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "-q", "-b", branch, str(repo)], check=True, capture_output=True
    )
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "--allow-empty", "-q", "-m", "init")
    return repo


def _fallback_protected() -> list[str]:
    """``push-target-guard.js``'s protected-branch fallback, read from the hook.

    Derived rather than restated: the two vocabularies are supposed to be the
    same set, so the test that says so must break when either side moves. A
    hand-copied tuple here would agree with itself through the next widening
    (``craft.md`` → *Exercise the production path, not merely a production
    constant*).
    """
    proc = subprocess.run(
        [
            _node(),
            "-e",
            "process.stdout.write(require(process.env.HOOK_PATH).FALLBACK_PROTECTED.join(','))",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "HOOK_PATH": str(_PUSH_HOOK)},
    )
    assert proc.returncode == 0, f"could not read FALLBACK_PROTECTED: {proc.stderr}"
    return [name for name in proc.stdout.strip().split(",") if name]


def _run_guard(repo: Path, edited: Path, *, tmpdir: Path | None = None) -> str:
    """Run the guard for a Write of ``edited`` in ``repo``; return additionalContext.

    ``TMPDIR`` defaults to a directory *inside* the repo so the guard's 4h
    debounce marker is isolated and cannot suppress the warning across runs. A
    caller that is measuring the debounce itself passes a shared ``tmpdir``,
    which is the machine-wide arrangement the real hook sees. The guard reads git
    state from the process CWD, so ``cwd`` is the repo under test.
    """
    if tmpdir is None:
        tmpdir = repo / "_tmp"
        tmpdir.mkdir(exist_ok=True)
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(edited)}}
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    proc = subprocess.run(
        [_node(), str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(repo),
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    return json.loads(proc.stdout).get("additionalContext", "")


def test_guard_recognises_trunk_as_default(tmp_path: Path) -> None:
    """Editing source on ``trunk`` warns *because it is a default branch* — the
    message names ``trunk``, not the fall-through "not in a task worktree"."""
    repo = _repo_on(tmp_path, "trunk")
    ctx = _run_guard(repo, repo / "app.py")
    assert "WORKFLOW-GUARD" in ctx, f"expected an advisory warning; got: {ctx!r}"
    assert "you are on 'trunk'" in ctx, (
        f"the guard must recognise 'trunk' as a default branch (onDefault), not "
        f"warn only via the worktree fallback; got: {ctx!r}"
    )


def test_guard_does_not_call_a_feature_branch_a_default(tmp_path: Path) -> None:
    """A non-default branch name must not be reported as a default branch — the
    'on <branch>' phrasing is reserved for the recognised default set."""
    repo = _repo_on(tmp_path, "feature-x")
    ctx = _run_guard(repo, repo / "app.py")
    # (A plain checkout is not a worktree, so the guard still warns — but via the
    # worktree fallback, never claiming 'feature-x' is a default branch.)
    assert "you are on 'feature-x'" not in ctx, (
        f"a feature branch must not be recognised as a default branch; got: {ctx!r}"
    )


# --- AC-5: one vocabulary, derived from the guard that owns it ----------------


def test_the_fallback_corpus_this_module_reads_is_live() -> None:
    """Floor: the derived corpus is populated and holds the names #457 added.

    A corpus deriving to ``[]`` collects no cases at all, and pytest reports an
    empty parametrization as a *skip* inside a green run (``craft.md`` → *The
    empty subject set*). Membership is pinned, never length.
    """
    fallback = _fallback_protected()

    assert {"main", "trunk", "staging", "release", "production"} <= set(fallback), (
        f"push-target-guard's FALLBACK_PROTECTED lost names this module is "
        f"written against; got {fallback}"
    )


@pytest.mark.parametrize("branch", _fallback_protected())
def test_the_vocabulary_covers_the_push_guards_fallback_set(
    branch: str, tmp_path: Path
) -> None:
    """Every branch the push guard protects is one this guard calls shared.

    The two hooks answer the same question about a branch name — *is this a
    branch other people build on* — and answering it differently is how
    ``staging`` came to be a branch you may edit source on directly and may not
    push to. The corpus is the push guard's own export, so the day a name is
    added there this case appears here.

    The assertion is on the *default-branch* arm specifically. A plain checkout
    is not a worktree either, so the guard warns for both reasons; only the
    "you are on '<branch>'" phrasing distinguishes a recognised shared branch
    from the worktree fall-through, which is what
    :func:`test_guard_does_not_call_a_feature_branch_a_default` pins from the
    other side.
    """
    repo = _repo_on(tmp_path, branch)

    ctx = _run_guard(repo, repo / "app.py")

    assert f"you are on '{branch}'" in ctx, (
        f"{branch!r} is protected by push-target-guard but workflow-guard does "
        f"not recognise it as a shared branch; got: {ctx!r}. Editing source "
        "directly on it breaks worktree-isolation exactly as it does on main."
    )


# --- AC-6: the non-source set, after two subsumed regexes went ----------------


@pytest.mark.parametrize("name", ["CONTEXT.md", "README.md", "notes.md"])
def test_markdown_paths_are_not_source(name: str, tmp_path: Path) -> None:
    """Editing markdown on a shared branch draws no warning.

    ``CONTEXT.md`` and ``README.md`` carried their own patterns in the
    non-source set, both subsumed by the trailing ``/\\.md$/``. Deleting a
    redundant pattern is only safe if something measures the behaviour it was
    redundant *with* — otherwise the deletion and the surviving pattern are two
    claims and nothing checks the second (``craft.md`` → *A survivor is
    ambiguous*). ``notes.md`` is the third case, which no named pattern ever
    covered, so this is one predicate rather than three coincidences.
    """
    repo = _repo_on(tmp_path, "main")

    assert _run_guard(repo, repo / name) == "", (
        f"editing {name} on a shared branch must not warn — markdown is not "
        "source, and the guard exists to catch off-pipeline code changes"
    )


# --- AC-6: the debounce is scoped to the repository ---------------------------


def test_two_checkouts_do_not_share_one_debounce(tmp_path: Path) -> None:
    """Two sessions, two repositories, one machine temp directory.

    The debounce marker was a fixed name in ``os.tmpdir()``, so the first
    session's warning silenced the second's for four hours — in a different
    repository, about a different edit, with nothing on stderr. This repo runs
    unattended sessions concurrently, which is precisely the condition that
    makes it happen and precisely the condition under which nobody is watching.

    ``tmpdir`` is deliberately shared between the two runs: isolating it (what
    every other case here does) is what would hide the defect.
    """
    shared = tmp_path / "machine-tmp"
    shared.mkdir()
    first = _repo_on(tmp_path, "main", name="checkout-a")
    second = _repo_on(tmp_path, "main", name="checkout-b")

    warned_first = _run_guard(first, first / "app.py", tmpdir=shared)
    warned_second = _run_guard(second, second / "app.py", tmpdir=shared)

    assert "WORKFLOW-GUARD" in warned_first, (
        f"the first session drew no warning, so the second proves nothing; got {warned_first!r}"
    )
    assert "WORKFLOW-GUARD" in warned_second, (
        "a session in a second checkout was silenced by the first session's "
        f"debounce marker; got {warned_second!r}. Advisory state must be scoped "
        "to the repository it was recorded in."
    )


def test_the_debounce_still_holds_within_one_checkout(tmp_path: Path) -> None:
    """The control for the case above: scoping must not disable the debounce.

    Without this, deleting the marker logic outright would pass
    :func:`test_two_checkouts_do_not_share_one_debounce` perfectly — every
    session warns, always, which is the noise the debounce exists to prevent.
    """
    shared = tmp_path / "machine-tmp"
    shared.mkdir()
    repo = _repo_on(tmp_path, "main")

    first = _run_guard(repo, repo / "app.py", tmpdir=shared)
    second = _run_guard(repo, repo / "other.py", tmpdir=shared)

    assert "WORKFLOW-GUARD" in first, f"the first edit drew no warning; got {first!r}"
    assert second == "", (
        f"the guard warned twice for the same checkout; got {second!r}. It is "
        "debounced once per session by design — a nudge that repeats on every "
        "edit is one that gets uninstalled."
    )
