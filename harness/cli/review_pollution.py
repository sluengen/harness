"""How far a run worktree has drifted past its own git index — #359.

``review``'s hang had one cause and one cure, and for three ticks the cure was a
rule an operator had to keep. The gate's ``.venv`` and caches, sitting in the
**run** worktree, drown the review engine's tool-using pass: #205 traced it, and
#208 kept the rule — deliberately routing ``uv`` at an external environment —
and *still* arrived at review with 3,555 files on disk against 578 tracked. That
review burned the full ``engine_timeout_seconds`` ceiling and returned
``engine_timeout`` having reviewed nothing. Deleting the stray ``.venv`` took the
tree to 586/578 and the very next review returned a real verdict in ~9 minutes.

This module is that rule as a mechanism. It converts a silent 720-second burn
into an instant refusal that states its own remedy — measured in ~90ms on the
observed tree, five orders of magnitude cheaper than the failure it forecloses.

What it measures, and why that shape
------------------------------------
``excess`` is ``scanned - tracked``: on-disk files against the size of the index,
**not** the size of the set difference. Counting is deliberate. A set-membership
test compares two *spellings* of a path, and macOS hands back NFD where git
prints NFC — so every non-ASCII filename would count as excess and the guard
would refuse a clean tree, the one direction it must never fail in. Subtraction
cannot make that mistake, and it errs safely besides: a tracked file deleted from
the working tree lowers ``scanned`` while ``tracked`` still counts it, so the
error runs toward *not* refusing.

The cost of that choice is that ``largest`` counts every file under a segment
rather than only the untracked ones, so a segment holding real source is named
with its real size. That is why the refusal calls them the worktree's *largest
top-level entries* rather than its offenders: pollution outweighs source by
orders of magnitude when it is present at all (``.venv`` at 3,036 against the
whole rest of the tree at ~800), so the polluter still sorts first, and the
number beside each name is a fact rather than an accusation.

Depth-1 only, always. A root-level ``.env.production`` is aggregated under
``(root)`` and never named. That is a confidentiality property of the refusal —
what escapes to the ledger and to the orchestrator's context is integers plus at
most three top-level segment names — not an accident of the implementation.

Fail-open, without exception
----------------------------
Every unanswerable case answers ``None`` (*no opinion*) and the verb proceeds to
review: a limit of 0 (the configured off switch), a path that is not a git
top-level, a failed or wedged ``git ls-files``, an empty index. A guard that
*stops* a run may rest only on evidence it actually gathered — the same asymmetry
:mod:`harness.cli.reclaim_liveness` states for its three clocks. The failure this
guard prevents is expensive but recoverable; refusing a legitimate review is not.

Bounded against the tree it reads
---------------------------------
The worktree's contents are untrusted — the pollution being measured was written
by tooling nobody has identified (#208, and finding the cause is explicitly out
of that ticket's scope). So the scan reads *directory entries only*: never a file
content, never a ``stat``, never an ``open``. ``followlinks=False`` and the
``.git`` prune mean a symlink pointing outside the worktree — or at a parent — is
counted once and never traversed, so the scan cannot leave the worktree and
cannot fail to terminate. The prune drops a directory of that name at **any**
depth, not only the worktree's own: a nested repository someone left behind is
pollution and its working files count, but git's object churn is git's and is
nothing the operator can act on. Unreadable directories are skipped rather than raised
on. And the entry cap makes the work constant rather than proportional: a
200,000-file tree costs the same as a 5,000-file one, which is what keeps this
guard from becoming its own version of the burn it exists to prevent.

It lives outside :mod:`harness.cli.review` on the ``review_inherit`` /
``review_telemetry`` precedent — that verb is watchlisted and already carries the
orchestration, the breakers and the gate glue — so the verb grows a call site and
a refusal, not a filesystem walk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from harness._git import tracked_paths

__all__ = [
    "POLLUTION_SCAN_CAP_MULTIPLIER",
    "ROOT_SEGMENT",
    "SegmentCount",
    "WorktreePollution",
    "measure_worktree_pollution",
    "pollution_refusal_message",
]

#: What a root-level file is attributed to. A fixed placeholder rather than the
#: filename: only depth-1 segments are ever reported, so a secret at the root is
#: aggregated instead of named (see the module docstring).
ROOT_SEGMENT = "(root)"

#: The scan cap, as a multiple of the limit on top of the tracked count:
#: ``tracked + POLLUTION_SCAN_CAP_MULTIPLIER * limit`` entries. Deciding needs
#: only ``limit + 1`` excess entries; the headroom is what makes the attribution
#: accurate rather than an artefact of walk order — the observed 3,555-file tree
#: fits entirely inside ``578 + 4 * 1000``, so its polluter ranks correctly.
POLLUTION_SCAN_CAP_MULTIPLIER = 4

#: How many top-level segments the refusal names.
_LARGEST_REPORTED = 3


@dataclass(frozen=True)
class SegmentCount:
    """One top-level entry of the worktree and how many files sit beneath it."""

    segment: str
    files: int


@dataclass(frozen=True)
class WorktreePollution:
    """A worktree measured against its index. Never constructed for *no opinion*."""

    tracked: int
    scanned: int
    excess: int
    limit: int
    truncated: bool
    largest: tuple[SegmentCount, ...]

    @property
    def refuses(self) -> bool:
        """Whether this measurement is past the bound.

        Strictly greater: a tree exactly at the limit is the configured budget
        being *spent*, not exceeded.
        """
        return self.excess > self.limit

    def as_payload(self) -> dict[str, object]:
        """The structured refusal detail, for the error JSON and the ledger."""
        return {
            "tracked": self.tracked,
            "scanned": self.scanned,
            "excess": self.excess,
            "limit": self.limit,
            "truncated": self.truncated,
            "largest": [
                {"segment": entry.segment, "files": entry.files}
                for entry in self.largest
            ],
        }


def measure_worktree_pollution(
    worktree: Path, *, limit: int
) -> WorktreePollution | None:
    """Measure ``worktree`` against its git index — or ``None`` for *no opinion*.

    Sync (it shells out and walks a directory tree); call it through
    :func:`asyncio.to_thread` from async code.

    ``None`` is returned when ``limit`` is 0 (the check is disabled, and nothing
    is spawned or walked), and for every case :func:`~harness._git.tracked_paths`
    cannot answer: not a directory, not a git top-level, a failed or timed-out
    ``git ls-files``, or an empty index.
    """
    if limit <= 0:
        return None
    tracked = tracked_paths(worktree)
    if tracked is None:
        return None

    cap = len(tracked) + POLLUTION_SCAN_CAP_MULTIPLIER * limit
    scanned = 0
    truncated = False
    buckets: dict[str, int] = {}

    # ``onerror`` is omitted deliberately: os.walk's default is to swallow the
    # listdir error and skip that directory, which is exactly the policy here —
    # an unreadable subtree is not a reason to refuse a review.
    for root, dirs, files in os.walk(worktree, topdown=True, followlinks=False):
        if ".git" in dirs:
            dirs.remove(".git")
        # Sorted so a truncated scan is deterministic rather than dependent on
        # the order the filesystem happened to hand back.
        dirs.sort()
        relative = Path(root).relative_to(worktree)
        segment = ROOT_SEGMENT if relative == Path(".") else relative.parts[0]
        remaining = cap - scanned
        if len(files) > remaining:
            buckets[segment] = buckets.get(segment, 0) + remaining
            scanned = cap
            truncated = True
            break
        buckets[segment] = buckets.get(segment, 0) + len(files)
        scanned += len(files)

    largest = tuple(
        SegmentCount(segment=name, files=count)
        for name, count in sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))
        if count
    )[:_LARGEST_REPORTED]

    return WorktreePollution(
        tracked=len(tracked),
        scanned=scanned,
        # Clamped: a tracked file deleted from the working tree makes the
        # difference negative, which is *less* pollution, not a strange amount.
        excess=max(0, scanned - len(tracked)),
        limit=limit,
        truncated=truncated,
        largest=largest,
    )


def pollution_refusal_message(measured: WorktreePollution) -> str:
    """The human half of the refusal: the counts, the offenders, and the remedy.

    AC-2 — the operator must not have to re-derive any of it. The named segments
    come from the measurement rather than a guess at the cause, because #208's
    cause was never identified and this guard has to fire on whatever wrote the
    files.
    """
    named = (
        ", ".join(f"`{entry.segment}` ({entry.files:,} files)" for entry in measured.largest)
        or "none"
    )
    at_least = "at least " if measured.truncated else ""
    return (
        f"the run worktree holds {at_least}{measured.scanned:,} files against "
        f"{measured.tracked:,} git-tracked ({measured.excess:,} excess, limit "
        f"{measured.limit:,}). Largest top-level entries: {named}. A run worktree "
        f"this far past its index drowns the review engine's tool use — the "
        f"observed signature is a review that burns the whole engine timeout and "
        f"returns engine_timeout having reviewed nothing (#208). No engine was "
        f"invoked and no verdict was recorded, and this refusal costs no review "
        f"cycle. Remove what does not belong — most often a verify-gate `.venv`, "
        f"so run the gate against an environment OUTSIDE the worktree (e.g. "
        f"UV_PROJECT_ENVIRONMENT=<path outside the worktree>) — then re-run "
        f"review. The harness does not delete files underneath a live run. To "
        f"raise or disable the bound, set loop.untracked_file_limit in CONTEXT.md "
        f"(0 disables)."
    )
