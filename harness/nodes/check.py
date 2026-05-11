"""Check node — sandboxed boolean expression over state — see SPEC §4.3, §5.

The check node is the *one* place in the engine where deterministic gating
lives. SPEC §4.3 makes it explicit: control flow may read from ``state`` and
from ``check`` node results; it may NOT read from ``attestation``. Routing on
this node's outcome is therefore engine-load-bearing, and the node has to be
a small, careful thing.

Two responsibilities:

1. **Evaluate** ``step.expr`` as a boolean expression over ``state``. The
   evaluator is shared with the loop block (:mod:`harness.engine.loop`)
   and lives in :mod:`harness.nodes._state_expr` — see that module for
   the AST allow-list. Truthiness coercion is rejected here (CheckNode's
   guarantee per SPEC §4.3 / §5), even though the same evaluator powers
   the loop's ``until:`` evaluation where bool coercion *is* applied.
2. **Echo** ``step.on_fail`` into the contract so the executor (H-007) can
   route on the documented vocabulary (``cancel | continue |
   retry_loop:<id>``). The CheckNode does not itself cancel runs or
   trigger loops — it just reports. The format is validated here so a
   typo in the YAML surfaces at the check rather than the executor.

Failure modes — all raise :class:`CheckNodeError`:

* ``expr`` is syntactically invalid Python.
* ``expr`` uses a disallowed AST node (function call, subscript, lambda,
  comprehension, f-string, dict/set literal, walrus, etc.).
* ``expr`` accesses a non-``state`` name (``os.getcwd()`` etc.) or a
  dunder-prefixed attribute (``state.__class__``).
* ``expr`` references a state attribute that doesn't exist on the
  supplied state instance.
* The top-level expression result is not a ``bool``. Truthiness coercion
  is rejected because it would silently paper over author bugs (an empty
  string evaluating ``False`` looks just like a deliberate ``False``).
* ``step.on_fail`` is not one of ``cancel`` / ``continue`` /
  ``retry_loop:<non-empty-id>``.

A ``passed=False`` result is *not* an exception — it is a successful
evaluation whose outcome is "the expression was False". The executor
reads ``passed`` plus ``on_fail`` and decides what to do next. This
distinction is the easy thing to get backwards (cf. ScriptNode, where
non-zero exit *does* raise), so it's restated in the
:meth:`CheckNode.execute` docstring too.

SPEC: §4.3 (Node protocol), §4.5 / §5 (check vs decision), §5 step keys
(``expr``, ``on_fail``), §10 (cancellation / sequencing).
"""

from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from harness.nodes._state_expr import StateExpressionError, evaluate_bool_strict
from harness.nodes.base import Attestation, NodeResult
from harness.state.schema import BaseState
from harness.workflow.schema import CheckStep

__all__ = ["CheckNode", "CheckNodeError", "CheckOutput"]


# Historic alias — pre-H-021 callers raised and caught
# :class:`CheckNodeError`. The class moved into a shared module under a
# more descriptive name; we keep the original symbol as an alias so
# ``except CheckNodeError`` keeps working at every call site.
CheckNodeError = StateExpressionError


# ---------------------------------------------------------------------------
# on_fail vocabulary
# ---------------------------------------------------------------------------

# SPEC §5: ``on_fail: cancel | continue | retry_loop:<id>``. The schema's
# ``on_fail: str = "cancel"`` is intentionally permissive (it doesn't
# enforce the value), so the validation lives here. ``<id>`` is a step
# id and the workflow-schema constraint on ids is the same shape we
# accept here: starts with a letter, then letters / digits / underscore
# / hyphen.
_ON_FAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"^(cancel|continue|retry_loop:[A-Za-z][A-Za-z0-9_-]*)$"
)


class CheckOutput(BaseModel):
    """Contract for a check step.

    The executor reads ``passed`` for routing and ``on_fail`` for the
    action to take when ``passed is False``. ``expr`` is echoed verbatim
    so the event log records exactly what was evaluated (useful when
    the YAML is templated).
    """

    model_config = ConfigDict(extra="forbid")

    passed: bool
    expr: str
    on_fail: str


class CheckNode:
    """v1 check node: parse → walk AST → evaluate → return.

    Conforms structurally to :class:`harness.nodes.base.Node`. Stateless;
    one instance is reused across every check step in a run.

    Note: ``passed=False`` is a *successful* return, not an exception. The
    executor (H-007) reads ``passed`` together with ``on_fail`` to decide
    routing; raising would lose that information. CheckNodeError is
    reserved for evaluator failures (parse error, disallowed AST node,
    missing attribute, non-bool result, malformed ``on_fail``).
    """

    type: Literal["check"] = "check"

    async def execute(
        self,
        *,
        step: CheckStep,
        state: BaseState,
    ) -> NodeResult[CheckOutput]:
        """Parse and evaluate ``step.expr`` against ``state``.

        Raises:
            CheckNodeError: on syntax error, disallowed AST node, missing
                state attribute, non-bool result, or malformed
                ``step.on_fail``.
        """
        # Validate on_fail first — a malformed routing string makes the
        # whole step useless; surface it before paying the parse cost.
        _validate_on_fail(step.on_fail)

        result = evaluate_bool_strict(step.expr, state=state)

        return NodeResult(
            contract=CheckOutput(
                passed=result,
                expr=step.expr,
                on_fail=step.on_fail,
            ),
            attestation=Attestation(
                status="complete",
                reasoning=f"check {step.id!r} evaluated to {result}",
            ),
        )


# ---------------------------------------------------------------------------
# Internals — on_fail validation
# ---------------------------------------------------------------------------


def _validate_on_fail(on_fail: str) -> None:
    """Reject anything outside the SPEC §5 vocabulary."""
    if not _ON_FAIL_RE.fullmatch(on_fail):
        raise CheckNodeError(
            f"malformed on_fail {on_fail!r}: must be one of "
            f"'cancel', 'continue', or 'retry_loop:<id>'"
        )
