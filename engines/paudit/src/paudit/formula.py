"""Whitelisted arithmetic expressions over item ids (pack `summaries[].expr`).

Public API (stable, reused by SP03): `evaluate`, `check`, `names`, `label_for`, `FormulaError`.
No `eval`: the tree is walked by a whitelist evaluator.
"""

import ast
import operator
from collections.abc import Mapping
from typing import Literal

_BIN = (ast.Add, ast.Sub, ast.Mult, ast.Div)
_UNARY = (ast.UAdd, ast.USub)
_OK = (ast.Expression, ast.Load, ast.BinOp, ast.UnaryOp, ast.Name, *_BIN, *_UNARY)


class FormulaError(ValueError):
    """The expression is not plain arithmetic over names and numbers."""


def parse(expr: str) -> ast.Expression:
    """Parse `expr`; allow only + - * / unary +/-, numbers, parentheses and bare names."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"not parseable: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, _OK):
            continue
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            continue
        raise FormulaError(f"disallowed element: {type(node).__name__}")
    return tree


def names(expr: str) -> set[str]:
    """Item ids referenced by `expr` (raises FormulaError if it is not plain arithmetic)."""
    return {n.id for n in ast.walk(parse(expr)) if isinstance(n, ast.Name)}


def check(expr: str) -> set[str]:
    """Parse-time check used by the pack loader: raises FormulaError, returns referenced ids."""
    return names(expr)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv}


def evaluate(expr: str, values: Mapping[str, float | int | None]) -> float | None:
    """Evaluate `expr` over `values`. Returns None on division by zero or when a referenced
    id is absent from `values` or its value is None. Raises FormulaError if `expr` is not
    plain arithmetic (so a bad formula is never silently null)."""
    tree = parse(expr)

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            v = values.get(node.id)
            if v is None:
                raise _Null
            return float(v)
        if isinstance(node, ast.UnaryOp):
            x = ev(node.operand)
            return -x if isinstance(node.op, ast.USub) else x
        if isinstance(node, ast.BinOp):
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        raise FormulaError(f"disallowed element: {type(node).__name__}")  # unreachable

    try:
        return ev(tree)
    except (_Null, ZeroDivisionError):
        return None


class _Null(Exception):
    """Internal: a referenced value is missing."""


def label_for(value: float | None, reference: Mapping[str, object] | None
              ) -> Literal["below_fair", "fair", "good"] | None:
    """Label `value` against a reference level `{fair, good, direction?}`.

    higher_better (default): >= good -> good, >= fair -> fair, else below_fair.
    lower_better: <= good -> good, <= fair -> fair, else below_fair. Boundaries inclusive.
    None value or no reference -> None."""
    if value is None or not reference:
        return None
    fair, good = float(reference["fair"]), float(reference["good"])  # type: ignore[arg-type]
    if reference.get("direction", "higher_better") == "lower_better":
        return "good" if value <= good else "fair" if value <= fair else "below_fair"
    return "good" if value >= good else "fair" if value >= fair else "below_fair"
