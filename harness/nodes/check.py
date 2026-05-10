"""Check node — sandboxed boolean expression over state — see SPEC §4.3, §5.

The check node is the *one* place in the engine where deterministic gating
lives. SPEC §4.3 makes it explicit: control flow may read from ``state`` and
from ``check`` node results; it may NOT read from ``attestation``. Routing on
this node's outcome is therefore engine-load-bearing, and the node has to be
a small, careful thing.

Two responsibilities:

1. **Evaluate** ``step.expr`` as a boolean expression over ``state``. The
   evaluator is an AST-walking subset of Python — no ``eval``, no ``exec``,
   no ``compile``-and-run. Allowed AST node types are intentionally tiny
   (constants, comparisons, boolean composition, attribute walks rooted
   at ``state``, list/tuple literals of constants). Anything else is a
   :class:`CheckNodeError` at evaluation time. Dunder-named attributes
   are rejected even on ``state`` so the sandbox can't be tunnelled
   through ``state.__class__.__mro__`` and friends.
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

import ast
import re
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from harness.nodes.base import Attestation, NodeResult
from harness.state.schema import BaseState
from harness.workflow.schema import CheckStep

__all__ = ["CheckNode", "CheckNodeError", "CheckOutput"]


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


# ---------------------------------------------------------------------------
# AST allow-list
# ---------------------------------------------------------------------------

# Comparison operator AST nodes → their Python semantics. ``ast.cmpop`` is
# an abstract type so we list the concrete subclasses we accept.
_CMP_OPS: Final[dict[type[ast.cmpop], Any]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}


class CheckNodeError(RuntimeError):  # noqa: N818 — spec vocabulary, not PEP-8 N818
    """Raised when an ``expr`` fails to evaluate or ``on_fail`` is malformed.

    This is reserved for *evaluator failures* — the expression couldn't be
    parsed, used a disallowed construct, referenced a missing attribute,
    or didn't return a bool. A bool result of ``False`` is a successful
    evaluation, not a CheckNodeError; see :class:`CheckOutput`.
    """


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

        tree = _parse(step.expr)
        result = _eval(tree.body, state=state, expr=step.expr)

        if not isinstance(result, bool):
            raise CheckNodeError(
                f"expression did not evaluate to bool: got {type(result).__name__} "
                f"(expr: {step.expr!r})"
            )

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
# Internals — parse + walk
# ---------------------------------------------------------------------------


def _validate_on_fail(on_fail: str) -> None:
    """Reject anything outside the SPEC §5 vocabulary."""
    if not _ON_FAIL_RE.match(on_fail):
        raise CheckNodeError(
            f"malformed on_fail {on_fail!r}: must be one of "
            f"'cancel', 'continue', or 'retry_loop:<id>'"
        )


def _parse(expr: str) -> ast.Expression:
    """Parse ``expr`` with ``mode='eval'`` and return the Expression root."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CheckNodeError(
            f"could not parse expression {expr!r}: {e.msg}"
        ) from e
    # ``mode="eval"`` always returns ast.Expression — assert for mypy/runtime.
    assert isinstance(tree, ast.Expression)
    return tree


def _eval(node: ast.AST, *, state: BaseState, expr: str) -> Any:
    """Walk ``node`` and return its evaluated value.

    The dispatch is a small ``isinstance`` ladder rather than a
    ``NodeVisitor`` so the allow-list is right here in one place — adding
    a new AST node type means adding a branch and a test, not subclassing.
    """
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id != "state":
            raise CheckNodeError(
                f"disallowed expression: only the 'state' name is permitted, "
                f"got {node.id!r} (expr: {expr!r})"
            )
        return state

    if isinstance(node, ast.Attribute):
        return _eval_attribute(node, state=state, expr=expr)

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            raise CheckNodeError(
                f"disallowed expression: UnaryOp {type(node.op).__name__} "
                f"(only 'not' is supported) (expr: {expr!r})"
            )
        return not _eval(node.operand, state=state, expr=expr)

    if isinstance(node, ast.BoolOp):
        return _eval_boolop(node, state=state, expr=expr)

    if isinstance(node, ast.Compare):
        return _eval_compare(node, state=state, expr=expr)

    if isinstance(node, (ast.List, ast.Tuple)):
        # Container literal — only constants inside, by design. We don't
        # want ``state.x in [state.y, "z"]`` to be a quiet sandbox surface;
        # the SPEC use-case is ``state.x in ["bug", "feature"]``.
        return [_eval_constant(elt, expr=expr) for elt in node.elts]

    raise CheckNodeError(
        f"disallowed expression: {type(node).__name__} "
        f"is not on the check-node allow-list (expr: {expr!r})"
    )


