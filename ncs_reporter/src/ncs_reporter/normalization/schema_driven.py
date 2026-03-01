"""Schema-driven normalization: execute a ReportSchema against a raw bundle."""

from __future__ import annotations

import ast
import json
import logging
import operator as _op
import re as _re
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ncs_reporter.alerts import compute_audit_rollups
from ncs_reporter.models.report_schema import (
    ComputedFilterCondition,
    DateThresholdCondition,
    ExistsCondition,
    FilterCountCondition,
    MultiFilterCondition,
    RangeCondition,
    ReportSchema,
    StringCondition,
    StringInCondition,
    ThresholdCondition,
)
from ncs_reporter.primitives import canonical_severity, safe_list

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Script field execution
# ---------------------------------------------------------------------------

# Built-in scripts shipped with the package
_BUILTIN_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _resolve_script(script: str, schema_source_path: str | None) -> Path | None:
    """
    Resolve *script* to an executable path.  Search order:
      1. Absolute path (used as-is if it exists)
      2. Relative to the schema file's directory
      3. CWD-relative
      4. Built-in package scripts/
    """
    p = Path(script)
    if p.is_absolute():
        return p if p.exists() else None

    if schema_source_path:
        candidate = Path(schema_source_path).parent / script
        if candidate.exists():
            return candidate

    if p.exists():
        return p

    candidate = _BUILTIN_SCRIPTS_DIR / script
    if candidate.exists():
        return candidate

    return None


def _run_script_field(
    script_path: Path,
    fields: dict[str, Any],
    args: dict[str, Any],
    timeout: int,
) -> Any:
    """
    Invoke *script_path* as a subprocess.

    stdin  — JSON: ``{"fields": {...}, "args": {...}}``
    stdout — JSON-serialised return value
    exit 0 — value used; non-zero — None returned (caller uses fallback)

    .py files are executed with the current interpreter so no shebang / chmod
    is required for built-in scripts.
    """
    payload = json.dumps({"fields": fields, "args": args})
    cmd: list[str] = (
        [sys.executable, str(script_path)]
        if script_path.suffix == ".py"
        else [str(script_path)]
    )
    # Return-code convention:
    #   0  — success; stdout is the JSON value
    #   1  — data not available on this host (normal); use fallback, no warning
    #   2+ — script error / broken path; use sentinel, log warning
    try:
        result = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return json.loads(result.stdout.strip())
        if result.returncode == 1:
            # Data absent — caller uses fallback quietly.
            return None
        # rc >= 2: something is broken
        logger.warning(
            "Script %s exited %d (broken): %s",
            script_path,
            result.returncode,
            result.stderr.strip()[:200],
        )
        return _SCRIPT_ERROR_SENTINEL
    except subprocess.TimeoutExpired:
        logger.warning("Script %s timed out after %ds", script_path, timeout)
        return _SCRIPT_ERROR_SENTINEL
    except Exception as exc:
        logger.warning("Script %s failed: %s", script_path, exc)
        return _SCRIPT_ERROR_SENTINEL


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


def resolve_field(path: str, raw: dict[str, Any]) -> Any:
    """
    Resolve a field path against *raw*.

    Syntax:
      - Dot-notation traversal: ``"ansible_facts.hostname"``
      - Optional pipe transform: ``"interfaces | len_if_list"``
    """
    transform_name: str | None = None

    if " | " in path:
        path_part, transform_name = path.split(" | ", 1)
        path_part = path_part.strip()
        transform_name = transform_name.strip()
    else:
        path_part = path

    obj: Any = raw
    for segment in path_part.split("."):
        segment = segment.strip()
        if not segment:
            continue
        if isinstance(obj, dict):
            obj = obj.get(segment)
        else:
            obj = None
            break

    if transform_name is not None:
        transform = _TRANSFORMS.get(transform_name)
        if transform is None:
            logger.warning("Unknown transform '%s' in path '%s'", transform_name, path)
        else:
            obj = transform(obj)

    return obj


_FALSY_STRINGS: frozenset[str] = frozenset({"false", "no", "0", "off", ""})


def _coerce_bool(value: Any) -> bool:
    """Coerce a value to bool, handling string representations from Ansible modules.

    The vmware.vmware.appliance_info module returns shell.enabled as the string
    "False" / "True" rather than a Python bool.  Python's built-in bool() treats
    any non-empty string as True, so a plain bool() coercer would incorrectly mark
    "False" as enabled.  This handles that case.
    """
    if isinstance(value, str):
        return value.lower() not in _FALSY_STRINGS
    return bool(value)


_TYPE_COERCERS: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": _coerce_bool,
    "list": safe_list,
    "dict": dict,
}


