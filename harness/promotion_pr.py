"""Promotion PR publication — push the gated branch and open the PR (CAL-1117).

``harness promote pr`` (:mod:`harness.cli.promote`) is the audited finalizer for a
gate-green promotion; this module is its **publication mechanics**, the analogue
of :mod:`harness.promotion_gate` (the gate executor) for the publish step. Where
:mod:`harness.promotion` stays git-*merge*-only, this owns the two release
side-effects the ADR reserves for ``promote pr`` (ADR 0003, "PR authority"):

* :func:`push_promotion_branch` — publish **only** the promotion branch to
  ``origin`` via an explicit ``<branch>:<branch>`` refspec. Never a bare
  ``git push`` (which could advance a tracking branch) and never a target branch.
  This is the **release hop's** publication: ``staging → main`` is PR-only.
* :func:`push_target_branch` — the **staging hop's** publication: advance the
  target branch itself to the gated SHA. Scoped to :data:`DIRECT_PUSH_TARGET`
  (``staging``) by a structural guard, so ``main`` is unreachable by direct push
  from this module however it is called (ADR 0003 as amended 2026-07-17: staging
  is *derived*, main is *decided*).
* :func:`collect_promotion_facts` — read the deterministic facts of the promotion
  from git: the commit range ``origin/<to>..<gated_sha>``, the Linear IDs in those
  commit subjects, and the changed ``specs/`` paths.
* :func:`build_pr_title` / :func:`build_pr_body` — render the PR prose from those
  facts plus the gate evidence, so the summary is reproducible from state rather
  than authored ad hoc.
* :func:`create_pull_request` — open the PR into the target branch through the
  ``gh`` CLI (harness-owned, not orchestrator-owned) and return its URL.

This module is git + ``gh`` only: no ledger, no Typer. A failed push or ``gh``
call raises :class:`~harness.promotion.PromotionMechanicsError` with a stable
``reason`` (``push_failed`` / ``pr_create_failed``), so the CLI surfaces it as a
structured refusal an orchestrator branches on — never a raw traceback.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from harness import promotion as _mechanics
from harness._git import NETWORK_GIT_TIMEOUT_SECONDS, run_git

# NB: the *module* import above (not ``from harness.promotion import
# PromotionMechanicsError``) reads its attribute only **inside** the functions
# below — never at module top — exactly as ``harness.cli.promote`` does.
#
# This used to be load-bearing against an import cycle: ``harness.promotion``
# imported ``harness.cli._git``, whose package ``harness.cli`` imports
# ``harness.cli.promote``, which imports this module — so when this module was
# pulled in first, ``harness.promotion`` was still partially initialised and
# ``PromotionMechanicsError`` not yet bound. #269 removed that cycle at its root
# by re-homing the git helpers to the ``harness._git`` leaf, so the lazy read is
# now inert: a top-level name import would work. It stays because it is correct
# and churn-free to leave, not because anything depends on it.

__all__ = [
    "DIRECT_PUSH_TARGET",
    "PromotionFacts",
    "PullRequestOutcome",
    "build_pr_body",
    "build_pr_title",
    "collect_promotion_facts",
    "create_pull_request",
    "push_promotion_branch",
    "push_target_branch",
]

#: The **only** target branch a promotion may advance by a direct push — the
#: staging hop (``CONTEXT.md`` ``branches.staging``). ADR 0003 originally forbade
#: direct target pushes on both hops; the 2026-07-17 amendment scopes that rule to
#: the *release* hop, because **staging is derived and main is decided**: nothing
#: is judged at the staging hop (the gate *is* the decision), while ``main``
#: remains the single human decision point.
#:
#: This constant is the structural guard's whole allowlist, and ``main``'s absence
#: from it is what makes a direct release push unreachable. It is a literal rather
#: than a ``CONTEXT.md`` read for the same reason the rest of the branch model
#: still is (``start.py`` / ``worktrees.py`` hardcode ``dev``/``main``/``master``);
#: reading the model from config is CAL-1106.
DIRECT_PUSH_TARGET = "staging"


def _publish_error(message: str, *, reason: str) -> _mechanics.PromotionMechanicsError:
    """Build a :class:`~harness.promotion.PromotionMechanicsError` with ``reason``.

    A tiny helper so the raise sites read cleanly and the (cycle-sensitive) lazy
    attribute lookup lives in one place.
    """
    return _mechanics.PromotionMechanicsError(message, reason=reason)

#: A Linear-style issue identifier (``CAL-1234``) as it appears in a commit
#: subject. Two-or-more uppercase letters, a hyphen, and digits, bounded so it
#: does not match a substring of a larger token.
_LINEAR_ID = re.compile(r"\b[A-Z]{2,}-\d+\b")

#: The path prefix that marks a changed *spec* — the promotion PR surfaces which
#: specs move so a reviewer sees the contract delta at a glance (ADR 0003).
_SPEC_PREFIX = "specs/"

#: Ceiling (seconds) for the ``gh pr create`` call — a network op like the git
#: pushes, bounded against a hung GitHub API by the same documented band.
_GH_TIMEOUT_SECONDS = NETWORK_GIT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class PromotionFacts:
    """The deterministic facts a promotion PR is written from (ADR 0003).

    Everything here is *read from git*, never authored: the branch endpoints, the
    ``gated_sha`` (the reviewed merge HEAD), the feature ``commit_subjects`` in the
    promoted range, the ``linear_ids`` mentioned in them, and the changed
    ``changed_specs``. The gate evidence is passed separately to
    :func:`build_pr_body` because it lives on the promotion row, not in git.
    """

    from_branch: str
    to_branch: str
    gated_sha: str
    commit_subjects: tuple[str, ...]
    linear_ids: tuple[str, ...]
    changed_specs: tuple[str, ...]


@dataclass(frozen=True)
class PullRequestOutcome:
    """The result of opening the promotion PR — the URL ``gh`` reports."""

    url: str


def push_promotion_branch(repo_root: Path, branch: str) -> None:
    """Push **only** ``branch`` to ``origin`` (never a target branch).

    Uses an explicit ``<branch>:<branch>`` refspec so exactly one ref moves — a
    bare ``git push`` could advance a configured tracking branch, and the ADR
    forbids any direct push to ``staging`` / ``main``. Idempotent: re-pushing an
    already-published branch at the same SHA is a no-op. Raises
    :class:`~harness.promotion.PromotionMechanicsError` (``reason='push_failed'``)
    on a non-zero push or a fired network timeout.
    """
    refspec = f"{branch}:{branch}"
    try:
        result = run_git(
            repo_root, "push", "origin", refspec, timeout=NETWORK_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise _publish_error(
            f"git push origin {refspec} exceeded the {NETWORK_GIT_TIMEOUT_SECONDS}s "
            "network timeout; the remote may be unreachable",
            reason="push_failed",
        ) from exc
    if result.returncode != 0:
        raise _publish_error(
            f"git push origin {refspec} failed: {result.stderr.strip()}",
            reason="push_failed",
        )


def push_target_branch(repo_root: Path, *, target: str, gated_sha: str) -> None:
    """Advance ``target`` on ``origin`` to ``gated_sha`` — the **staging hop only**.

    The publication half of an automatic ``dev → staging`` promotion: the gated
    candidate becomes ``staging`` itself, with no PR, so the nightly promotion
    completes without a human (ADR 0003 as amended 2026-07-17).

    ``target`` must be :data:`DIRECT_PUSH_TARGET`. Any other branch — ``main`` above
    all — raises ``PromotionMechanicsError`` (``reason='direct_push_refused'``)
    **before any git runs**. The guard is deliberately here rather than in the
    caller: "the release hop opens a PR" must be a property of the code, not a
    convention an orchestrator (or a future caller) can quietly break.

    The refspec is an explicit ``<gated_sha>:refs/heads/<target>``: exactly one ref
    moves, it is named in full (no bare ``git push``, no tracking-branch surprise),
    and the pushed commit is precisely the one the gate covered rather than
    whatever a branch tip has since become. Git's default non-fast-forward refusal
    still applies, so a ``target`` that moved under us fails loudly as
    ``push_failed`` (→ escalation) instead of clobbering it.
    """
    if target != DIRECT_PUSH_TARGET:
        raise _publish_error(
            f"refusing a direct push to {target!r}: only {DIRECT_PUSH_TARGET!r} may "
            "be advanced directly — the release hop opens a pull request",
            reason="direct_push_refused",
        )
    refspec = f"{gated_sha}:refs/heads/{target}"
    try:
        result = run_git(
            repo_root, "push", "origin", refspec, timeout=NETWORK_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise _publish_error(
            f"git push origin {refspec} exceeded the {NETWORK_GIT_TIMEOUT_SECONDS}s "
            "network timeout; the remote may be unreachable",
            reason="push_failed",
        ) from exc
    if result.returncode != 0:
        raise _publish_error(
            f"git push origin {refspec} failed: {result.stderr.strip()}",
            reason="push_failed",
        )


def collect_promotion_facts(
    repo_root: Path, *, from_branch: str, to_branch: str, gated_sha: str
) -> PromotionFacts:
    """Read the deterministic PR facts from the promoted commit range.

    The promoted range is ``origin/<to_branch>..<gated_sha>`` — the commits present
    in the gated merge but not yet on the target. From it: the non-merge commit
    subjects, the sorted-unique Linear IDs mentioned in them, and the changed
    ``specs/`` paths (``git diff --name-only origin/<to>..<gated_sha>``). Best-effort
    reads — an unresolvable range yields empty lists rather than raising, so a PR
    with no discernible feature commits still opens with a valid (if sparse) body.
    """
    rng = f"origin/{to_branch}..{gated_sha}"
    subjects = _commit_subjects(repo_root, rng)
    changed = _changed_paths(repo_root, rng)
    changed_specs = tuple(p for p in changed if p.startswith(_SPEC_PREFIX))
    return PromotionFacts(
        from_branch=from_branch,
        to_branch=to_branch,
        gated_sha=gated_sha,
        commit_subjects=subjects,
        linear_ids=_extract_linear_ids(subjects),
        changed_specs=changed_specs,
    )


def _commit_subjects(repo_root: Path, rng: str) -> tuple[str, ...]:
    """The non-merge commit subjects in ``rng``, newest first; empty on failure."""
    result = run_git(repo_root, "log", "--no-merges", "--format=%s", rng)
    if result.returncode != 0:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line.strip())


def _changed_paths(repo_root: Path, rng: str) -> tuple[str, ...]:
    """The files changed across ``rng``, sorted; empty on failure."""
    result = run_git(repo_root, "diff", "--name-only", rng)
    if result.returncode != 0:
        return ()
    return tuple(sorted(line for line in result.stdout.splitlines() if line.strip()))


def _extract_linear_ids(subjects: Sequence[str]) -> tuple[str, ...]:
    """The sorted, de-duplicated Linear IDs mentioned across ``subjects``."""
    ids: set[str] = set()
    for subject in subjects:
        ids.update(_LINEAR_ID.findall(subject))
    return tuple(sorted(ids))


def build_pr_title(facts: PromotionFacts) -> str:
    """The deterministic PR title — names both promotion endpoints."""
    return f"Promote {facts.from_branch} → {facts.to_branch}"


def build_pr_body(facts: PromotionFacts, *, evidence: str | None) -> str:
    """Render the PR body from ``facts`` + the gate ``evidence`` (AC-4).

    A deterministic Markdown summary: the endpoints and gated SHA, the promoted
    commit subjects, the Linear IDs, the changed specs, and the captured gate
    evidence. Every section degrades to an explicit "_none_" rather than vanishing,
    so the body's shape is stable regardless of how sparse the promotion is.
    """
    lines = [
        f"## Promotion: `{facts.from_branch}` → `{facts.to_branch}`",
        "",
        f"Gated SHA: `{facts.gated_sha}`",
        "",
        "Generated by `harness promote pr` from deterministic facts "
        "(commit range, Linear IDs, changed specs, gate evidence).",
        "",
        f"### Commits ({len(facts.commit_subjects)})",
        "",
        *_bullet_section(facts.commit_subjects),
        "",
        "### Linear issues",
        "",
        *_bullet_section(facts.linear_ids),
        "",
        "### Changed specs",
        "",
        *_bullet_section(facts.changed_specs),
        "",
        "### Gate evidence",
        "",
        f"```\n{evidence}\n```" if evidence else "_no gate evidence recorded_",
    ]
    return "\n".join(lines) + "\n"


def _bullet_section(items: Sequence[str]) -> list[str]:
    """A Markdown bullet list, or a single ``_none_`` line when empty."""
    if not items:
        return ["_none_"]
    return [f"- {item}" for item in items]


def create_pull_request(
    repo_root: Path, *, base: str, head: str, title: str, body: str
) -> PullRequestOutcome:
    """Open the promotion PR through ``gh`` and return its URL (AC-3).

    Shells out to ``gh pr create --base <base> --head <head> --title … --body …``
    in ``repo_root`` — PR creation is harness-owned, not orchestrator-owned (ADR
    0003). ``gh`` prints the new PR's URL to stdout, which is returned. Any failure
    — a non-zero ``gh`` exit or ``gh`` not being installed — raises
    :class:`~harness.promotion.PromotionMechanicsError` (``reason='pr_create_failed'``)
    so the CLI reports it structurally.
    """
    argv = [
        "gh",
        "pr",
        "create",
        "--base",
        base,
        "--head",
        head,
        "--title",
        title,
        "--body",
        body,
    ]
    try:
        result = subprocess.run(  # noqa: S603
            argv,
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=_GH_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise _publish_error(
            f"gh pr create failed to run ({exc}); is the GitHub CLI installed and "
            "authenticated?",
            reason="pr_create_failed",
        ) from exc
    if result.returncode != 0:
        raise _publish_error(
            f"gh pr create failed: {result.stderr.strip()}",
            reason="pr_create_failed",
        )
    return PullRequestOutcome(url=result.stdout.strip())