def _eval_attribute(
    node: ast.Attribute,
    *,
    state: BaseState,
    expr: str,
) -> Any:
    """Walk ``state.foo.bar`` by chained ``getattr``.

    Two hardenings beyond the obvious:

    * dunder names (``__class__``, ``__mro__``, …) are rejected so the
      sandbox can't be tunnelled through Python's introspection
      machinery. ``_private`` names are also rejected because they're
      not part of the public state contract.
    * Missing attributes raise CheckNodeError (rather than the bare
      AttributeError we'd otherwise pass through) so the workflow author
      sees a message naming the field.
    """
    if node.attr.startswith("_"):
        raise CheckNodeError(
            f"disallowed attribute access: {node.attr!r} "
            f"(dunder / private attributes rejected) (expr: {expr!r})"
        )
    target = _eval(node.value, state=state, expr=expr)
    try:
        return getattr(target, node.attr)
    except AttributeError as e:
        raise CheckNodeError(
            f"state has no attribute {node.attr!r} (expr: {expr!r})"
        ) from e


def _eval_boolop(
    node: ast.BoolOp,
    *,
    state: BaseState,
    expr: str,
) -> bool:
    """Evaluate ``and`` / ``or`` with Python short-circuit semantics."""
    if isinstance(node.op, ast.And):
        for v in node.values:
            r = _eval(v, state=state, expr=expr)
            if not r:
                return bool(r)
        # All truthy — return the last one's bool. Python returns the
        # last operand for and/or but we coerce to bool to keep the
        # top-level result type honest; the outer non-bool guard does
        # not see this layer.
        return bool(r)
    if isinstance(node.op, ast.Or):
        for v in node.values:
            r = _eval(v, state=state, expr=expr)
            if r:
                return bool(r)
        return bool(r)
    # Defensive — ast.boolop has only And / Or, but stay strict.
    raise CheckNodeError(
        f"disallowed expression: BoolOp {type(node.op).__name__} (expr: {expr!r})"
    )


def _eval_compare(
    node: ast.Compare,
    *,
    state: BaseState,
    expr: str,
) -> bool:
    """Evaluate ``a OP b [OP c …]`` with Python chaining semantics."""
    left = _eval(node.left, state=state, expr=expr)
    for op, right_node in zip(node.ops, node.comparators, strict=True):
        right = _eval(right_node, state=state, expr=expr)
        op_fn = _CMP_OPS.get(type(op))
        if op_fn is None:
            raise CheckNodeError(
                f"disallowed comparison operator: {type(op).__name__} "
                f"(expr: {expr!r})"
            )
        if not op_fn(left, right):
            return False
        left = right
    return True


def _eval_constant(node: ast.AST, *, expr: str) -> Any:
    """Reject anything other than ``ast.Constant`` inside a list/tuple literal.

    The SPEC use-case is ``state.x in ["bug", "feature"]`` — a
    container of literal options. Allowing ``state.x in [state.y]``
    silently extends the allow-list and isn't justified by any current
    workflow.
    """
    if not isinstance(node, ast.Constant):
        raise CheckNodeError(
            f"disallowed expression: list/tuple literals may only contain "
            f"constants, got {type(node).__name__} (expr: {expr!r})"
        )
    return node.value