# Sentinel object returned by _run_script_field on rc >= 2 / timeout / crash.
# Distinct from None (data absent) so the script pass can tell them apart.
_SCRIPT_ERROR_SENTINEL = object()

# Type-appropriate sentinel values shown when a path is provably broken.
# Deliberately wrong-looking so problems are visible in the rendered report.
_TYPE_SENTINELS: dict[str, Any] = {
    "str": "ERROR",
    "int": -1,
    "float": -1.0,
}


def _get_sentinel(spec: Any) -> Any:
    """Return the sentinel for a broken path field."""
    if spec.sentinel is not None:
        return spec.sentinel
    return _TYPE_SENTINELS.get(spec.type, spec.fallback)


def _coerce(value: Any, type_name: str, fallback: Any) -> Any:
    if value is None:
        return fallback
    coercer = _TYPE_COERCERS.get(type_name)
    if coercer is None:
        return value
    try:
        if type_name == "list":
            return safe_list(value)
        if type_name == "dict":
            return value if isinstance(value, dict) else fallback
        return coercer(value)
    except (TypeError, ValueError):
        return fallback


def extract_fields(
    schema: ReportSchema, raw: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """
    Walk schema.fields, resolve each from *raw*, coerce types, apply fallbacks.

    Three-pass evaluation:
      1. path fields    — resolved from raw data
      2. compute fields — arithmetic expressions referencing already-extracted fields
      3. script fields  — subprocess invocations; receive all prior fields + static args

    Returns ``(fields, coverage)`` where *coverage* is
    ``{"resolved": N, "total": M, "broken": B}`` for path-based fields.
    """
    result: dict[str, Any] = {}

    # Set of field names whose paths are known-broken (populated at schema load
    # time by schema_loader._attach_broken_paths).  Empty if no example file.
    _broken_paths: frozenset[str] = getattr(schema, "_broken_paths", frozenset())

    path_total = 0
    path_resolved = 0
    path_broken = 0

    # Pass 1: path-based fields
    for name, spec in schema.fields.items():
        if spec.path is not None:
            path_total += 1
            raw_value = resolve_field(spec.path, raw)
            if raw_value is None and name in _broken_paths:
                # Path is provably broken (verified at load time against the
                # example bundle).  Use the sentinel so the report makes the
                # problem visible rather than silently showing a neutral fallback.
                result[name] = _get_sentinel(spec)
                path_broken += 1
            else:
                result[name] = _coerce(raw_value, spec.type, spec.fallback)
                if raw_value is not None:
                    path_resolved += 1

    # Pass 2: compute fields
    for name, spec in schema.fields.items():
        if spec.compute is not None:
            try:
                computed = _safe_eval_expr(spec.compute, result)
                result[name] = _coerce(computed, spec.type, spec.fallback)
            except Exception as exc:
                logger.warning("compute field '%s' failed: %s", name, exc)
                result[name] = _get_sentinel(spec)

    # Pass 3: script fields
    schema_source = getattr(schema, "_source_path", None)
    for name, spec in schema.fields.items():
        if spec.script is not None:
            script_path = _resolve_script(spec.script, schema_source)
            if script_path is None:
                logger.warning("Script not found for field '%s': %s", name, spec.script)
                result[name] = _get_sentinel(spec)
                continue
            value = _run_script_field(script_path, result, spec.script_args, spec.script_timeout)
            if value is _SCRIPT_ERROR_SENTINEL:
                result[name] = _get_sentinel(spec)
            else:
                result[name] = _coerce(value, spec.type, spec.fallback)

    # Pass 4: re-evaluate compute fields (allows compute to reference script results)
    for name, spec in schema.fields.items():
        if spec.compute is not None:
            try:
                computed = _safe_eval_expr(spec.compute, result)
                result[name] = _coerce(computed, spec.type, spec.fallback)
            except Exception as exc:
                logger.warning("compute field '%s' (pass 4) failed: %s", name, exc)
                # Don't overwrite if pass 2 already succeeded unless error
                if name not in result:
                    result[name] = _get_sentinel(spec)

    coverage = {"resolved": path_resolved, "total": path_total, "broken": path_broken}
    return result, coverage


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

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


def evaluate_condition(condition: Any, fields: dict[str, Any]) -> bool:
    """Evaluate a single AlertCondition against extracted *fields*."""
    if isinstance(condition, ThresholdCondition):
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

    if isinstance(condition, ExistsCondition):
        value = fields.get(condition.field)
        if condition.op == "exists":
            return value is not None and value != [] and value != {}
        else:  # not_exists
            return value is None or value == [] or value == {}

    if isinstance(condition, FilterCountCondition):
        lst = safe_list(fields.get(condition.field, []))
        count = sum(
            1 for item in lst
            if isinstance(item, dict) and item.get(condition.filter_field) == condition.filter_value
        )
        return count > condition.threshold

    if isinstance(condition, StringCondition):
        value = str(fields.get(condition.field, ""))
        if condition.op == "eq_str":
            return value == condition.value
        else:  # ne_str
            return value != condition.value

    if isinstance(condition, StringInCondition):
        value = str(fields.get(condition.field, ""))
        if condition.op == "in_str":
            return value in condition.values
        else:  # not_in_str
            return value not in condition.values

    if isinstance(condition, MultiFilterCondition):
        lst = safe_list(fields.get(condition.field, []))
        count = sum(
            1 for item in lst
            if isinstance(item, dict)
            and all(item.get(f.filter_field) == f.filter_value for f in condition.filters)
        )
        return count > condition.threshold

    if isinstance(condition, RangeCondition):
        value = float(fields.get(condition.field, 0.0))
        # min <= val < max
        return condition.min <= value < condition.max

    if isinstance(condition, ExistsCondition):
        if condition.op == "exists":
            return condition.field in fields
        else:  # not_exists
            return condition.field not in fields

    if isinstance(condition, ComputedFilterCondition):
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

    if isinstance(condition, DateThresholdCondition):
        ts_str = str(fields.get(condition.field) or "")
        field_dt = _parse_iso(ts_str)
        if field_dt is None:
            return False

        if condition.reference_field:
            ref_str = str(fields.get(condition.reference_field) or "")
            ref_dt = _parse_iso(ref_str) or datetime.now(timezone.utc)
        else:
            ref_dt = datetime.now(timezone.utc)

        age_days = (ref_dt - field_dt).total_seconds() / 86400.0
        _date_ops = {
            "age_gt": lambda a, t: a > t,
            "age_lt": lambda a, t: a < t,
            "age_gte": lambda a, t: a >= t,
            "age_lte": lambda a, t: a <= t,
        }
        cmp_fn = _date_ops.get(condition.op)
        return bool(cmp_fn(age_days, condition.days)) if cmp_fn else False

    return False


# ---------------------------------------------------------------------------
# Alert building
# ---------------------------------------------------------------------------


def build_schema_alerts(schema: ReportSchema, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate all alert rules and return alert dicts compatible with build_alerts()."""
    alerts: list[dict[str, Any]] = []
    for rule in schema.alerts:
        if not evaluate_condition(rule.condition, fields):
            continue

        try:
            message = rule.message.format(**fields)
        except (KeyError, ValueError):
            message = rule.message

        detail: dict[str, Any] = {}
        for df in rule.detail_fields:
            if df in fields:
                detail[df] = fields[df]

        affected_items: list[Any] = []
        if rule.affected_items_field:
            affected_items = safe_list(fields.get(rule.affected_items_field, []))

        alerts.append({
            "id": rule.id,
            "severity": canonical_severity(rule.severity),
            "category": rule.category,
            "message": message,
            "detail": detail,
            "affected_items": affected_items,
            "condition": True,
        })

    return alerts


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def normalize_from_schema(schema: ReportSchema, raw_bundle: dict[str, Any]) -> dict[str, Any]:
    """
    Execute *schema* against *raw_bundle* and return a standard audit dict with:
      metadata, health, summary, alerts, fields, widgets_meta
    """
    fields, coverage = extract_fields(schema, raw_bundle)
    raw_alerts = build_schema_alerts(schema, fields)
    rollups = compute_audit_rollups(raw_alerts)

    # Inject alert statistics as virtual fields starting with '_' so they
    # can be referenced in fleet_columns or widgets.
    crit = len([a for a in raw_alerts if a.get("severity") == "CRITICAL"])
    warn = len([a for a in raw_alerts if a.get("severity") == "WARNING"])
    fields["_critical_count"] = crit
    fields["_warning_count"] = warn
    fields["_total_alerts"] = crit + warn

    widgets_meta: dict[str, Any] = {}
    for widget in schema.widgets:
        widgets_meta[widget.id] = {
            "id": widget.id,
            "title": widget.title,
            "type": widget.type,
        }

    return {
        "metadata": {
            "audit_type": f"schema_{schema.name}",
            "schema_name": schema.name,
            "platform": schema.platform,
            "display_name": schema.display_name,
            "generated_at": datetime.now().isoformat(),
            "field_coverage": coverage,
        },
        "health": rollups["health"],
        "summary": rollups["summary"],
        "alerts": raw_alerts,
        "fields": fields,
        "widgets_meta": widgets_meta,
        "schema": {
            "name": schema.name,
            "display_name": schema.display_name,
            "widgets": [w.model_dump() for w in schema.widgets],
        },
    }
