"""Built-in pipe transforms and safe arithmetic expression evaluator."""

from __future__ import annotations

import ast
import operator as _op
import re as _re
from collections.abc import Callable
from typing import Any

from ncs_reporter.primitives import BYTES_PER_GB, BYTES_PER_MB, SECONDS_PER_DAY

# ---------------------------------------------------------------------------
# Built-in pipe transforms
# ---------------------------------------------------------------------------

_TRANSFORMS: dict[str, Callable[[Any], Any]] = {}


def _register_transform(name: str) -> Callable[[Callable[[Any], Any]], Callable[[Any], Any]]:
    def decorator(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        _TRANSFORMS[name] = fn
        return fn

    return decorator


@_register_transform("len_if_list")
def _len_if_list(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


@_register_transform("first")
def _first(value: Any) -> Any:
    if isinstance(value, list) and value:
        return value[0]
    return None


@_register_transform("to_gb")
def _to_gb(value: Any) -> float:
    try:
        return round(float(value) / BYTES_PER_GB, 2)
    except (TypeError, ValueError):
        return 0.0


@_register_transform("to_mb")
def _to_mb(value: Any) -> float:
    try:
        return round(float(value) / BYTES_PER_MB, 2)
    except (TypeError, ValueError):
        return 0.0


@_register_transform("to_days")
def _to_days(value: Any) -> float:
    try:
        return round(float(value) / SECONDS_PER_DAY, 1)
    except (TypeError, ValueError):
        return 0.0


@_register_transform("join_lines")
def _join_lines(value: Any) -> str:
    """Join a list of strings into a single newline-delimited string."""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value) if value is not None else ""


@_register_transform("keys")
def _keys(value: Any) -> list[str]:
    """Return the keys of a dict as a list."""
    if isinstance(value, dict):
        return list(value.keys())
    return []


@_register_transform("values")
def _values(value: Any) -> list[Any]:
    """Return the values of a dict as a list."""
    if isinstance(value, dict):
        return list(value.values())
    return []


@_register_transform("flatten")
def _flatten(value: Any) -> list[Any]:
    """Flatten a list of lists into a single list."""
    if not isinstance(value, list):
        return []
    result: list[Any] = []
    for item in value:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Parameterized transforms (name(arg) syntax)
# ---------------------------------------------------------------------------

_PARAM_TRANSFORMS: dict[str, Callable[..., Any]] = {}


def _register_param_transform(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _PARAM_TRANSFORMS[name] = fn
        return fn

    return decorator


@_register_param_transform("regex_extract")
def _regex_extract(value: Any, pattern: str) -> str:
    """Extract the first capture group from a string using a regex pattern."""
    text = str(value) if value is not None else ""
    m = _re.search(pattern, text)
    return m.group(1) if m else ""


@_register_param_transform("parse_kv")
def _parse_kv(value: Any, separator: str = " ", comment: str = "#") -> dict[str, str]:
    """Parse key-value pairs from lines of text.

    Strips comment lines (starting with `comment`), splits on `separator`,
    and strips inline comments.
    """
    lines: list[str] = []
    if isinstance(value, list):
        lines = [str(v) for v in value]
    elif isinstance(value, str):
        lines = value.splitlines()
    else:
        return {}

    result: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith(comment):
            continue
        if separator == " ":
            parts = line.split(None, 1)
        else:
            parts = line.split(separator, 1)
        if len(parts) == 2 and parts[0]:
            val = parts[1].split(comment, 1)[0].strip()
            result[parts[0]] = val
    return result


@_register_param_transform("round")
def _round_transform(value: Any, digits: str = "0") -> float:
    """Round a number to the given number of decimal places."""
    try:
        return round(float(value), int(digits))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Safe arithmetic expression evaluator
# ---------------------------------------------------------------------------

_EXPR_OPS: dict[type, Any] = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.USub: _op.neg,
    ast.UAdd: lambda x: x,
}

_FIELD_REF_RE = _re.compile(r"\{(\w+)\}")


def _safe_eval_expr(expression: str, context: dict[str, Any]) -> float:
    """
    Evaluate a numeric arithmetic expression with {field} substitutions.

    - Supports: +  -  *  /  and numeric literals.
    - Field references like ``{freeSpace}`` are replaced from *context*.
    - Division by zero returns 0.0.
    - Any non-numeric or structurally unsafe input raises ValueError.
    """

    def _sub(m: _re.Match[str]) -> str:
        val = context.get(m.group(1), 0)
        try:
            return str(float(val))
        except (TypeError, ValueError):
            return "0"

    substituted = _FIELD_REF_RE.sub(_sub, expression)

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"Non-numeric constant: {node.value!r}")
        if isinstance(node, ast.BinOp):
            op_fn = _EXPR_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Div) and right == 0.0:
                return 0.0
            return float(op_fn(left, right))
        if isinstance(node, ast.UnaryOp):
            op_fn = _EXPR_OPS.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")
            return float(op_fn(_eval(node.operand)))
        raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    try:
        tree = ast.parse(substituted, mode="eval")
        return _eval(tree.body)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Expression error in '{expression}': {exc}") from exc
