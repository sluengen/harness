"""Promotion escalation content — the non-success terminal path's evidence (CAL-1118).

``harness promote escalate`` (:mod:`harness.cli.promote`) is the audited terminal
path when a promotion exceeds local repair authority — a semantic conflict, a red
gate, or an infrastructure block that a bounded local repair cannot clear
(proposal ``local-promotion-steward``, breakdown item 7). This module is its
**content half**, the analogue of :func:`harness.promotion_pr.build_pr_body` for
the escalate step: it renders the deterministic Linear ticket title/body from a
:class:`~harness.state.promotions.Promotion` plus the live conflict files, so the
escalation a human (or premium-model session) picks up carries the promotion id,
endpoints, branch/worktree to inspect, conflict files, gate summary, and the next
human action.

Pure functions only — no Linear I/O (that is :class:`~harness.linear.LinearClient`),
no ledger, no Typer. The CLI orchestrates: it gathers the live conflict files,
calls these builders, and drives the create-or-comment decision.
"""

from __future__ import annotations

from collections.abc import Sequence

from harness.state.promotions import Promotion

__all__ = [
    "build_escalation_body",
    "build_escalation_title",
    "escalation_next_action",
]

#: The next human action keyed on the promotion's blocking status. Deterministic
#: so the escalation always names a concrete step rather than "look into it".
_NEXT_ACTION: dict[str, str] = {
    "needs_ticket": (
        "Resolve the merge conflict or gate failure on the promotion branch, then "
        "re-run the promotion (a fresh `harness promote start`)."
    ),
    "blocked": (
        "The gate could not run — an infrastructure block, not a code decision. "
        "Investigate the environment (toolchain, credentials), then re-run "
        "`harness promote start`."
    ),
    "agent_may_fix": (
        "Resolve the conflicted files in the promotion worktree, `git add` them, "
        "and resume with `harness promote continue`."
    ),
}

#: Fallback next action for any status without a specific instruction.
_DEFAULT_NEXT_ACTION = (
    "Inspect the promotion worktree and decide the next step by hand."
)


def escalation_next_action(status: str) -> str:
    """The next human action for a promotion blocked in ``status``."""
    return _NEXT_ACTION.get(status, _DEFAULT_NEXT_ACTION)


def build_escalation_title(promotion: Promotion) -> str:
    """The deterministic escalation ticket title — status + both endpoints."""
    return (
        f"Promotion blocked ({promotion.status}): "
        f"{promotion.from_branch} → {promotion.to_branch}"
    )


def build_escalation_body(
    promotion: Promotion, *, conflict_files: Sequence[str]
) -> str:
    """Render the escalation ticket body from ``promotion`` + the live conflicts.

    A deterministic Markdown summary carrying everything the escalation proposal
    requires: the promotion id, its status and endpoints, the branch/worktree to
    inspect, the conflict files, the captured gate evidence, and the next human
    action. Every section degrades to an explicit ``_none_`` rather than
    vanishing, so the body's shape is stable however sparse the promotion is.
    """
    lines = [
        "## Promotion escalation",
        "",
        "A promotion exceeded local repair authority and needs a human or "
        "premium-model session.",
        "",
        f"- Promotion id: `{promotion.promotion_id}`",
        f"- Status: `{promotion.status}`",
        f"- Source → target: `{promotion.from_branch}` → `{promotion.to_branch}`",
        f"- Promotion branch: {_code_or_none(promotion.promotion_branch)}",
        f"- Worktree: {_code_or_none(promotion.worktree_path)}",
        "",
        f"### Conflict files ({len(conflict_files)})",
        "",
        *_bullet_section(conflict_files),
        "",
        "### Gate summary",
        "",
        f"```\n{promotion.evidence}\n```"
        if promotion.evidence
        else "_no gate evidence recorded_",
        "",
        "### Next action",
        "",
        escalation_next_action(promotion.status),
    ]
    return "\n".join(lines) + "\n"


def _code_or_none(value: str | None) -> str:
    """``value`` in code ticks, or an explicit ``_none_`` when absent."""
    return f"`{value}`" if value else "_none_"


def _bullet_section(items: Sequence[str]) -> list[str]:
    """A Markdown bullet list, or a single ``_none_`` line when empty."""
    if not items:
        return ["_none_"]
    return [f"- `{item}`" for item in items]
