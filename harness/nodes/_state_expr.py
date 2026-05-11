"""Sandboxed AST evaluator over ``state`` — shared between CheckNode and Loop.

Extracted from :mod:`harness.nodes.check` as part of H-021 so the loop
evaluator (:mod:`harness.engine.loop`) can reuse the same allow-list
without duplicating the AST plumbing.

Two public seams:

* :func:`parse_and_eval` — parse ``expr`` and evaluate against ``state``.
  Returns the raw Python value (any type). Used by the loop evaluator,
  which then coerces with :func:`bool`.
* :func:`evaluate_bool_strict` — evaluates and *requires* the result to
  be a ``bool``. Used by :class:`harness.nodes.check.CheckNode` to keep
  its "no truthiness coercion" guarantee (SPEC §4.3 / §5).

Allow-list, mirrored from the pre-refactor CheckNode:

* :class:`ast.Constant`
* :class:`ast.Name` — restricted to the single name ``state``
* :class:`ast.Attribute` — ``state.foo.bar``, dunders and ``_private``
  rejected
* :class:`ast.UnaryOp` — only ``not``
* :class:`ast.BoolOp` — ``and`` / ``or``
* :class:`ast.Compare` — ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``,
  ``in``, ``not in``, ``is``, ``is not``
* :class:`ast.List` / :class:`ast.Tuple` — constants only

Everything else (function calls, subscripts, lambdas, comprehensions,
f-strings, dict/set literals, walrus, etc.) raises
:class:`StateExpressionError`.

The exception is a renamed alias of CheckNode's historical
``CheckNodeError`` — same identity at runtime so existing
``except CheckNodeError`` callers keep working. See the alias note in
:mod:`harness.nodes.check`.
"""

from __future__ import annotations

import ast
from typing import Any, Final

from harness.state.schema import BaseState

__all__ = [
    "StateExpressionError",
    "evaluate_bool_strict",
    "parse_and_eval",
]


class StateExpressionError(RuntimeError):  # noqa: N818 — engine vocabulary
    """Raised when a state expression fails to parse or evaluate.

    The historic :class:`harness.nodes.check.CheckNodeError` is re-exported
    as an alias of this class so existing ``except CheckNodeError`` blocks
    keep catching the same instances.
    """


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


def parse_and_eval(expr: str, *, state: BaseState) -> Any:
    """Parse ``expr`` and evaluate it against ``state``. Returns the raw value.

    The caller decides whether to coerce to bool (loop) or to require a
    bool (check). All errors surface as :class:`StateExpressionError`.
    """
    tree = _parse(expr)
    return _eval(tree.body, state=state, expr=expr)


def evaluate_bool_strict(expr: str, *, state: BaseState) -> bool:
    """Parse + evaluate ``expr`` and require the result to be a ``bool``.

    Used by :class:`harness.nodes.check.CheckNode` — SPEC §4.3 / §5 say
    a check's expression must evaluate to a boolean. Truthiness coercion
    would silently paper over author bugs (an empty string evaluating
    falsy looks just like a deliberate ``False``), so we reject it here.
    """
    result = parse_and_eval(expr, state=state)
    if not isinstance(result, bool):
        raise StateExpressionError(
            f"expression did not evaluate to bool: got {type(result).__name__} "
            f"(expr: {expr!r})"
        )
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _parse(expr: str) -> ast.Expression:
    """Parse ``expr`` with ``mode='eval'`` and return the Expression root."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise StateExpressionError(
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
            raise StateExpressionError(
                f"disallowed expression: only the 'state' name is permitted, "
                f"got {node.id!r} (expr: {expr!r})"
            )
        return state

    if isinstance(node, ast.Attribute):
        return _eval_attribute(node, state=state, expr=expr)

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.Not):
            raise StateExpressionError(
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

    raise StateExpressionError(
        f"disallowed expression: {type(node).__name__} "
        f"is not on the state-expression allow-list (expr: {expr!r})"
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
    * Missing attributes raise StateExpressionError (rather than the bare
      AttributeError we'd otherwise pass through) so the workflow author
      sees a message naming the field.
    """
    if node.attr.startswith("_"):
        raise StateExpressionError(
            f"disallowed attribute access: {node.attr!r} "
            f"(dunder / private attributes rejected) (expr: {expr!r})"
        )
    target = _eval(node.value, state=state, expr=expr)
    try:
        return getattr(target, node.attr)
    except AttributeError as e:
        raise StateExpressionError(
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
    raise StateExpressionError(
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
            raise StateExpressionError(
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
        raise StateExpressionError(
            f"disallowed expression: list/tuple literals may only contain "
            f"constants, got {type(node).__name__} (expr: {expr!r})"
        )
    return node.value
