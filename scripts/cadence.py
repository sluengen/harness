"""Release-cadence bounds — enforced on the release path, reported at the gate.

A bound on *accumulated repo state over time* is not the same kind of assertion
as a bound on *this change*, and #350 is what it costs to conflate them. The
``changelog.d/`` fragment count lived in the pytest stage of
``scripts/verify.sh``; when the window went one over, ``verify.sh`` turned red on
``origin/dev`` **independent of any diff**, ``harness review`` refused every
non-zero ``--gate-exit`` before invoking an engine, and five consecutive
unattended build ticks shipped nothing. Every blocked ticket both had not caused
the condition and could not fix it.

That fragment count is gone with the system it measured (#324, ADR 0014) — the
changelog is derived from commits, so there is no pending directory to count.
The reasoning above is kept because it is what sets the *remaining* bounds'
home: they are here, not in the gate, for the same reason.

The discriminator, worth stating because it generalises past this file: ask what
a *single change* can do about the assertion.

* It fails because of the **diff**, and the diff can fix it → **correctness**.
  It belongs in the gate every change must pass.
* It fails because of **accumulated state**, which no one change caused and none
  can fix → **cadence**. It belongs on the release path.

So the bounds here are enforced where they are actionable — the ``staging →
main`` PR, which *is* the release (``RELEASING.md``) — and merely *reported* at
the gate, where they are visible in the bounded evidence tail ``review`` and
``promote`` already record, but cannot halt an unrelated change.

Two modes, and the difference between them is the whole point:

``report``
    Prints one stable line per bound and **always exits 0** for a breach. Run by
    ``scripts/verify.sh`` as its last stage, so a breach lands in the gate log
    tail rather than in the gate's verdict.

``check``
    Exits 1 on any breach *or* any unmeasurable subject. Run by the
    ``release-cadence`` CI job on a PR into ``main`` and by ``RELEASING.md``
    step 3. Fails **closed**: an unmeasurable subject on the release path is a
    reason to stop, not a pass to record.

Only the release fold moves a value here, and it moves it in the same commit
that folds — the rule is unchanged from when these constants lived in
``tests/unit/test_changelog_rotation.py``, only the file changed.

Stdlib only. Reads one subject under ``--repo-root``; never writes, never
deletes, makes no network call and spawns no subprocess.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BOUNDS",
    "CadenceBound",
    "Reading",
    "check",
    "main",
    "report",
]

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: ``CHANGELOG.md``'s ceilings — a **ratchet**, not a headroom budget.
#:
#: Entries do not accumulate here: since #324 a change writes no changelog
#: artifact at all and only the release assembly touches this file, so between
#: releases it does not change. That is what lets the bounds be *may-not-grow*.
#: They are the measurement at the #322 drain baseline (7 lines / 388 bytes)
#: plus the same small stated allowance the #267 baseline used (+4 lines /
#: +577 bytes).
#:
#: **Re-baselined downward at #322**, from 160 lines / 46,500 bytes — the
#: measurement at #267, when the root still carried 12 entries the rotation had
#: never moved. The fold + rotation drained the window into
#: ``CHANGELOG-archive/2026.md``, so the root is now its header, its archive
#: pointer, and an empty ``## [Unreleased]``. A ratchet that only ever moves
#: down is doing its job; these constants tighten by 93% rather than being
#: raised to accommodate the section, which is what landing 76 KB in the root
#: would have required.
#:
#: They are cadence bounds because of how they *breach*: the release assembly
#: inserts a released section, and the tree then sits over the ratchet until the
#: same commit re-baselines it. The per-change hazard they catch in passing — a
#: direct append under ``## [Unreleased]`` — is also caught in the gate by
#: ``test_unreleased_window_carries_no_new_entries``, which is base-independent
#: and has no accumulated-state component. See that test for the pairing.
_ROOT_BYTE_BOUND = 965
_ROOT_LINE_BOUND = 11


@dataclass(frozen=True)
class Reading:
    """One bound's measurement over one tree.

    ``measured is None`` means *unmeasurable* — the subject could not be read at
    all. ``report`` prints it and exits 0; ``check`` treats it as a failure.
    """

    measured: int | None
    detail: str = ""

    @property
    def unmeasurable(self) -> bool:
        return self.measured is None


@dataclass(frozen=True)
class CadenceBound:
    """A bound on accumulated repo state, with the remedy that clears it."""

    name: str
    subject: str
    unit: str
    bound: int
    remedy: str
    measure: Callable[[Path], int]

    def read(self, repo_root: Path) -> Reading:
        try:
            return Reading(self.measure(repo_root))
        except OSError as exc:
            return Reading(None, f"{type(exc).__name__}: {exc}")

    def breached(self, reading: Reading) -> bool:
        return reading.measured is not None and reading.measured > self.bound

    def line(self, reading: Reading) -> str:
        if reading.unmeasurable:
            return (
                f"cadence: {self.subject} unmeasurable/{self.bound:,} "
                f"{self.unit} — {reading.detail}"
            )
        assert reading.measured is not None
        status = "OVER" if self.breached(reading) else "ok"
        line = (
            f"cadence: {self.subject} {reading.measured:,}/{self.bound:,} "
            f"{self.unit} {status}"
        )
        if status == "OVER":
            line += (
                " — blocks the release path, not this change; "
                f"{self.remedy}"
            )
        return line


def _changelog_bytes(repo_root: Path) -> int:
    return len((repo_root / "CHANGELOG.md").read_bytes())


def _changelog_lines(repo_root: Path) -> int:
    text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
    return len(text.splitlines())


#: The single home of every cadence bound. ``RELEASING.md``'s table and its doc
#: guard derive from this tuple; nothing retypes a value.
BOUNDS: tuple[CadenceBound, ...] = (
    CadenceBound(
        name="changelog-bytes",
        subject="CHANGELOG.md size",
        unit="bytes",
        bound=_ROOT_BYTE_BOUND,
        remedy=(
            "re-baseline this ratchet in the release fold's own commit "
            "(RELEASING.md step 3)"
        ),
        measure=_changelog_bytes,
    ),
    CadenceBound(
        name="changelog-lines",
        subject="CHANGELOG.md length",
        unit="lines",
        bound=_ROOT_LINE_BOUND,
        remedy=(
            "re-baseline this ratchet in the release fold's own commit "
            "(RELEASING.md step 3)"
        ),
        measure=_changelog_lines,
    ),
)


def _readings(repo_root: Path) -> list[tuple[CadenceBound, Reading]]:
    return [(entry, entry.read(repo_root)) for entry in BOUNDS]


def report(repo_root: Path, *, stream: object = None) -> int:
    """Print every bound; exit 0 regardless of breach.

    The gate's mode. A breach is loud in the output — and therefore in the
    bounded gate-log tail ``review`` records — without being the gate's verdict.
    """
    out = stream if stream is not None else sys.stdout
    for entry, reading in _readings(repo_root):
        print(entry.line(reading), file=out)  # type: ignore[arg-type]
    return 0


def check(repo_root: Path) -> int:
    """Exit 1 on any breach or unmeasurable subject.

    The release path's mode: fails closed, because an unmeasured bound on the
    way into ``main`` is exactly the pass nobody should be able to record.
    """
    failures: list[str] = []
    for entry, reading in _readings(repo_root):
        print(entry.line(reading))
        if reading.unmeasurable:
            failures.append(
                f"{entry.name}: {entry.subject} is unmeasurable ({reading.detail}). "
                "The release path fails closed rather than record an unmeasured pass."
            )
        elif entry.breached(reading):
            assert reading.measured is not None
            failures.append(
                f"{entry.name}: {entry.subject} is {reading.measured:,} "
                f"{entry.unit}, over the {entry.bound:,} bound — {entry.remedy}."
            )
    if not failures:
        return 0
    sys.stdout.flush()  # so the per-bound lines precede the summary when piped
    print("", file=sys.stderr)
    print("release cadence: NOT clear to release", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "mode",
        choices=("report", "check"),
        help=(
            "report: print every bound, always exit 0 (the gate). "
            "check: exit 1 on a breach or an unmeasurable subject (the release path)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_REPO_ROOT,
        help="tree to measure (defaults to this checkout)",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    return report(repo_root) if args.mode == "report" else check(repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
