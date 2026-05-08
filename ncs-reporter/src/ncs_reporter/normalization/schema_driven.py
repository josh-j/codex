"""Schema-driven normalization: execute a ReportSchema against a raw bundle."""

from __future__ import annotations

import functools
import graphlib
import logging
from datetime import datetime
from typing import Any

from jinja2 import meta as jinja_meta

from ncs_reporter.alerts import compute_audit_rollups
from ncs_reporter.models.report_schema import _SENTINEL_UNSET, ReportSchema
from ncs_reporter.primitives import canonical_severity

from ._when import (
    _build_jinja_env,
    _compile_template,
    eval_compute,
    evaluate_when,
)
from ._normalize_dsl import eval_normalize
from ._fields import (
    _SCRIPT_ERROR_SENTINEL,
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


@functools.lru_cache(maxsize=256)
def _compile_field_template(template: str) -> Any:
    return _build_jinja_env().from_string(template)


def _eval_template_field(template: str, context: dict[str, Any]) -> Any:
    return _compile_field_template(template).render(**context)


# ---------------------------------------------------------------------------
# Dependency extraction (for topological ordering of producers)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=512)
def _jinja_referenced_names(text: str) -> frozenset[str]:
    """Extract identifier references from a Jinja template/expression.

    Bare expression text (no `{{ }}`) is wrapped to mirror the runtime
    semantics of `eval_compute` / `evaluate_when`, which both accept
    pure expressions without delimiters.
    """
    if not text:
        return frozenset()
    src = text.strip()
    if "{{" not in src and "{%" not in src:
        src = "{{ " + src + " }}"
    try:
        ast = _build_jinja_env().parse(src)
        return frozenset(jinja_meta.find_undeclared_variables(ast))
    except Exception:
        # Empty deps from a parse failure can silently break topo
        # ordering — log so the issue surfaces at debug level.
        logger.debug("jinja parse failed for dependency extraction: %r", text, exc_info=True)
        return frozenset()


def _normalize_referenced_names(spec: Any, declared: set[str], deps: set[str]) -> None:
    """Walk a `normalize:` spec, collecting declared-field references.

    The DSL accepts:
      - bare strings as path lookups (`"items"`, `"item.foo"`, `"parent.bar"`)
      - dict ops with string operands (`{path: "items"}`, `{flatten: "x[]"}`)
      - embedded Jinja in `expr:` / `compute:` / `template:` strings
    Conservative: any string whose head segment matches a declared field
    name counts as a dep. `item.X` / `parent.X` are scoped references and
    do *not* count as top-level deps.
    """
    if isinstance(spec, str):
        if "{{" in spec or "{%" in spec:
            deps.update(_jinja_referenced_names(spec) & declared)
            return
        head = spec.split(".", 1)[0]
        if head in ("item", "parent"):
            return
        if head in declared:
            deps.add(head)
        return
    if isinstance(spec, dict):
        for value in spec.values():
            _normalize_referenced_names(value, declared, deps)
    elif isinstance(spec, list):
        for value in spec:
            _normalize_referenced_names(value, declared, deps)


def _producer_dependencies(spec: Any, declared: set[str]) -> frozenset[str]:
    """Return the set of declared field names this field's producer references."""
    deps: set[str] = set()
    if spec.compute is not None:
        deps |= _jinja_referenced_names(spec.compute) & declared
    if spec.template is not None:
        deps |= _jinja_referenced_names(spec.template) & declared
    if spec.normalize is not None:
        _normalize_referenced_names(spec.normalize, declared, deps)
    # path/const/script have no declared-field dependencies (path resolves
    # against the raw bundle; const is literal; script is opaque and is
    # always run last).
    return frozenset(deps)


def _topological_order(producers: list[str], deps: dict[str, frozenset[str]]) -> list[str]:
    """Topologically sort *producers* by their declared-field deps.

    Cycles are a schema-author bug — when one is detected the evaluator
    falls back to declaration order and emits a warning naming the
    cycle members. Cyclic fields will evaluate against `Undefined`
    references on the back-edge (the arithmetic env coerces those to
    `0`), matching the legacy double-pass behavior.
    """
    sorter: graphlib.TopologicalSorter[str] = graphlib.TopologicalSorter()
    producer_set = set(producers)
    for name in producers:
        sorter.add(name, *(deps.get(name, frozenset()) & producer_set))
    try:
        return list(sorter.static_order())
    except graphlib.CycleError as exc:
        cycle = list(exc.args[1]) if len(exc.args) > 1 else producers
        logger.warning("schema field dependency cycle detected, falling back to declaration order: %s", cycle)
        return list(producers)


def _producer_order(schema: ReportSchema) -> list[str]:
    """Topologically order compute / normalize / template producer fields by
    their declared-field references. Cached per-schema on the schema object.

    Script fields run after the topological pass (they're opaque and may
    invoke arbitrary helpers); path/const fields run before it.
    """
    if schema._producer_order is not None:
        return schema._producer_order
    declared = set(schema.fields)
    producers = [
        name for name, spec in schema.fields.items()
        if spec.compute is not None or spec.normalize is not None or spec.template is not None
    ]
    deps = {name: _producer_dependencies(schema.fields[name], declared) for name in producers}
    schema._producer_order = _topological_order(producers, deps)
    return schema._producer_order


def extract_fields(schema: ReportSchema, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """
    Walk schema.fields, resolve each from *raw*, coerce types, apply fallbacks.

    Evaluation order:
      Pass 0. auto-imported keys from `path_prefix` (declared fields override)
      Pass 1. const fields              — literal values
      Pass 2. path fields               — resolved from raw data
      Pass 3. compute / normalize / template fields — topologically ordered
              by declared-field references; each evaluated exactly once
      Pass 4. script fields             — subprocess invocations, run last
              (opaque dependencies — see `_run_script_field`)

    Returns ``(fields, coverage)`` where *coverage* is
    ``{"resolved": N, "total": M, "broken": B}`` for path-based fields.
    """
    result: dict[str, Any] = {}

    # Pass 0: auto-import keys from path_prefix data dict as vars; declared
    # fields override these in subsequent passes.
    if schema.path_prefix:
        prefix_data = resolve_field(schema.path_prefix, raw)
        if isinstance(prefix_data, dict):
            result.update(prefix_data)
        ts = resolve_field(_metadata_path(schema.path_prefix), raw)
        if ts and "collected_at" not in result:
            result["collected_at"] = ts

    _broken_paths: frozenset[str] = schema._broken_paths

    path_total = 0
    path_resolved = 0
    path_broken = 0

    # Pass 1: const fields.
    for name, spec in schema.fields.items():
        if spec.const is not _SENTINEL_UNSET:
            result[name] = spec.const

    # Pass 2: path-based fields (override auto-imported vars). Paths that
    # are provably broken at schema-load time render the type-appropriate
    # sentinel so the report surfaces the gap rather than masking it.
    for name, spec in schema.fields.items():
        if spec.path is not None:
            path_total += 1
            raw_value = resolve_field(spec.path, raw)
            if raw_value is None and name in _broken_paths:
                result[name] = _get_sentinel(spec)
                path_broken += 1
            else:
                result[name] = _coerce(raw_value, spec.type, spec.fallback)
                if raw_value is not None:
                    path_resolved += 1

    # Pass 3: compute / normalize / template fields in topological order
    # — each producer evaluated exactly once.
    for name in _producer_order(schema):
        spec = schema.fields[name]
        try:
            if spec.compute is not None:
                result[name] = eval_compute(spec.compute, result)
            elif spec.normalize is not None:
                value = eval_normalize(spec.normalize, result)
                result[name] = _coerce(value, spec.type, spec.fallback)
            elif spec.template is not None:
                value = _eval_template_field(spec.template, result)
                result[name] = _coerce(value, spec.type, spec.fallback)
        except Exception as exc:
            logger.warning("field '%s' failed: %s", name, exc)
            result[name] = _get_sentinel(spec)

    # Pass 4: script fields (with result caching for identical script+args)
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
            # Cache key: (resolved_path, frozen args) — avoids re-running identical invocations.
            # ``_extract_key`` is a reporter-side unpack hint added by script_bundles,
            # not an input to the script itself, so exclude it from the invocation
            # args and cache key. This lets one script return a dict used by many
            # fields without being executed once per unpacked key.
            script_args = dict(ss.args or {})
            extract_key = script_args.pop("_extract_key", None)
            cache_key = (
                str(script_path),
                frozenset((k, repr(v)) for k, v in sorted(script_args.items())),
            )
            if cache_key in _script_cache:
                value = _script_cache[cache_key]
            else:
                value = _run_script_field(script_path, result, script_args, ss.timeout)
                _script_cache[cache_key] = value
            if value is _SCRIPT_ERROR_SENTINEL:
                result[name] = _get_sentinel(spec)
            else:
                if extract_key and isinstance(value, dict):
                    value = value.get(extract_key)
                result[name] = _coerce(value, spec.type, spec.fallback)

    coverage = {"resolved": path_resolved, "total": path_total, "broken": path_broken}
    return result, coverage


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
            for ref in sorted(_jinja_referenced_names(rule.when)):
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
        widgets_meta[widget.slug] = {
            "slug": widget.slug,
            "name": widget.name,
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
