"""#436 — the gate-marker contract, pinned by execution across three languages.

The marker **path** is computed in three places (``scripts/gate_marker.py``,
``hooks/push-target-guard.js``, ``hooks/gate-evidence-guard.js``) and the
**tree** in two (``gate_marker.py`` and the Stop hook). Drift there is silent
and total: a hook that computes a slightly different path finds no marker, ever,
and denies or blocks every time — or, worse, computes a slightly different tree
and finds a marker that covers something else.

Three cheap duplicated implementations beat one shared ``hooks/lib/`` module
here, and the reason is structural rather than aesthetic:
``test_hooks_fail_open_is_loud.py``, ``test_hooks_module_type.py`` and
``test_hooks_no_empty_catch.py`` all scan ``hooks/*.js`` **non-recursively**, so
a ``lib/`` subdirectory would be a silent hole in three guards; and a shared
module's own load failure would disarm both enforcement hooks at once. An
equivalence test that *executes* all three catches the drift those guards would
miss, and adds no new failure mode of its own.

Acceptance criteria:

* **AC-1** — ``verify.sh`` actually invokes the writer, after the stage that can
  turn the tree red. This is the one link an executing test cannot cover (a full
  gate inside the gate is not viable), so it is a text guard over the shipped
  script. :func:`test_verify_writes_the_marker_on_its_success_path`.
* **AC-2** — the marker path agrees between the writer and both readers, in a
  real repository, including from a linked worktree.
  :func:`test_every_implementation_computes_the_same_marker_path`.
* **AC-3** — the tree oid agrees between the writer and the Stop hook, in a
  repository with a **dirty** working tree — the case where a naive
  ``HEAD^{tree}`` would silently pass an equivalence computed on a clean one.
  :func:`test_the_writer_and_the_stop_hook_compute_the_same_tree`.
* **AC-4** — the freshness bound agrees. Three parsers of one environment
  variable is exactly the shape that drifts.
  :func:`test_every_implementation_reads_the_same_freshness_bound`.
* **AC-5** — the mechanism is *published*: both hooks are registry ``files:``
  entries, so the installer copies them into a consuming repo, and the process
  doc says they exist. An enforcement hook that ships to nobody, or that a repo
  meets for the first time as an unexplained refusal, is a worse outcome than no
  hook at all. :func:`test_both_hooks_are_installed_by_the_registry` and
  :func:`test_the_process_doc_documents_the_enforcement_hooks`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "gate_marker.py"
VERIFY = REPO_ROOT / "scripts" / "verify.sh"
HOOKS_DIR = REPO_ROOT / "hooks"

#: The two hooks that re-implement the contract. Named rather than globbed: the
#: advisory hooks read no marker, so a glob would demand exports they have no
#: business carrying.
READERS = ("push-target-guard.js", "gate-evidence-guard.js")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gate_marker", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gm = _module()


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


@pytest.fixture
def dirty_repo(tmp_path: Path) -> Path:
    """A repository with a commit *and* uncommitted work.

    Dirty on purpose: a clean worktree makes ``current_tree()`` and
    ``HEAD^{tree}`` the same object, so an equivalence measured there would pass
    against a Stop hook that had degraded to reading ``HEAD^{tree}`` — which is
    precisely the mutation this module has to kill.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "first")
    (root / "b.txt").write_text("uncommitted\n")
    return root


def _hook_call(hook: str, expression: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    """Evaluate ``expression`` against ``hook``'s exports, in ``cwd``.

    ``require()``ing a hook does not run it — every hook guards its entry point
    with ``require.main === module`` — so this reads the real shipped
    implementation rather than a restatement of it.
    """
    script = (
        "const h = require(process.env.HOOK_PATH);"
        f"process.stdout.write(String({expression}));"
    )
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {}), "HOOK_PATH": str(HOOKS_DIR / hook)},
    )
    assert proc.returncode == 0, (
        f"{hook} could not evaluate {expression!r} (rc={proc.returncode}): {proc.stderr.strip()}"
    )
    return proc.stdout.strip()


# --- AC-1 ---------------------------------------------------------------------


def test_verify_writes_the_marker_on_its_success_path() -> None:
    """The one link no executing test can cover.

    Running ``verify.sh`` inside the suite would be a full gate inside the gate.
    Its marker-writing half is the part under test, and it is reached only if
    every stage above it passed — ``set -e`` is what makes "after pytest" mean
    "only when the tree is green".
    """
    source = VERIFY.read_text()
    invocation = "scripts/gate_marker.py write"

    assert invocation in source, (
        "scripts/verify.sh does not invoke the gate-marker writer, so a green "
        "gate leaves no evidence and both enforcement hooks refuse everything "
        "(or, if they fall open, enforce nothing). Add "
        f"`uv run --extra dev python {invocation}` to the success path."
    )
    assert source.index("pytest -n") < source.index(invocation), (
        "the marker is written before the pytest stage, so a red suite would "
        "still record the tree as verified. It must sit after every stage that "
        "can fail."
    )


# --- AC-2 ---------------------------------------------------------------------


