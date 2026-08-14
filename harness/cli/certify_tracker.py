"""``certify``'s tracker I/O — replace the assurance label, say why (#353).

The verb touches the tracker at exactly one moment: after a run's diff turns out
not to be certifiable, the issue's ``assurance:trivial`` label is replaced with
``assurance:simple`` and a comment records the deterministic reason. That is a
tracker boundary rather than verb orchestration, so it lives here and
:mod:`harness.cli.certify` keeps only the flow around it — the same split
:mod:`harness.cli.design_tracker` records, and split at birth for the same
reason (#211): a brand-new module should not be born over the 500-line limit
with a ``# size:`` marker papering over a seam that plainly exists.

The layering is one-way. This module raises a tracker-shaped failure
(:class:`UpgradeSyncError`) naming *which artifact* did not synchronize, and
knows nothing of exit codes or ``reason`` tags. The verb owns that vocabulary.

**Only the assurance label is touched, and that is a mechanism rather than an
intention.** Both calls are single-label operations on the
:class:`~harness.tracker.Tracker` protocol; nothing here enumerates the issue's
labels and writes a set back. So "unrelated labels are preserved" holds by
construction — there is no code path that could drop one — which is why the test
asserts the *call log* rather than the resulting label set.

Remove-then-apply, in that order. Either order is safe for the harness
(:func:`~harness.assurance.resolve_assurance` reads both a conflict and an
absence as ``simple``, and this run has already snapshotted its level anyway),
but a human reading the issue mid-sync must never see two contradictory levels.
"""

from __future__ import annotations

from collections.abc import Sequence

from harness.assurance import ASSURANCE_LABEL_PREFIX, DEFAULT_ASSURANCE
from harness.tracker import Tracker
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

__all__ = [
    "COMMENT_ARTIFACT",
    "LABEL_ARTIFACT",
    "UpgradeSyncError",
    "sync_upgrade",
    "upgrade_comment",
]

#: The label the run stated and did not earn.
TRIVIAL_LABEL = f"{ASSURANCE_LABEL_PREFIX}trivial"
#: The label it is upgraded to — the level that requires an LLM review.
UPGRADED_LABEL = f"{ASSURANCE_LABEL_PREFIX}{DEFAULT_ASSURANCE}"

#: The two artifacts a partial sync can leave behind, named on the verb's output
#: so a caller knows what to reconcile by hand rather than re-deriving it.
LABEL_ARTIFACT = "label"
COMMENT_ARTIFACT = "comment"

#: How many offending paths the comment names. The classifier already bounds its
#: list; this is the second bound, so a comment stays readable even if that one
#: is ever widened.
_COMMENT_PATH_LIMIT = 10


class UpgradeSyncError(Exception):
    """The upgrade landed on the run row but not on the issue.

    ``artifact`` is :data:`LABEL_ARTIFACT` or :data:`COMMENT_ARTIFACT` — which
    write did not take. The run row is already authoritative by the time this can
    be raised, so it is never a reason to roll anything back.
    """

    def __init__(self, artifact: str, detail: str) -> None:
        super().__init__(f"{artifact}: {detail}")
        self.artifact = artifact
        self.detail = detail


def upgrade_comment(
    *,
    run_id: str,
    reason: str,
    offending_paths: Sequence[str],
    classifier_version: int,
) -> str:
    """The comment body. Deterministic — same inputs, same bytes.

    It names the run, the machine-readable reason, the paths that caused it and
    the classifier version, then says plainly what happens next. A reader
    arriving at the issue should not have to open the ledger to learn why the
    level they asked for is not the level the run is under.
    """
    lines = [
        f"**Assurance upgraded to `{DEFAULT_ASSURANCE}`** (run `{run_id}`).",
        "",
        f"This run stated `{TRIVIAL_LABEL}`, but its diff is not certifiable "
        f"without a review: `{reason}` (classifier v{classifier_version}).",
    ]
    if offending_paths:
        shown = list(offending_paths)[:_COMMENT_PATH_LIMIT]
        lines += ["", "Paths that made it ineligible:"]
        lines += [f"- `{path}`" for path in shown]
        if len(offending_paths) > len(shown):
            lines.append(f"- … and {len(offending_paths) - len(shown)} more")
    lines += [
        "",
        "The run now requires an LLM review and will proceed to it. No "
        "certification was recorded.",
    ]
    return "\n".join(lines)


async def sync_upgrade(
    client: Tracker,
    ticket: str,
    *,
    run_id: str,
    reason: str,
    offending_paths: Sequence[str],
    classifier_version: int,
) -> None:
    """Replace the assurance label and comment the reason.

    Raises :class:`UpgradeSyncError` naming the artifact that did not land. The
    label pair is one artifact on purpose: a removed-but-not-applied label leaves
    the issue with *no* stated level, which resolves to ``simple`` — the same
    place the upgrade was heading — so telling the two halves apart would buy a
    reader nothing.
    """
    try:
        await client.remove_label(ticket, TRIVIAL_LABEL)
        await client.apply_label(ticket, UPGRADED_LABEL)
    except (TrackerNotFound, TrackerRequestError, TrackerConfigError) as exc:
        raise UpgradeSyncError(LABEL_ARTIFACT, str(exc)) from exc

    body = upgrade_comment(
        run_id=run_id,
        reason=reason,
        offending_paths=offending_paths,
        classifier_version=classifier_version,
    )
    try:
        await client.post_comment(ticket, body)
    except (TrackerNotFound, TrackerRequestError, TrackerConfigError) as exc:
        raise UpgradeSyncError(COMMENT_ARTIFACT, str(exc)) from exc
