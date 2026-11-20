"""Whitelisted arithmetic expressions over item ids (pack `summaries[].expr`).

This module only parses and validates. Evaluation is added with the summaries task.
"""

import ast

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
