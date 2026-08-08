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

#324 deleted the fragment system, so the bound whose breach caused all this is
gone with the directory it counted. What remains — ``CHANGELOG.md``'s byte and
line ratchets — is the same category and is exercised here the same way, over
**synthetic trees built from the bound's own value**. Nothing in this module
retypes a number: a test that hardcoded ``965`` would keep passing after a
release re-baselined the ratchet, which is precisely the drift the #350 shape
exists to prevent.

These tests are the executable form of the acceptance criteria:

* **#350 AC-4 — the property**, over a *synthetic over-bound tree*: the same
  tree makes ``verify.sh``'s cadence stage exit 0 and the release check exit 1.
  Both halves run the **real** ``scripts/cadence.py`` as a subprocess.
* **#350 AC-2 — the breach is still enforced**, so ``check`` fails closed on an
  unmeasurable subject. That arm is the easiest one here to leave untested and
  the one whose absence silently turns the release gate into a rubber stamp.
* **The binding test** (:func:`test_verify_runs_report_never_check`) is what
  makes the AC-4 pair mean anything: without it, both halves would prove a
  property of a command nobody runs.
* **#324 AC-2 — the ratchets survived the fragment deletion with their teeth.**
  :func:`test_an_appended_entry_breaches_the_root_ratchet` plants a realistic
  entry under ``## [Unreleased]`` and asserts the real script refuses the tree,
  and :func:`test_each_root_ratchet_is_independently_breachable` breaches each
  bound *alone* — because a tree that trips both cannot tell you which one is
  still doing the work, and a silently-dead line bound would look identical.
* **The migration guard** pins that the moved constants do not reappear in
  ``tests/unit/test_changelog_rotation.py`` by copy-paste — the realistic
  regression, and the one that would rebuild the wedge in place.

Deliberately **not** asserted: "this repo is over a bound". That is live-tree
evidence, not a property — it inverts into a false failure the moment a release
re-baselines.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import cadence  # noqa: E402

_SCRIPT = _REPO_ROOT / "scripts" / "cadence.py"
_VERIFY = _REPO_ROOT / "scripts" / "verify.sh"

#: The real root changelog, the substrate every synthetic tree is grown from —
#: so a tree differs from the live repo only by the append under test.
_REAL_CHANGELOG = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

#: The two bounds over ``CHANGELOG.md``, by name. Each is looked up in
#: ``cadence.BOUNDS`` at use; these are the keys, never the values.
_BYTES = "changelog-bytes"
_LINES = "changelog-lines"


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