@pytest.mark.parametrize("hook", READERS)
def test_every_implementation_computes_the_same_marker_path(hook: str, dirty_repo: Path) -> None:
    """A reader that computes a different path finds no marker, ever."""
    tree = "0" * 40
    expected = str(gm.marker_path(tree, dirty_repo))

    assert _hook_call(hook, f'h.markerPath("{tree}", process.cwd())', dirty_repo) == expected


@pytest.mark.parametrize("hook", READERS)
def test_the_marker_path_agrees_from_a_linked_worktree(
    hook: str, dirty_repo: Path, tmp_path: Path
) -> None:
    """The gate may run in a detached gate worktree while the claim is made in
    the build worktree. Both resolve the *common* directory, so both find the
    same marker — the property that makes that workflow safe rather than lucky.
    """
    linked = tmp_path / "linked"
    _git(dirty_repo, "worktree", "add", "-q", "--detach", str(linked))
    tree = "0" * 40

    assert _hook_call(hook, f'h.markerPath("{tree}", process.cwd())', linked) == str(
        gm.marker_path(tree, dirty_repo)
    )


# --- AC-3 ---------------------------------------------------------------------


def test_the_writer_and_the_stop_hook_compute_the_same_tree(dirty_repo: Path) -> None:
    """The equivalence that carries the most weight.

    The Stop hook's whole value over "did someone run a gate lately" is that it
    reads the tree *including uncommitted work*. If it drifted to ``HEAD^{tree}``
    it would still find markers, still allow, and silently stop distinguishing a
    verified tree from one edited afterwards.
    """
    from_python = gm.current_tree(dirty_repo)
    from_hook = _hook_call("gate-evidence-guard.js", "h.currentTree(process.cwd())", dirty_repo)

    assert from_hook == from_python
    assert from_hook != _git(dirty_repo, "rev-parse", "HEAD^{tree}"), (
        "the fixture is not dirty, so this equivalence would also hold for an "
        "implementation that merely read HEAD^{tree} — the fixture is wrong"
    )


def test_the_stop_hook_leaves_the_index_alone(dirty_repo: Path) -> None:
    """The hook computes a tree on every candidate stop. Doing that in the real
    index would stage the session's work behind its back."""
    before = _git(dirty_repo, "status", "--porcelain")

    _hook_call("gate-evidence-guard.js", "h.currentTree(process.cwd())", dirty_repo)

    assert _git(dirty_repo, "status", "--porcelain") == before


# --- AC-4 ---------------------------------------------------------------------


@pytest.mark.parametrize("hook", READERS)
@pytest.mark.parametrize("value", ["", "0", "-5", "soon", "60s", "60", "900"])
def test_every_implementation_reads_the_same_freshness_bound(
    hook: str, value: str, dirty_repo: Path
) -> None:
    """Three parsers of one environment variable is the shape that drifts.

    The degenerate values are the point: an unusable bound must read as *unset*
    in all three, because "never fresh" wedges every session and "always fresh"
    disarms the bound.
    """
    expected = gm.max_age_seconds({gm.MAX_AGE_ENV: value})
    from_hook = _hook_call(hook, "h.maxAgeSeconds()", dirty_repo, env={gm.MAX_AGE_ENV: value})

    assert int(from_hook) == expected


@pytest.mark.parametrize("hook", READERS)
def test_the_unset_freshness_bound_agrees(hook: str, dirty_repo: Path) -> None:
    """The default path, exercised with the variable genuinely absent rather
    than set to the empty string — a distinction ``process.env`` makes and the
    parametrized case above cannot express."""
    env = {k: v for k, v in os.environ.items() if k != gm.MAX_AGE_ENV}
    script = (
        "const h = require(process.env.HOOK_PATH);"
        "process.stdout.write(String(h.maxAgeSeconds()));"
    )
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=dirty_repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**env, "HOOK_PATH": str(HOOKS_DIR / hook)},
    )

    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip()) == gm.DEFAULT_MAX_AGE_SECONDS


# --- the marker the readers read is the one the writer wrote ------------------


@pytest.mark.parametrize("hook", READERS)
def test_a_reader_finds_the_marker_the_production_writer_produced(
    hook: str, dirty_repo: Path
) -> None:
    """The anti-vacuity spine of this whole change, stated once here.

    Every allow-path test in the two hook suites produces its marker by running
    ``scripts/gate_marker.py write`` — the production writer — never by
    hand-authoring a file. This test is the reason that works: the path the
    writer chose and the path the reader looks in are the same string, measured
    rather than assumed.
    """
    proc = subprocess.run(
        [os.environ.get("PYTHON", "python3"), str(SCRIPT), "write"],
        cwd=dirty_repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    tree = _hook_call("gate-evidence-guard.js", "h.currentTree(process.cwd())", dirty_repo)
    path = _hook_call(hook, f'h.markerPath("{tree}", process.cwd())', dirty_repo)

    assert Path(path).exists(), (
        f"{hook} looks for the marker at {path}, which the production writer did "
        f"not create. It wrote: {proc.stdout.strip()!r}"
    )
    assert json.loads(Path(path).read_text())["tree"] == tree


# --- AC-5: the mechanism is published -----------------------------------------


