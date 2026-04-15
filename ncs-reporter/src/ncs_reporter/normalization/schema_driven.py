"""Schema-driven normalization: execute a ReportSchema against a raw bundle."""

from __future__ import annotations

import functools
import logging
from datetime import datetime
from typing import Any

from ncs_reporter.alerts import compute_audit_rollups
from ncs_reporter.models.report_schema import ReportSchema
from ncs_reporter.primitives import canonical_severity

from ._when import (
    _build_jinja_env,
    _compile_template,
    _parse_iso,  # noqa: F401
    eval_compute,
    eval_expression,  # noqa: F401
    evaluate_when,
)
from ._fields import (
    _BUILTIN_SCRIPTS_DIR,  # noqa: F401
    _SCRIPT_ERROR_SENTINEL,
    _apply_list_processing,
    _coerce,
    _coerce_bytes,  # noqa: F401
    _coerce_datetime,  # noqa: F401
    _coerce_duration,  # noqa: F401
    _coerce_percentage,  # noqa: F401
    _get_sentinel,
    _resolve_script,
    _run_script_field,
    resolve_field,  # noqa: F401
)

logger = logging.getLogger(__name__)


def _metadata_path(path_prefix: str) -> str:
    """Derive the ``metadata.timestamp`` path from a ``path_prefix``.

    Convention: ``raw_<name>.data`` → ``raw_<name>.metadata.timestamp``.
    Works for any nesting depth (strips the rightmost ``.data`` segment).
    """
    return path_prefix.rsplit(".data", 1)[0] + ".metadata.timestamp"


def extract_fields(schema: ReportSchema, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
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

    # Pass 0: auto-import all keys from path_prefix data dict as vars.
    # Declared fields override these in subsequent passes.
    if schema.path_prefix:
        prefix_data = resolve_field(schema.path_prefix, raw)
        if isinstance(prefix_data, dict):
            result.update(prefix_data)
        # Auto-inject collected_at from metadata.timestamp
        ts = resolve_field(_metadata_path(schema.path_prefix), raw)
        if ts and "collected_at" not in result:
            result["collected_at"] = ts

    # Set of field names whose paths are known-broken (populated at schema load
    # time by schema_loader._attach_broken_paths).  Empty if no example file.
    _broken_paths: frozenset[str] = getattr(schema, "_broken_paths", frozenset())

    path_total = 0
    path_resolved = 0
    path_broken = 0

    # Pass 1: path-based fields (override auto-imported vars)
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
                processed = _apply_list_processing(raw_value, spec)
                coerced = _coerce(processed, spec.type, spec.fallback)
                result[name] = coerced
                if raw_value is not None:
                    path_resolved += 1

    # Pass 2: compute fields (expression result type is authoritative)
    for name, spec in schema.fields.items():
        if spec.compute is not None:
            try:
                result[name] = eval_compute(spec.compute, result)
            except Exception as exc:
                logger.warning("compute field '%s' failed: %s", name, exc)
                result[name] = _get_sentinel(spec)

    # Pass 3: script fields (with result caching for identical script+args)
    schema_source = getattr(schema, "_source_path", None)
    _script_cache: dict[tuple[str, frozenset[tuple[str, str]]], Any] = {}
    for name, spec in schema.fields.items():
        if spec.script is not None:
            ss = spec.script
            script_path = _resolve_script(ss.path, schema_source)
            if script_path is None:
                logger.warning("Script not found for field '%s': %s", name, ss.path)
                result[name] = _get_sentinel(spec)
                continue
            # Cache key: (resolved_path, frozen args) — avoids re-running identical invocations
            cache_key = (
                str(script_path),
                frozenset((k, repr(v)) for k, v in sorted((ss.args or {}).items())),
            )
            if cache_key in _script_cache:
                value = _script_cache[cache_key]
            else:
                value = _run_script_field(script_path, result, ss.args, ss.timeout)
                _script_cache[cache_key] = value
            if value is _SCRIPT_ERROR_SENTINEL:
                result[name] = _get_sentinel(spec)
            else:
                # script_bundles expansion sets _extract_key to pluck from a dict result
                extract_key = (ss.args or {}).get("_extract_key")
                if extract_key and isinstance(value, dict):
                    value = value.get(extract_key)
                processed = _apply_list_processing(value, spec)
                result[name] = _coerce(processed, spec.type, spec.fallback)

    # Pass 4: re-evaluate compute fields (allows compute to reference script results)
    for name, spec in schema.fields.items():
        if spec.compute is not None:
            try:
                result[name] = eval_compute(spec.compute, result)
            except Exception as exc:
                logger.warning("compute field '%s' (pass 4) failed: %s", name, exc)
                if name not in result:
                    result[name] = _get_sentinel(spec)

    coverage = {"resolved": path_resolved, "total": path_total, "broken": path_broken}
    return result, coverage


@functools.lru_cache(maxsize=256)
def _extract_when_refs(expression: str) -> tuple[str, ...]:
    """Extract field names referenced in a when expression."""
    from jinja2 import meta
    try:
        ast = _build_jinja_env().parse("{{ " + expression + " }}")
        return tuple(sorted(meta.find_undeclared_variables(ast)))
    except Exception:
        return ()


def build_schema_alerts(schema: ReportSchema, fields: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate all alert rules and return alert dicts."""
    alerts: list[dict[str, Any]] = []
    fired_ids: set[str] = set()

    for rule in schema.alerts:
        if not evaluate_when(rule.when, fields):
            continue

        # Check suppress_if: skip this alert if any referenced alert already fired
        if rule.suppress_if is not None:
            suppressor_ids = [rule.suppress_if] if isinstance(rule.suppress_if, str) else rule.suppress_if
            if any(sid in fired_ids for sid in suppressor_ids):
                continue

        try:
            message = _compile_template(rule.msg).render(**fields)
        except Exception:
            logger.debug("alert %s msg template failed", rule.id, exc_info=True)
            message = rule.msg

        affected_items: list[Any] = []
        if rule.items:
            try:
                items_result = _compile_template(rule.items).render(**fields)
                if isinstance(items_result, list):
                    affected_items = items_result
            except Exception:
                logger.debug("alert %s items expression failed", rule.id, exc_info=True)
        else:
            for ref in _extract_when_refs(rule.when):
                if ref not in fields or ref.startswith("_"):
                    continue
                val = fields[ref]
                if isinstance(val, list):
                    affected_items = val

        alerts.append(
            {
                "id": rule.id,
                "severity": canonical_severity(rule.severity),
                "category": rule.category,
                "message": message,
                "affected_items": affected_items,
                "action": rule.action,
                "cooldown": rule.cooldown,
                "condition": True,
            }
        )
        fired_ids.add(rule.id)

    return alerts


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
    from ncs_reporter.constants import FIELD_CRITICAL_COUNT, FIELD_TOTAL_ALERTS, FIELD_WARNING_COUNT
    summary = rollups["summary"]
    crit = summary.get("critical_count", 0)
    warn = summary.get("warning_count", 0)
    fields[FIELD_CRITICAL_COUNT] = crit
    fields[FIELD_WARNING_COUNT] = warn
    fields[FIELD_TOTAL_ALERTS] = crit + warn

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
