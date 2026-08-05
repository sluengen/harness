"""#350 — a release-cadence bound must not sit inside the per-change gate.

Five consecutive unattended build ticks shipped nothing because
``test_unreleased_fragments_are_bounded`` failed on ``origin/dev`` *independent
of any change*: ``changelog.d/`` held 41 fragments against a bound of 40, so
``bash scripts/verify.sh`` was red on the integration branch, ``review`` refused
every non-zero ``--gate-exit`` before invoking an engine, and no ticket could
close — including the ones that would have removed the guard.

The defect is a **category error**, not a wrong number. Distinguish the two
kinds of assertion by what a *single change* can do about them:

* a **correctness** bound fails because of the diff, and the diff can fix it —
  it belongs in the gate every change must pass;
* a **cadence** bound fails because of accumulated repo state, which no single
  change caused and none can fix — it belongs on the release path.

These tests are the executable form of the acceptance criteria:

* **AC-4 — the property**, over a *synthetic over-bound tree*: the same tree
  makes ``verify.sh``'s cadence stage exit 0 and the release check exit 1. Both
  halves run the **real** ``scripts/cadence.py`` as a subprocess over a tree
  built from the registry's own bound — the AC forbids re-implementing the
  count, and a test that retyped ``40`` would keep passing after the bound moved.
* **AC-2 — the breach is still enforced**, so ``check`` fails closed on an
  unmeasurable subject. That arm is the easiest one here to leave untested and
  the one whose absence silently turns the release gate into a rubber stamp.
* **The binding test** (:func:`test_verify_runs_report_never_check`) is what
  makes the AC-4 pair mean anything: without it, both halves would prove a
  property of a command nobody runs.
* **The migration guard** pins that the three moved constants do not reappear in
  ``tests/unit/test_changelog_rotation.py`` by copy-paste — the realistic
  regression, and the one that would rebuild the wedge in place.

Deliberately **not** asserted: "this repo is over the fragment bound". That is
live-tree evidence, not a property — it inverts into a false failure the moment
a release folds.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import cadence  # noqa: E402

_SCRIPT = _REPO_ROOT / "scripts" / "cadence.py"
_VERIFY = _REPO_ROOT / "scripts" / "verify.sh"


def _run(mode: str, repo_root: Path) -> subprocess.CompletedProcess[str]:
    """Run the real script the way the gate and the release path run it."""
    return subprocess.run(
        [sys.executable, str(_SCRIPT), mode, "--repo-root", str(repo_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _bound(name: str) -> cadence.CadenceBound:
    """Look a bound up by name — never retype its value."""
    for entry in cadence.BOUNDS:
        if entry.name == name:
            return entry
    raise AssertionError(f"no cadence bound named {name!r} in BOUNDS")


def _synthetic_tree(tmp_path: Path, *, fragments: int) -> Path:
    """An otherwise-correct repo tree carrying ``fragments`` pending entries.

    ``CHANGELOG.md`` is copied from the real repo so the byte/line bounds stay
    green and any breach is unambiguously the fragment count. The fragments are
    well-formed, so the tree also passes ``changelog_fragments.check`` — the AC's
    "otherwise correct" clause.
    """
    root = tmp_path / "tree"
    (root / cadence.FRAGMENT_DIRNAME).mkdir(parents=True)
    shutil.copy(_REPO_ROOT / "CHANGELOG.md", root / "CHANGELOG.md")
    (root / cadence.FRAGMENT_DIRNAME / "README.md").write_text(
        "not a fragment\n", encoding="utf-8"
    )
    for index in range(fragments):
        ticket = 9000 + index
        (root / cadence.FRAGMENT_DIRNAME / f"{ticket}.md").write_text(
            f"### Added — synthetic entry (#{ticket})\n\nA well-formed body.\n",
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# AC-4 — the property, on one synthetic over-bound tree.
# ---------------------------------------------------------------------------


def test_over_bound_tree_fails_the_release_check(tmp_path: Path) -> None:
    """The release path refuses a tree over the cadence bound."""
    entry = _bound("changelog-fragments")
    over = entry.bound + 1
    tree = _synthetic_tree(tmp_path, fragments=over)

    result = _run("check", tree)

    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert cadence.FRAGMENT_DIRNAME in combined
    assert str(over) in combined
    assert str(entry.bound) in combined
    assert "release" in combined.lower()


def test_over_bound_tree_passes_the_gates_cadence_stage(tmp_path: Path) -> None:
    """The *same* tree leaves the per-change gate green, and says why.

    This is the half the wedge was about: a change that neither caused the
    breach nor can fix it must still reach review.
    """
    entry = _bound("changelog-fragments")
    over = entry.bound + 1
    tree = _synthetic_tree(tmp_path, fragments=over)

    result = _run("report", tree)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OVER" in result.stdout
    assert str(over) in result.stdout


def test_verify_runs_report_never_check() -> None:
    """The gate runs ``report``; only the release path runs ``check``.

    Binds the two tests above to the command the gate actually runs. Without
    this, they prove a property of a script nobody invokes.
    """
    lines = [
        line.strip()
        for line in _VERIFY.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    invokes_report = [ln for ln in lines if "cadence.py report" in ln]
    invokes_check = [ln for ln in lines if "cadence.py check" in ln]

    assert invokes_report, (
        "scripts/verify.sh must run `scripts/cadence.py report` so a cadence "
        "breach is visible in every gate run's output tail (#350 AC-2)."
    )
    assert not invokes_check, (
        "scripts/verify.sh must never run `cadence.py check` — that would put "
        f"the cadence bound back inside the correctness gate (#350): {invokes_check}"
    )


# ---------------------------------------------------------------------------
# Per-bound coverage, table-driven from the registry.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", cadence.BOUNDS, ids=lambda e: e.name)
def test_every_bound_is_measurable_on_the_real_repo(entry: cadence.CadenceBound) -> None:
    """Each registered bound reads a real number over the real tree.

    A bound whose subject moved would silently read ``unmeasurable`` and, in
    ``report`` mode, keep exiting 0 forever.
    """
    reading = entry.read(_REPO_ROOT)
    assert reading.measured is not None, (
        f"{entry.name} is unmeasurable on the real repo — its subject "
        f"({entry.subject}) has moved or been deleted."
    )


def test_at_bound_passes_and_one_over_breaches(tmp_path: Path) -> None:
    """The boundary itself is inclusive; one more is a breach."""
    entry = _bound("changelog-fragments")

    at_bound = _synthetic_tree(tmp_path / "at", fragments=entry.bound)
    assert _run("check", at_bound).returncode == 0

    over = _synthetic_tree(tmp_path / "over", fragments=entry.bound + 1)
    assert _run("check", over).returncode == 1


def test_check_fails_closed_on_an_unmeasurable_subject(tmp_path: Path) -> None:
    """``check`` refuses to record an unmeasured pass; ``report`` still exits 0.

    The release path fails closed. The gate does not litigate it — a missing
    ``CHANGELOG.md`` is not the business of the change under review.
    """
    root = tmp_path / "tree"
    (root / cadence.FRAGMENT_DIRNAME).mkdir(parents=True)
    # No CHANGELOG.md at all: the byte and line bounds cannot be measured.

    checked = _run("check", root)
    assert checked.returncode == 1
    assert "unmeasurable" in (checked.stdout + checked.stderr).lower()

    reported = _run("report", root)
    assert reported.returncode == 0
    assert "unmeasurable" in reported.stdout.lower()


def test_missing_fragment_directory_reads_zero(tmp_path: Path) -> None:
    """Post-#324 the directory is gone; that is zero pending, not a breach."""
    root = tmp_path / "tree"
    root.mkdir()
    shutil.copy(_REPO_ROOT / "CHANGELOG.md", root / "CHANGELOG.md")

    result = _run("check", root)

    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The migration guard.
# ---------------------------------------------------------------------------


def test_rotation_module_declares_no_absolute_cadence_bound() -> None:
    """The three moved constants must not reappear by copy-paste.

    Narrow by design: it names the three constants that moved, so a genuinely
    new *correctness* bound in that module is unaffected.
    """
    source = (_REPO_ROOT / "tests" / "unit" / "test_changelog_rotation.py").read_text(
        encoding="utf-8"
    )
    moved = ["_FRAGMENT_COUNT_BOUND", "_ROOT_BYTE_BOUND", "_ROOT_LINE_BOUND"]
    present = [name for name in moved if name in source]
    assert not present, (
        f"{present} are cadence bounds and now live in scripts/cadence.py (#350). "
        "Re-declaring them in the gate's test suite rebuilds the wedge: a "
        "release overdue would again halt every unrelated ticket."
    )
