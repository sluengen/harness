"""Promotion worktree + merge mechanics — the deterministic git half of promotion.

``harness promote start`` / ``continue`` (:mod:`harness.cli.promote`) are the
audited orchestration; this module is their **mechanics**, the promotion analogue
of :mod:`harness.worktree` for build runs (CAL-1115, ADR 0003). It owns only git
and conflict classification — it knows nothing about the ledger or Typer:

* :func:`fetch_origin` — refresh the remote refs the promotion reads.
* :func:`validate_branch_pair` — refuse an ``origin/<from>`` → ``origin/<to>``
  pair that is degenerate (``from == to``) or names a branch ``origin`` does not
  carry (an unclean base / ambiguous topology → an invocation refusal, no row).
* :func:`promotion_branch_name` — the deterministic ``promote/<date>-<from>-to-<to>``
  branch name from the design record.
* :func:`create_promotion_worktree` — a worktree at
  ``.worktrees/harness/<promotion_id>`` on that promotion branch, **based on the
  target** ``origin/<to>`` (so the merge lands on the branch we will PR).
* :func:`attempt_merge` — merge ``origin/<from>`` into it. Clean → the merged
  HEAD; conflict → the worktree is **left in progress** (resumable) and the
  conflicted files are :func:`classify_conflicts`-ed against the ADR 0003 repair
  policy.
* :func:`conflicted_files` / :func:`abort_merge` / :func:`complete_merge` — the
  resume primitives ``continue`` drives after a bounded, in-policy repair.

No PR, no push, no auto-merge, and **no gate** (gate evidence is CAL-1116): the
merge commit lands only in the promotion worktree, and only ``promote pr``
(CAL-1117) ever pushes it. Never a direct push to ``staging`` / ``main``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from harness.cli._git import NETWORK_GIT_TIMEOUT_SECONDS, run_git
from harness.worktree import worktree_path

__all__ = [
    "MAX_REPAIRABLE_CONFLICT_FILES",
    "MergeOutcome",
    "PromotionMechanicsError",
    "abort_merge",
    "attempt_merge",
    "classify_conflicts",
    "complete_merge",
    "conflicted_files",
    "create_promotion_worktree",
    "fetch_origin",
    "promotion_branch_name",
    "validate_branch_pair",
]


# ---------------------------------------------------------------------------
# Conflict classification — the ADR 0003 repair-authority policy.
# ---------------------------------------------------------------------------

#: Path fragments that force ``needs_ticket``: a conflict touching one of these
#: exceeds local repair authority (schema migrations; auth / payment / security /
#: release / deployment scripts; dependency lockfiles — ADR 0003). Matched
#: case-insensitively as a substring of each conflicted path. Deliberately
#: **conservative** — over-escalation only costs a human a glance, while a missed
#: escalation risks an autonomous repair of release-critical code.
_ESCALATE_PATH_FRAGMENTS: tuple[str, ...] = (
    "migration",
    "auth",
    "payment",
    "security",
    "release",
    "deploy",
    # dependency lockfiles
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "pipfile.lock",
    "cargo.lock",
    "gemfile.lock",
    "composer.lock",
    "go.sum",
)

#: The most conflicted files a single promotion may carry and still be a bounded,
#: in-policy repair. Beyond this the merge is too broad for one attempt →
#: ``needs_ticket`` regardless of file kind (ADR 0003 "conflicts over the file
#: threshold"). A measurable bound — pinned by a measuring test.
MAX_REPAIRABLE_CONFLICT_FILES = 10


def classify_conflicts(files: Sequence[str]) -> str:
    """Classify a merge's conflicted files as ``agent_may_fix`` or ``needs_ticket``.

    ``needs_ticket`` when the conflict spans more than
    :data:`MAX_REPAIRABLE_CONFLICT_FILES` files, or when *any* conflicted path
    matches a sensitive file kind (:data:`_ESCALATE_PATH_FRAGMENTS`); otherwise
    ``agent_may_fix`` — a small, low-semantic conflict the orchestrator may
    repair once before calling ``continue`` (ADR 0003 repair authority).
    """
    if len(files) > MAX_REPAIRABLE_CONFLICT_FILES:
        return "needs_ticket"
    for path in files:
        lowered = path.lower()
        if any(fragment in lowered for fragment in _ESCALATE_PATH_FRAGMENTS):
            return "needs_ticket"
    return "agent_may_fix"


# ---------------------------------------------------------------------------
# Branch naming.
# ---------------------------------------------------------------------------


def promotion_branch_name(
    from_branch: str, to_branch: str, *, day: date | None = None
) -> str:
    """The deterministic promotion branch name ``promote/<date>-<from>-to-<to>``.

    Follows the design record (ADR 0003): a branch created from the target, e.g.
    ``promote/2026-07-17-dev-to-staging``. ``/`` in a branch component is slugged
    to ``-`` so the promotion branch stays a single ref segment under
    ``promote/``. ``day`` defaults to today (UTC).
    """
    day = day or datetime.now(UTC).date()
    return f"promote/{day.isoformat()}-{_slug(from_branch)}-to-{_slug(to_branch)}"


def _slug(branch: str) -> str:
    """Collapse a branch name into one promotion-branch path segment."""
    return branch.replace("/", "-")


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class PromotionMechanicsError(RuntimeError):
    """A promotion git mechanic failed or was misused.

    Carries a stable, machine-readable ``reason`` so the CLI can surface it as a
    structured refusal an orchestrator branches on (mirroring ``VerbError`` for
    the build verbs).
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# ---------------------------------------------------------------------------
# Merge outcome.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeOutcome:
    """The result of a merge attempt (or resume).

    ``clean`` merges carry ``merged_sha`` (the promotion worktree HEAD) and no
    conflict data; a conflict carries the sorted ``conflict_files`` and their
    ``classification`` (``agent_may_fix`` / ``needs_ticket``) with
    ``merged_sha=None`` and the worktree left resumable.
    """

    clean: bool
    merged_sha: str | None = None
    conflict_files: tuple[str, ...] = ()
    classification: str | None = None


