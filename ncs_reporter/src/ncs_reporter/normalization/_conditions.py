"""Condition evaluation for schema-driven alerts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ncs_reporter.models.report_schema import (
    ComputedFilterCondition,
    DateThresholdCondition,
    ExistsCondition,
    FilterCountCondition,
    MultiFilterCondition,
    RangeCondition,
    StringCondition,
    StringInCondition,
    ThresholdCondition,
)
from ncs_reporter.primitives import SECONDS_PER_DAY, safe_list

from ._transforms import _safe_eval_expr


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning a UTC-aware datetime or None."""
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


_OPS: dict[str, Any] = {
    "gt": lambda v, t: v > t,
    "lt": lambda v, t: v < t,
    "gte": lambda v, t: v >= t,
    "lte": lambda v, t: v <= t,
    "eq": lambda v, t: v == t,
    "ne": lambda v, t: v != t,
}


def _eval_threshold(condition: Any, fields: dict[str, Any]) -> bool:
    value = fields.get(condition.field)
    if value is None:
        return False
    comparator = _OPS.get(condition.op)
    if comparator is None:
        return False
    try:
        return bool(comparator(float(value), float(condition.threshold)))
    except (TypeError, ValueError):
        return False


def _eval_exists(condition: Any, fields: dict[str, Any]) -> bool:
    value = fields.get(condition.field)
    if condition.op == "exists":
        return value is not None and value != [] and value != {}
    else:  # not_exists
        return value is None or value == [] or value == {}


def _eval_filter_count(condition: Any, fields: dict[str, Any]) -> bool:
    lst = safe_list(fields.get(condition.field, []))
    count = sum(
        1 for item in lst if isinstance(item, dict) and item.get(condition.filter_field) == condition.filter_value
    )
    return count > condition.threshold


def _eval_string(condition: Any, fields: dict[str, Any]) -> bool:
    value = str(fields.get(condition.field, ""))
    if condition.op == "eq_str":
        return value == condition.value
    else:  # ne_str
        return value != condition.value


def _eval_string_in(condition: Any, fields: dict[str, Any]) -> bool:
    value = str(fields.get(condition.field, ""))
    if condition.op == "in_str":
        return value in condition.values
    else:  # not_in_str
        return value not in condition.values


def _eval_multi_filter(condition: Any, fields: dict[str, Any]) -> bool:
    lst = safe_list(fields.get(condition.field, []))
    count = sum(
        1
        for item in lst
        if isinstance(item, dict) and all(item.get(f.filter_field) == f.filter_value for f in condition.filters)
    )
    return count > condition.threshold


def _eval_range(condition: Any, fields: dict[str, Any]) -> bool:
    value = float(fields.get(condition.field, 0.0))
    # min <= val < max
    return condition.min <= value < condition.max


def _eval_computed_filter(condition: Any, fields: dict[str, Any]) -> bool:
    lst = safe_list(fields.get(condition.field, []))
    if condition.cmp == "range":
        if condition.min is None or condition.max is None:
            return False
        for item in lst:
            if not isinstance(item, dict):
                continue
            try:
                val = _safe_eval_expr(condition.expression, item)
                if condition.min <= val < condition.max:
                    return True
            except Exception:
                continue
        return False

    comparator = _OPS.get(condition.cmp)
    if comparator is None or condition.threshold is None:
        return False
    for item in lst:
        if not isinstance(item, dict):
            continue
        try:
            val = _safe_eval_expr(condition.expression, item)
            if comparator(val, condition.threshold):
                return True
        except Exception:
            continue
    return False


_DATE_OPS: dict[str, Any] = {
    "age_gt": lambda a, t: a > t,
    "age_lt": lambda a, t: a < t,
    "age_gte": lambda a, t: a >= t,
    "age_lte": lambda a, t: a <= t,
}


def _eval_date_threshold(condition: Any, fields: dict[str, Any]) -> bool:
    ts_str = str(fields.get(condition.field) or "")
    field_dt = _parse_iso(ts_str)
    if field_dt is None:
        return False

    if condition.reference_field:
        ref_str = str(fields.get(condition.reference_field) or "")
        ref_dt = _parse_iso(ref_str) or datetime.now(timezone.utc)
    else:
        ref_dt = datetime.now(timezone.utc)

    age_days = (ref_dt - field_dt).total_seconds() / SECONDS_PER_DAY
    cmp_fn = _DATE_OPS.get(condition.op)
    return bool(cmp_fn(age_days, condition.days)) if cmp_fn else False


_CONDITION_DISPATCH: dict[type, Callable[[Any, dict[str, Any]], bool]] = {
    ThresholdCondition: _eval_threshold,
    ExistsCondition: _eval_exists,
    FilterCountCondition: _eval_filter_count,
    StringCondition: _eval_string,
    StringInCondition: _eval_string_in,
    MultiFilterCondition: _eval_multi_filter,
    RangeCondition: _eval_range,
    ComputedFilterCondition: _eval_computed_filter,
    DateThresholdCondition: _eval_date_threshold,
}


def evaluate_condition(condition: Any, fields: dict[str, Any]) -> bool:
    """Evaluate a single AlertCondition against extracted *fields*."""
    handler = _CONDITION_DISPATCH.get(type(condition))
    if handler is not None:
        return handler(condition, fields)
    return False


def _filter_affected_items(condition: Any, items: list[Any]) -> list[Any]:
    """Filter *items* to only those matching the alert *condition*.

    For list-filtering conditions (``computed_filter``, ``filter_count``,
    ``filter_multi``) this returns the subset of items that actually triggered
    the alert.  For scalar conditions the full list is returned unchanged.
    """
    if isinstance(condition, ComputedFilterCondition):
        result: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                val = _safe_eval_expr(condition.expression, item)
            except Exception:
                continue
            if condition.cmp == "range":
                if condition.min is not None and condition.max is not None and condition.min <= val < condition.max:
                    result.append(item)
            else:
                comparator = _OPS.get(condition.cmp)
                if comparator and condition.threshold is not None and comparator(val, condition.threshold):
                    result.append(item)
        return result

    if isinstance(condition, FilterCountCondition):
        return [
            item for item in items
            if isinstance(item, dict) and item.get(condition.filter_field) == condition.filter_value
        ]

    if isinstance(condition, MultiFilterCondition):
        return [
            item for item in items
            if isinstance(item, dict) and all(item.get(f.filter_field) == f.filter_value for f in condition.filters)
        ]

    return items
