"""#457 AC-3 / AC-6 — the version-drift detector is shown to detect.

``hooks/guidance-freshness.js`` warns when a version-stamped guidance file is
edited without its version bumped: the header stamp and the ``registry.yaml``
entry are two halves of one number, and an un-bumped edit is invisible to every
repo that installed the file. Until #457 that logic had never been run. The
cross-cutting structural guards it did have — CommonJS parse, fail-open-is-loud,
no-empty-catch — all pass on a detector whose comparison never fires, and a
silent detector is indistinguishable from a tree with no drift in it.

The fixtures are miniature source repos rather than this one, for two reasons.
The hook keys on ``registry.yaml`` being present in ``process.cwd()``, so a
fixture is the only way to control both halves of the comparison; and a test that
read the real registry would go red on any unrelated version bump, which is a
guard that teaches people to weaken it.

Each case carries its negative control, and the controls are chosen so the hook
is proven to have *run and decided* rather than merely to have said nothing:
:func:`test_a_current_file_draws_no_drift_warning` asserts the drift message is
absent **and** the ordinary bump reminder is present, which only holds if the
comparison happened and came out equal.

AC-6 is :func:`test_two_source_repos_do_not_share_one_debounce`. The debounce
markers were fixed names in the machine-wide temp directory, so a drift warning
in one checkout suppressed the warning in another for four hours — most often
under the unattended concurrency this guidance encourages, where nobody is
reading stderr.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "guidance-freshness.js"

#: The registry entry version every fixture declares. The *file* header is what
#: varies between the drift case and its control, so the two differ in exactly
#: one place.
_REGISTRY_VERSION = "0.2.0"

_WATCHED = "skills/sample/SKILL.md"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _source_repo(root: Path, *, header_version: str) -> Path:
    """A miniature guidance *source* repo: a registry, and one stamped file.

    Source mode is selected by ``registry.yaml`` being present, which is the
    hook's own discriminator rather than a flag this fixture invents.
    """
    root.mkdir(parents=True)
    (root / "registry.yaml").write_text(
        "\n".join(
            [
                "# guidance:registry@0.1.0",
                "files:",
                f"  {_WATCHED}:  "
                f"{{ id: sample, version: {_REGISTRY_VERSION}, profiles: [harness] }}",
                "meta:",
                "  registry.yaml:  { id: registry, version: 0.1.0 }",
                "",
            ]
        )
    )
    watched = root / _WATCHED
    watched.parent.mkdir(parents=True)
    watched.write_text(
        f"<!-- guidance:sample@{header_version} -->\n"
        "# Sample skill\n\nA sample rule, named after nothing in particular.\n"
    )
    return root


def _run(repo: Path, edited: Path, *, tmpdir: Path) -> str:
    """Run the hook for a Write of ``edited`` in ``repo``; return its advisory."""
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(edited)}}
    proc = subprocess.run(
        [_node(), str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(repo),
        env={**os.environ, "TMPDIR": str(tmpdir)},
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    return str(json.loads(proc.stdout).get("additionalContext", ""))


@pytest.fixture
def state(tmp_path: Path) -> Path:
    """An isolated temp directory, so a debounce marker cannot cross tests."""
    where = tmp_path / "machine-tmp"
    where.mkdir()
    return where


# --- AC-3: the drift comparison fires -----------------------------------------


def test_a_file_behind_its_registry_entry_is_flagged(tmp_path: Path, state: Path) -> None:
    """The header says one version, the registry says another, and both appear.

    The message has to name *both* numbers: "something is out of date" sends the
    reader back to work out which half moved, and the whole value of the hook is
    that it already knows.
    """
    repo = _source_repo(tmp_path / "repo", header_version="0.1.0")

    advisory = _run(repo, repo / _WATCHED, tmpdir=state)

    assert "[GUIDANCE-FRESHNESS]" in advisory, (
        f"a file behind its registry entry drew no warning; got {advisory!r}"
    )
    assert "@0.1.0" in advisory and f"@{_REGISTRY_VERSION}" in advisory, (
        f"the drift warning must name both versions it compared; got {advisory!r}"
    )
    assert _WATCHED in advisory, (
        f"the drift warning must name the file it is about; got {advisory!r}"
    )


def test_a_current_file_draws_no_drift_warning(tmp_path: Path, state: Path) -> None:
    """The negative control, and a positive one about the same run.

    Asserting only "no drift warning" would be satisfied by a hook that never
    reached the comparison at all — a mis-parsed registry, a path it decided not
    to watch, an early return. The ordinary bump reminder sits *after* the drift
    branch, so requiring it too pins that the hook ran, watched this file, and
    found the two versions equal.
    """
    repo = _source_repo(tmp_path / "repo", header_version=_REGISTRY_VERSION)

    advisory = _run(repo, repo / _WATCHED, tmpdir=state)

    assert "header says" not in advisory, (
        f"a file whose header matches its registry entry was reported as drifted; "
        f"got {advisory!r}"
    )
    assert "version-stamped file" in advisory, (
        "the hook did not reach its ordinary reminder, so the absence of a drift "
        f"warning above is not evidence the comparison happened; got {advisory!r}"
    )


def test_a_file_outside_the_guidance_surface_is_ignored(
    tmp_path: Path, state: Path
) -> None:
    """The second negative control: not every edit is this hook's business.

    A hook that advised on every write would satisfy the positive case above and
    be indistinguishable from noise. ``src/app.py`` is under no surface
    directory and is in no registry, so the hook must say nothing at all.
    """
    repo = _source_repo(tmp_path / "repo", header_version="0.1.0")
    other = repo / "src" / "app.py"
    other.parent.mkdir(parents=True)
    other.write_text("print('hello')\n")

    assert _run(repo, other, tmpdir=state) == "", (
        "the hook advised about a file that is neither installed guidance nor "
        "version-stamped"
    )


def test_a_tool_the_hook_does_not_own_is_ignored(tmp_path: Path, state: Path) -> None:
    """A ``Bash`` payload naming a drifted file is still not an edit of it."""
    repo = _source_repo(tmp_path / "repo", header_version="0.1.0")
    payload = {"tool_name": "Bash", "tool_input": {"file_path": str(repo / _WATCHED)}}
    proc = subprocess.run(
        [_node(), str(_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(repo),
        env={**os.environ, "TMPDIR": str(state)},
        timeout=30,
    )

    assert proc.returncode == 0, f"hook errored: {proc.stderr}"
    assert json.loads(proc.stdout).get("additionalContext", "") == ""


# --- AC-6: the debounce is scoped to the repository ---------------------------


def test_two_source_repos_do_not_share_one_debounce(tmp_path: Path) -> None:
    """Two checkouts, one machine temp directory, the same drift in each.

    The marker was a fixed name in ``os.tmpdir()``, so the first warning
    silenced the second for four hours — in a different repository, about a
    different file, with nothing on stderr to say a warning had been suppressed.
    """
    shared = tmp_path / "machine-tmp"
    shared.mkdir()
    first = _source_repo(tmp_path / "checkout-a", header_version="0.1.0")
    second = _source_repo(tmp_path / "checkout-b", header_version="0.1.0")

    warned_first = _run(first, first / _WATCHED, tmpdir=shared)
    warned_second = _run(second, second / _WATCHED, tmpdir=shared)

    assert "header says" in warned_first, (
        f"the first checkout drew no drift warning, so the second proves "
        f"nothing; got {warned_first!r}"
    )
    assert "header says" in warned_second, (
        "a second checkout's drift warning was suppressed by the first "
        f"checkout's debounce marker; got {warned_second!r}"
    )


def test_the_debounce_still_holds_within_one_repo(tmp_path: Path) -> None:
    """The control: scoping the marker must not remove the debounce.

    Deleting the marker logic outright passes the scoping test perfectly and
    turns a once-per-session reminder into one appended to every write.
    """
    shared = tmp_path / "machine-tmp"
    shared.mkdir()
    repo = _source_repo(tmp_path / "repo", header_version="0.1.0")

    first = _run(repo, repo / _WATCHED, tmpdir=shared)
    second = _run(repo, repo / _WATCHED, tmpdir=shared)

    assert "header says" in first, f"the first edit drew no drift warning; got {first!r}"
    assert "header says" not in second, (
        f"the same drift was reported twice in one session; got {second!r}"
    )