# ---------------------------------------------------------------------------
# Git mechanics.
# ---------------------------------------------------------------------------


def fetch_origin(repo_root: Path) -> None:
    """``git fetch origin`` so the promotion reads current remote refs.

    Raises :class:`PromotionMechanicsError` (``reason='fetch_failed'``) on a
    non-zero fetch or a network timeout — the promotion cannot proceed on stale
    or unreachable refs.
    """
    try:
        result = run_git(
            repo_root, "fetch", "origin", timeout=NETWORK_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise PromotionMechanicsError(
            f"git fetch origin exceeded the {NETWORK_GIT_TIMEOUT_SECONDS}s network "
            "timeout; the remote may be unreachable",
            reason="fetch_failed",
        ) from exc
    if result.returncode != 0:
        raise PromotionMechanicsError(
            f"git fetch origin failed: {result.stderr.strip()}",
            reason="fetch_failed",
        )


def validate_branch_pair(repo_root: Path, from_branch: str, to_branch: str) -> None:
    """Refuse a degenerate or unresolvable ``from`` → ``to`` promotion pair.

    ``from == to`` is a no-op promotion; a branch ``origin`` does not carry is an
    unclean base. Either raises :class:`PromotionMechanicsError`
    (``reason='invalid_branch_pair'``) before any worktree is created, so an
    invalid pair leaves no ledger row behind. Call after :func:`fetch_origin` so
    the ``origin/<branch>`` refs are current.
    """
    if from_branch == to_branch:
        raise PromotionMechanicsError(
            f"cannot promote branch {from_branch!r} into itself",
            reason="invalid_branch_pair",
        )
    for branch in (from_branch, to_branch):
        result = run_git(
            repo_root, "rev-parse", "--verify", "--quiet", f"origin/{branch}"
        )
        if result.returncode != 0:
            raise PromotionMechanicsError(
                f"branch origin/{branch} not found — fetch the remote or check the "
                "branch name before promoting",
                reason="invalid_branch_pair",
            )


def create_promotion_worktree(
    repo_root: Path, promotion_id: str, *, to_branch: str, branch_name: str
) -> Path:
    """Create the promotion worktree at ``.worktrees/harness/<promotion_id>``.

    The worktree is a fresh branch ``branch_name`` **based on the target**
    ``origin/<to_branch>`` — the merge lands on the branch that will later be
    PR'd. Reuses the ``.worktrees/harness/`` area so ``harness worktrees cleanup``
    reclaims a merged promotion exactly as it does a build run. Writes relative
    worktree pointers (git ≥ 2.48) so the path resolves identically on host and in
    the container (CAL-866). Raises :class:`PromotionMechanicsError` if the path
    already exists (``reason='worktree_exists'``) or ``git worktree add`` fails
    (``reason='worktree_create_failed'``).
    """
    path = worktree_path(repo_root, promotion_id)
    if path.exists():
        raise PromotionMechanicsError(
            f"promotion worktree already exists at {path}; refusing to reuse",
            reason="worktree_exists",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(
        repo_root,
        "-c",
        "worktree.useRelativePaths=true",
        "worktree",
        "add",
        "-b",
        branch_name,
        str(path),
        f"origin/{to_branch}",
    )
    if result.returncode != 0:
        # Never leave a half-created directory behind (mirrors WorktreeNode).
        if path.exists():
            run_git(repo_root, "worktree", "remove", "--force", str(path))
            run_git(repo_root, "worktree", "prune")
        raise PromotionMechanicsError(
            f"git worktree add failed for promotion branch {branch_name!r}: "
            f"{result.stderr.strip()}",
            reason="worktree_create_failed",
        )
    return path


def attempt_merge(worktree: Path, *, from_branch: str) -> MergeOutcome:
    """Merge ``origin/<from_branch>`` into the promotion worktree; classify the result.

    A clean merge returns ``MergeOutcome(clean=True, merged_sha=<HEAD>)``. A
    conflict is **left in progress** — the worktree stays resumable so the
    orchestrator can repair and ``continue`` — and returns the sorted conflicted
    files with their :func:`classify_conflicts` classification. A merge that fails
    with *no* conflicted paths (a genuine git error, not a content conflict) is
    aborted and raised as :class:`PromotionMechanicsError`
    (``reason='merge_failed'``).
    """
    result = run_git(
        worktree,
        "merge",
        "--no-ff",
        f"origin/{from_branch}",
        "-m",
        f"Merge origin/{from_branch} into promotion candidate",
    )
    if result.returncode == 0:
        return MergeOutcome(clean=True, merged_sha=_head(worktree))

    files = conflicted_files(worktree)
    if not files:
        # No unmerged paths ⇒ this was not a content conflict but a git error
        # (e.g. an unrelated-history refusal). Leave nothing half-merged.
        abort_merge(worktree)
        raise PromotionMechanicsError(
            f"git merge origin/{from_branch} failed: {result.stderr.strip()}",
            reason="merge_failed",
        )
    return MergeOutcome(
        clean=False,
        conflict_files=tuple(files),
        classification=classify_conflicts(files),
    )


def conflicted_files(worktree: Path) -> tuple[str, ...]:
    """The worktree's unmerged (conflicted) paths, sorted; empty if none.

    ``git diff --name-only --diff-filter=U`` — the files with conflict markers a
    resume must resolve. Sorted for a deterministic contract.
    """
    result = run_git(worktree, "diff", "--name-only", "--diff-filter=U")
    if result.returncode != 0:
        return ()
    return tuple(sorted(line for line in result.stdout.splitlines() if line.strip()))


def abort_merge(worktree: Path) -> None:
    """``git merge --abort`` the in-progress merge — best-effort, never raises."""
    run_git(worktree, "merge", "--abort")


def complete_merge(worktree: Path) -> MergeOutcome:
    """Finalize a repaired merge in the worktree, committing the resolution.

    Called by ``continue`` after the orchestrator has resolved and **staged**
    (``git add``) the conflicts. Refuses — raising
    :class:`PromotionMechanicsError` (``reason='dirty_worktree'``) — if any
    unmerged path remains, so an incomplete repair cannot be committed. On a fully
    resolved tree it commits the merge (``--no-edit``) and returns
    ``MergeOutcome(clean=True, merged_sha=<HEAD>)``.
    """
    remaining = conflicted_files(worktree)
    if remaining:
        raise PromotionMechanicsError(
            "promotion worktree still has unresolved conflicts: "
            f"{', '.join(remaining)}",
            reason="dirty_worktree",
        )
    result = run_git(worktree, "commit", "--no-edit")
    if result.returncode != 0:
        raise PromotionMechanicsError(
            f"failed to commit the resolved promotion merge: {result.stderr.strip()}",
            reason="merge_commit_failed",
        )
    return MergeOutcome(clean=True, merged_sha=_head(worktree))


def _head(worktree: Path) -> str:
    """The worktree's HEAD SHA. Raises :class:`PromotionMechanicsError` on failure."""
    result = run_git(worktree, "rev-parse", "HEAD")
    if result.returncode != 0:
        raise PromotionMechanicsError(
            f"git rev-parse HEAD failed in {worktree}: {result.stderr.strip()}",
            reason="rev_parse_failed",
        )
    return result.stdout.strip()