def _tree(tmp_path: Path, changelog: str) -> Path:
    """A repo tree whose only subject is the given ``CHANGELOG.md`` text."""
    root = tmp_path / "tree"
    root.mkdir(parents=True, exist_ok=True)
    (root / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return root


def _grown_to(*, size_bytes: int) -> str:
    """The real changelog grown to *exactly* ``size_bytes`` by one padded line.

    One line, so the byte bound can be breached while the line bound stays
    comfortably green — that separation is what lets each ratchet be proven
    alone. The size is passed in from a bound's own value, never typed here.
    """
    base = _REAL_CHANGELOG.rstrip("\n") + "\n"
    envelope = f"{base}<!--  -->\n"
    overhead = len(envelope.encode("utf-8"))
    assert size_bytes >= overhead, (
        f"cannot grow the changelog to {size_bytes} bytes — the real file plus "
        f"a minimal comment line is already {overhead}. The byte ratchet has "
        "been re-baselined below the file it bounds."
    )
    return f"{base}<!-- {'x' * (size_bytes - overhead)} -->\n"


def _grown_by_lines(*, extra: int) -> str:
    """The real changelog with ``extra`` short lines appended.

    Short, so the line bound can be breached while the byte bound stays green.
    """
    base = _REAL_CHANGELOG.rstrip("\n") + "\n"
    return base + "".join(f"<!-- {index} -->\n" for index in range(extra))


# ---------------------------------------------------------------------------
# #350 AC-4 — the property, on one synthetic over-bound tree.
# ---------------------------------------------------------------------------


def test_over_bound_tree_fails_the_release_check(tmp_path: Path) -> None:
    """The release path refuses a tree over the cadence bound."""
    entry = _bound(_BYTES)
    over = entry.bound + 1
    tree = _tree(tmp_path, _grown_to(size_bytes=over))

    result = _run("check", tree)

    assert result.returncode == 1, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "CHANGELOG.md" in combined
    assert str(over) in combined
    assert str(entry.bound) in combined
    assert "release" in combined.lower()


def test_over_bound_tree_passes_the_gates_cadence_stage(tmp_path: Path) -> None:
    """The *same* tree leaves the per-change gate green, and says why.

    This is the half the wedge was about: a change that neither caused the
    breach nor can fix it must still reach review.
    """
    entry = _bound(_BYTES)
    over = entry.bound + 1
    tree = _tree(tmp_path, _grown_to(size_bytes=over))

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


def test_the_registry_still_bounds_the_root_changelog() -> None:
    """The floor under the parametrized test above.

    A derived ``@parametrize`` whose source collapsed to nothing collects zero
    cases and reports **green**. This names the two bounds that must be in
    ``BOUNDS`` for that test to mean anything — the deletion in #324 removed one
    entry from this tuple, and nothing else structural stopped it removing three.
    """
    names = {entry.name for entry in cadence.BOUNDS}
    assert {_BYTES, _LINES} <= names, (
        f"scripts/cadence.py must bound CHANGELOG.md's size and length, but "
        f"BOUNDS registers only {sorted(names)}."
    )


def test_at_bound_passes_and_one_over_breaches(tmp_path: Path) -> None:
    """The boundary itself is inclusive; one more byte is a breach."""
    entry = _bound(_BYTES)

    at_bound = _tree(tmp_path / "at", _grown_to(size_bytes=entry.bound))
    assert _run("check", at_bound).returncode == 0

    over = _tree(tmp_path / "over", _grown_to(size_bytes=entry.bound + 1))
    assert _run("check", over).returncode == 1


def test_check_fails_closed_on_an_unmeasurable_subject(tmp_path: Path) -> None:
    """``check`` refuses to record an unmeasured pass; ``report`` still exits 0.

    The release path fails closed. The gate does not litigate it — a missing
    ``CHANGELOG.md`` is not the business of the change under review.
    """
    root = tmp_path / "tree"
    root.mkdir()
    # No CHANGELOG.md at all: neither the byte nor the line bound can be read.

    checked = _run("check", root)
    assert checked.returncode == 1
    assert "unmeasurable" in (checked.stdout + checked.stderr).lower()

    reported = _run("report", root)
    assert reported.returncode == 0
    assert "unmeasurable" in reported.stdout.lower()


# ---------------------------------------------------------------------------
# #324 AC-2 — the ratchets survived the fragment deletion, with their teeth.
# ---------------------------------------------------------------------------


def test_an_appended_entry_breaches_the_root_ratchet(tmp_path: Path) -> None:
    """A realistic entry appended under ``## [Unreleased]`` is refused.

    The shape the ratchet exists to catch, planted rather than reasoned about:
    before #267 every change appended an entry here, and after #324 the release
    assembles from commits, so the window must stay empty either way. The entry
    is a real one — #371's, taken verbatim from the window this ticket drained —
    grown to clear the headroom so the test states what it needs rather than
    depending on today's file being close enough to the bound.
    """
    entry = _bound(_BYTES)
    headroom = entry.bound - len(_REAL_CHANGELOG.encode("utf-8"))
    assert headroom >= 0, (
        "the real CHANGELOG.md is already over its byte ratchet — re-baseline "
        "it in the release commit before reading anything into this test."
    )

    body = (
        "`close`'s teardown ran a repo-wide `git worktree prune`, which "
        "deregistered every worktree whose directory was missing, not only the "
        "one it had just removed. "
    )
    planted = (
        "\n### Fixed — worktree teardown no longer deregisters worktrees it was "
        "not asked to touch (#371)\n\n"
        + body * (headroom // len(body.encode("utf-8")) + 1)
        + "\n"
    )
    appended = _REAL_CHANGELOG.rstrip("\n") + "\n" + planted
    assert len(appended.encode("utf-8")) > entry.bound, (
        "the planted entry did not clear the headroom — this test would then "
        "assert nothing about the ratchet."
    )

    result = _run("check", _tree(tmp_path, appended))

    assert result.returncode == 1, (
        "an entry appended under ## [Unreleased] must breach the root ratchet, "
        f"but `cadence.py check` exited 0:\n{result.stdout}{result.stderr}"
    )
    assert "CHANGELOG.md" in result.stdout + result.stderr


@pytest.mark.parametrize("name", [_BYTES, _LINES])
def test_each_root_ratchet_is_independently_breachable(name: str, tmp_path: Path) -> None:
    """Each bound refuses a tree that breaches **only** it.

    A single tree that trips both cannot distinguish a live bound from a dead
    one — the exit code would be identical if the line bound had been dropped
    alongside the fragment count it sat next to. So each is breached alone, and
    the other is asserted still green in the same run.
    """
    entry = _bound(name)
    other = _bound(_LINES if name == _BYTES else _BYTES)

    if name == _BYTES:
        changelog = _grown_to(size_bytes=entry.bound + 1)
    else:
        current = len(_REAL_CHANGELOG.splitlines())
        changelog = _grown_by_lines(extra=entry.bound - current + 1)

    tree = _tree(tmp_path, changelog)
    assert entry.read(tree).measured > entry.bound, (
        f"the planted tree does not breach {name} — it proves nothing."
    )
    assert other.read(tree).measured <= other.bound, (
        f"the planted tree also breaches {other.name}, so a refusal cannot be "
        f"attributed to {name}. Adjust the plant, not the assertion."
    )

    result = _run("check", tree)

    assert result.returncode == 1, (
        f"{name} did not refuse a tree over its bound — the ratchet is inert:\n"
        f"{result.stdout}{result.stderr}"
    )
    assert entry.subject in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The migration guard.
# ---------------------------------------------------------------------------


def test_rotation_module_declares_no_absolute_cadence_bound() -> None:
    """The moved constants must not reappear by copy-paste.

    Narrow by design: it names the constants that moved, so a genuinely new
    *correctness* bound in that module is unaffected. ``_FRAGMENT_COUNT_BOUND``
    stays on the list after #324 deleted it — a constant that no longer exists
    anywhere is exactly the one a future edit could reintroduce without noticing
    it is rebuilding the wedge.
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
