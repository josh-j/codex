"""Jinja2-based ``when`` expression evaluator for alerts, visible_if, and style_rules."""

from __future__ import annotations

import functools
import logging
import re
from datetime import datetime, timezone
from typing import Any

from jinja2 import Undefined
from jinja2.nativetypes import NativeEnvironment

from ncs_reporter.primitives import SECONDS_PER_DAY

logger = logging.getLogger(__name__)


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning a UTC-aware datetime or None."""
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _age_days(value: Any, reference: Any = None) -> float:
    """Jinja2 filter: return days since an ISO-8601 timestamp.

    Usage in ``when`` expressions::

        last_backup | age_days > 7
        last_backup | age_days(reference_timestamp) > 7
    """
    dt = _parse_iso(str(value)) if not isinstance(value, datetime) else value
    if dt is None:
        return 0.0

    if reference is not None:
        ref_dt = _parse_iso(str(reference)) if not isinstance(reference, datetime) else reference
        ref_dt = ref_dt or datetime.now(timezone.utc)
    else:
        ref_dt = datetime.now(timezone.utc)

    return (ref_dt - dt).total_seconds() / SECONDS_PER_DAY


def _regex_search(value: Any, pattern: str, ignorecase: bool = False) -> str:
    """Return the first regex match (or first capture group) in *value*, or ''."""
    m = re.search(pattern, "" if value is None else str(value), re.IGNORECASE if ignorecase else 0)
    if m is None:
        return ""
    return m.group(1) if m.groups() else m.group(0)


def _regex_replace(value: Any, pattern: str, replacement: str = "", ignorecase: bool = False) -> str:
    """Substitute *pattern* with *replacement* in *value* (all matches)."""
    return re.sub(pattern, replacement, "" if value is None else str(value), flags=re.IGNORECASE if ignorecase else 0)


def _regex_findall(value: Any, pattern: str, ignorecase: bool = False) -> list[str]:
    """Return all non-overlapping regex matches in *value* as a list of strings."""
    return re.findall(pattern, "" if value is None else str(value), re.IGNORECASE if ignorecase else 0)


def _register_common_filters(env: NativeEnvironment) -> None:
    env.filters["age_days"] = _age_days
    env.filters["regex_search"] = _regex_search
    env.filters["regex_replace"] = _regex_replace
    env.filters["regex_findall"] = _regex_findall


@functools.lru_cache(maxsize=1)
def _build_jinja_env() -> NativeEnvironment:
    env = NativeEnvironment(undefined=Undefined)
    _register_common_filters(env)
    return env


@functools.lru_cache(maxsize=256)
def _compile_when(expression: str) -> Any:
    return _build_jinja_env().from_string("{{ " + expression + " }}")


@functools.lru_cache(maxsize=256)
def _compile_template(template: str) -> Any:
    """Compile a full Jinja template string (already containing ``{{ }}``)."""
    return _build_jinja_env().from_string(template)


# ---------------------------------------------------------------------------
# Arithmetic expression evaluation (compute fields, list_map)
# ---------------------------------------------------------------------------


class _NumericUndefined(Undefined):
    """Undefined that acts as ``0`` in arithmetic — for compute/list_map expressions."""

    def __int__(self) -> int:
        return 0

    def __float__(self) -> float:
        return 0.0

    def __bool__(self) -> bool:
        return False

    def __add__(self, o: Any) -> Any:
        return o

    def __radd__(self, o: Any) -> Any:
        return o

    def __sub__(self, o: Any) -> Any:
        return -o if not isinstance(o, Undefined) else 0

    def __rsub__(self, o: Any) -> Any:
        return o

    def __mul__(self, o: Any) -> Any:
        return 0

    def __rmul__(self, o: Any) -> Any:
        return 0

    def __truediv__(self, o: Any) -> float:
        return 0.0

    def __rtruediv__(self, o: Any) -> float:
        return 0.0

    def __neg__(self) -> int:
        return 0


@functools.lru_cache(maxsize=1)
def _build_arithmetic_env() -> NativeEnvironment:
    from ._transforms import _TRANSFORMS

    env = NativeEnvironment(undefined=_NumericUndefined)
    _register_common_filters(env)
    env.filters.update(_TRANSFORMS)
    return env


@functools.lru_cache(maxsize=256)
def _compile_expr(expression: str) -> Any:
    expr = expression.strip()
    if expr.startswith("{{") and expr.endswith("}}"):
        return _build_arithmetic_env().from_string(expr)
    return _build_arithmetic_env().from_string("{{ " + expr + " }}")


def eval_expression(expression: str, context: dict[str, Any]) -> float:
    """Evaluate a Jinja2 arithmetic expression, returning a float.

    Missing variables default to 0.  Division by zero returns 0.0.
    """
    try:
        result = _compile_expr(expression).render(**context)
    except ZeroDivisionError:
        return 0.0
    except Exception:
        logger.debug("eval_expression failed: %r", expression, exc_info=True)
        return 0.0

    try:
        return float(result)
    except (TypeError, ValueError):
        return 0.0


def eval_compute(expression: str, context: dict[str, Any]) -> Any:
    """Evaluate a Jinja2 compute expression, returning the native type.

    Like eval_expression but preserves int/float/str from the expression.
    Missing variables default to 0.  Division by zero returns 0.0.
    """
    try:
        return _compile_expr(expression).render(**context)
    except ZeroDivisionError:
        return 0.0
    except Exception:
        logger.debug("eval_compute failed: %r", expression, exc_info=True)
        return 0.0


# ---------------------------------------------------------------------------
# Boolean when-expression evaluation (alerts, visible_if, style_rules)
# ---------------------------------------------------------------------------


def evaluate_when(expression: str, fields: dict[str, Any]) -> bool:
    """Evaluate a Jinja2 ``when`` expression against *fields* and return a bool.

    Returns ``False`` for undefined variables, render errors, or falsy results.
    """
    try:
        result = _compile_when(expression).render(**fields)
    except Exception:
        logger.debug("when expression failed: %r", expression, exc_info=True)
        return False

    if isinstance(result, Undefined):
        return False

    return bool(result)
