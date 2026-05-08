#!/usr/bin/env python3
"""Generate JSON Schema from Pydantic models for YAML editor autocomplete.

Post-processes the Pydantic-generated schema to accept YAML authoring
aliases (``message`` for ``msg``, ``vars`` for ``fields``, etc.) that
Pydantic's ``AliasChoices`` supports at runtime but ``model_json_schema``
does not emit.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from ncs_reporter.models.report_schema import AlertRule, ReportSchema  # noqa: E402
from ncs_reporter.normalization._normalize_dsl import (  # noqa: E402
    _DISPATCH_ORDER,
    _NORMALIZE_OP_SCHEMAS,
    _OP_VALUE_DEF,
)

# Alias mappings: {definition_name: {canonical_field: [aliases]}}
# Sourced from AliasChoices declarations in the Pydantic models.
_ALIASES: dict[str, dict[str, list[str]]] = {
    "AlertRule": {"msg": ["message"]},
    "FieldSpec": {"path": ["from"], "compute": ["expr"]},
    "ScriptSpec": {"path": ["run"], "args": ["script_args"], "timeout": ["script_timeout"]},
    "TableWidget": {"rows_field": ["rows"]},
    "GroupedTableWidget": {"rows_field": ["rows"]},
    "InventorySection": {"rows_field": ["rows"]},
    "DetectionSpec": {"keys_any": ["any"], "keys_all": ["all"]},
    "ReportSchema": {"display_name": ["title"], "fields": ["vars"]},
}


# Descriptions injected into the generated JSON schema for editor hover-hints
# and autocomplete sidebar text. Sourced from `docs/ncs-reporter-config/`.
# Each entry: (def_name OR "ReportSchema") -> {property: description}.
# "ReportSchema" entries land on the top-level properties.
# Descriptions for *alias-only* properties — the canonical fields' descriptions
# now live on the Pydantic models themselves (Field(description=...)). Aliases
# are synthesized in _add_aliases() so they need a separate registry.
_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "ReportSchema": {
        "title": "Alias for `display_name:` — title shown in report headers and dashboards.",
        "vars": "Alias for `fields:` — field definitions block.",
        "config": "Inline metadata block (display_name, platform, detection, stig, …). Keys are merged into the schema root by the loader.",
    },
    "FieldSpec": {
        "from": "Alias for `path:` — dotted-path lookup into the raw bundle.",
        "expr": "Alias for `compute:` — Jinja2 expression over other fields.",
    },
    "AlertRule": {
        "message": "Alias for `msg:` — alert message template.",
    },
    "DetectionSpec": {
        "any": "Alias for `keys_any:`.",
        "all": "Alias for `keys_all:`.",
    },
    "TableWidget": {
        "rows": "Alias for `rows_field:` — Jinja2 expression returning the row list.",
    },
    "GroupedTableWidget": {
        "rows": "Alias for `rows_field:` — Jinja2 expression returning the row list.",
    },
    "InventorySection": {
        "rows": "Alias for `rows_field:` — Jinja2 expression returning the row list.",
    },
}


# Def-level descriptions are now Pydantic class docstrings — no parallel
# registry needed. Keep this dict empty for the import to remain resolvable
# until other callers are removed.
_DEF_DESCRIPTIONS: dict[str, str] = {}


# Top-level + per-def YAML examples shown in editor hover tooltips and
# (when supported) inline completion previews.
_EXAMPLES: dict[str, dict[str, list]] = {
    # Top-level minimal valid config.
    "ReportSchema": {
        "config": [
            {
                "platform": "myplatform",
                "display_name": "My Platform",
                "detection": {"keys_any": ["raw_myplatform"]},
            }
        ],
        "vars": [
            {
                "uptime_days": {"compute": "{{ uptime_seconds / 86400 }}"},
                "cpu_load_pct": {"path": ".cpu.load_avg_1m", "type": "float", "thresholds": {"warn_if_above": 70, "crit_if_above": 90}},
            }
        ],
        "alerts": [
            [
                {"id": "cpu_hot", "category": "Health", "severity": "CRITICAL", "when": "cpu_load_pct >= 90", "msg": "CPU load {{ cpu_load_pct | round(1) }}% on {{ hostname }}"}
            ]
        ],
        "widgets": [
            [
                {"type": "stat-cards", "cards": [{"name": "Uptime (d)", "value": "{{ uptime_days | round(0) }}"}]}
            ]
        ],
    },
    "FieldSpec": {
        "path": ["ansible_facts.hostname", ".cpu.load_avg_1m | to_float"],
        "compute": ["{{ uptime_seconds / 86400 }}", "{{ (mem_total - mem_free) / mem_total * 100 }}"],
    },
    "AlertRule": {
        "id": ["cpu_hot", "disk_near_full"],
        "severity": ["CRITICAL", "WARNING", "INFO"],
        "when": ["cpu_load_pct >= 90", "disks | selectattr('used_pct', 'gt', 90) | list | length > 0"],
        "msg": ["CPU load {{ cpu_load_pct | round(1) }}% on {{ hostname }}"],
    },
    # Per-widget `type:` examples were dropped — the schema already
    # enforces the canonical/hyphen literal via `enum:`, so an example
    # added nothing. If newcomer-facing widget skeletons are wanted later,
    # add them under the widget def's `name:` / `columns:` slots.
}


def _resolve_def_target(schema: dict, def_name: str) -> dict | None:
    """Return the object dict for `def_name`, drilling into `anyOf` if wrapped."""
    if def_name == "ReportSchema":
        return schema
    defs = schema.get("$defs", {})
    target = defs.get(def_name)
    if not isinstance(target, dict):
        return None
    if isinstance(target.get("properties"), dict):
        return target
    for branch in target.get("anyOf", []):
        if isinstance(branch, dict) and isinstance(branch.get("properties"), dict):
            return branch
    return target


def _annotate_schema(schema: dict) -> None:
    """Inject descriptions + examples in a single walk over each $def.

    `_DESCRIPTIONS` and `_EXAMPLES` both key on `(def_name, property)` and
    drill into the same `_resolve_def_target` slot. `_DEF_DESCRIPTIONS`
    sets the def-level description (overwriting any Pydantic docstring so
    the user-facing copy is authoritative).
    """
    for def_name in {*_DESCRIPTIONS, *_DEF_DESCRIPTIONS, *_EXAMPLES}:
        target = _resolve_def_target(schema, def_name)
        if not target:
            continue
        if def_name in _DEF_DESCRIPTIONS:
            target["description"] = _DEF_DESCRIPTIONS[def_name]
        props = target.get("properties")
        if not isinstance(props, dict):
            continue
        for prop_name, desc in _DESCRIPTIONS.get(def_name, {}).items():
            spec = props.get(prop_name)
            if isinstance(spec, dict) and not spec.get("description"):
                spec["description"] = desc
        for prop_name, examples in _EXAMPLES.get(def_name, {}).items():
            spec = props.get(prop_name)
            if isinstance(spec, dict) and "examples" not in spec:
                spec["examples"] = examples


def _add_aliases(schema: dict) -> None:
    """Walk $defs and add alias properties alongside canonical names."""
    defs = schema.get("$defs", {})
    for def_name, aliases in _ALIASES.items():
        defn = defs.get(def_name) or (schema if def_name == "ReportSchema" else None)
        if not defn:
            continue
        props = defn.get("properties", {})
        required = defn.get("required", [])
        for canonical, alias_list in aliases.items():
            if canonical not in props:
                continue
            for alias in alias_list:
                if alias not in props:
                    props[alias] = props[canonical]
            # Don't require the canonical name — the alias satisfies it
            if canonical in required:
                required.remove(canonical)

    # Top-level: accept config: wrapper (unwrapped by _normalise_top_level)
    top_props = schema.get("properties", {})
    if "config" not in top_props:
        top_props["config"] = {"type": "object", "title": "Config", "description": "Top-level config block (keys are merged into the schema root)."}

    # Relax additionalProperties on ReportSchema to allow config/vars passthrough
    schema.pop("additionalProperties", None)

    # Accept hyphenated widget type values (key-value, stat-cards, etc.)
    # The model_validator normalises hyphens → underscores at runtime.
    for def_name in defs:
        defn = defs[def_name]
        type_prop = defn.get("properties", {}).get("type", {})
        if "const" in type_prop and "_" in str(type_prop["const"]):
            canonical = type_prop["const"]
            hyphenated = canonical.replace("_", "-")
            type_prop.pop("const")
            type_prop["enum"] = [canonical, hyphenated]

    # Accept string shorthand for WidgetLayout (e.g. layout: half)
    # The model_validator converts "half" → {"width": "half"} at runtime.
    for def_name in defs:
        defn = defs[def_name]
        props = defn.get("properties", {})
        layout = props.get("layout")
        if layout and layout.get("$ref", "").endswith("/WidgetLayout"):
            props["layout"] = {
                "anyOf": [
                    {"$ref": "#/$defs/WidgetLayout"},
                    {"type": "string", "enum": ["full", "half", "third", "quarter"]},
                ],
                "default": "full",
            }

    # Accept $include strings where arrays or dicts are expected.
    # The schema_loader resolves $include at load time before validation.
    top_props = schema.get("properties", {})
    for prop_name in ("alerts", "widgets"):
        prop = top_props.get(prop_name, {})
        if prop.get("type") == "array":
            items = prop.pop("items", None)
            prop.pop("type", None)
            prop["anyOf"] = [
                {"type": "array", **({"items": items} if items else {})},
                {"type": "object", "properties": {"$include": {"type": "string"}}, "additionalProperties": False},
            ]
    # vars/fields: accept dict of FieldSpec OR $include object OR bare strings
    for prop_name in ("fields", "vars"):
        prop = top_props.get(prop_name, {})
        if prop:
            top_props[prop_name] = {
                "anyOf": [
                    prop,
                    {"type": "object", "additionalProperties": True},
                ],
            }

    # FieldSpec: accept bare string shorthand (path-only)
    field_spec = defs.get("FieldSpec", {})
    if field_spec:
        defs["FieldSpec"] = {
            "anyOf": [
                field_spec,
                {"type": "string", "description": "Shorthand for {path: <value>}"},
            ],
        }

    # Inject a typed NormalizeSpec definition so IDEs can autocomplete
    # the DSL ops inside `normalize:`. Pydantic emits this field as
    # `dict[str, Any]`; the schema is generated from the DSL's own
    # ``_DISPATCH_ORDER`` + ``_NORMALIZE_OP_SCHEMAS`` in
    # ``_normalize_dsl.py`` so the operator surface stays in lockstep.
    # `OpValue` is a single shared definition every operator's value
    # slot references — keeps the on-disk schema compact.
    defs["OpValue"] = _OP_VALUE_DEF
    defs["NormalizeSpec"] = _build_normalize_spec()
    # FieldSpec was wrapped in `anyOf` above to accept the string-shorthand
    # form; `_resolve_def_target` drills into the canonical (object) branch.
    canonical = _resolve_def_target(schema, "FieldSpec")
    if canonical is not None:
        props = canonical.setdefault("properties", {})
        if "normalize" in props:
            props["normalize"] = {
                "anyOf": [
                    {"$ref": "#/$defs/NormalizeSpec"},
                    {"type": "object"},  # forward-compat: unknown ops still load
                    {"type": "null"},
                ],
                "description": (
                    "Declarative normalization DSL — see "
                    "docs/ncs-reporter-config/FIELDS.md `normalize:` for the "
                    "full operator reference."
                ),
            }


def _build_normalize_spec() -> dict:
    """Typed JSON Schema for the normalize: DSL.

    Generated directly from the DSL's own ``_DISPATCH_ORDER`` +
    ``_NORMALIZE_OP_SCHEMAS`` so the editor surface stays in lockstep
    with the evaluator. Each branch is a single-key dict (or the
    ``if``+``then``+``else`` / ``first_of``+``default`` triples) so
    editors can surface the available ops via autocompletion. The schema
    does not enforce mutual exclusion of branches because the DSL
    evaluator short-circuits on the first matched key — overspecifying
    would block valid configs.
    """
    branches: list[dict] = []
    for op_key in _DISPATCH_ORDER:
        fragment = _NORMALIZE_OP_SCHEMAS.get(op_key)
        if fragment is None:
            continue
        properties: dict = {op_key: fragment["value"]}
        if "extra_props" in fragment:
            properties.update(fragment["extra_props"])
        branches.append({"type": "object", "properties": properties, "required": [op_key]})
    return {
        "title": "NormalizeSpec",
        "description": (
            "Declarative DSL for shaping raw collector output. Exactly "
            "one operator key per dict — see "
            "docs/ncs-reporter-config/FIELDS.md `normalize:` for the "
            "operator reference."
        ),
        "anyOf": branches,
    }


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "schemas"
    out_dir.mkdir(exist_ok=True)

    # 1. Generate the report-schema JSON.
    report_schema = ReportSchema.model_json_schema()

    # 2. Inject AlertRule before alias/annotation passes — AlertRule has
    #    its own AliasChoices (`message` → `msg`) that need the alias
    #    pass to surface, and its property descriptions live in the
    #    Pydantic model.
    alert_schema = AlertRule.model_json_schema()
    report_defs = report_schema.setdefault("$defs", {})
    for def_name, defn in alert_schema.get("$defs", {}).items():
        report_defs.setdefault(def_name, defn)
    alert_rule_def = {k: v for k, v in alert_schema.items() if k != "$defs"}
    report_defs["AlertRule"] = alert_rule_def

    # 3. Aliases first (so alias-only descriptions can override on the
    #    canonical-shared dict reference), then annotations.
    _add_aliases(report_schema)
    _annotate_schema(report_schema)

    # 3a. Main schema: the full report-config object. Root is a single
    #     object so yaml-language-server (Zed, VS Code) can offer
    #     property completion at the top level. Alert-only `$include`
    #     partials use the sibling `alert_list_schema.json` instead.
    report_body = {k: v for k, v in report_schema.items() if k not in {"$schema", "title", "description"}}
    main_schema: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "NCS Reporter Config",
        "description": "YAML-driven report schema for ncs_reporter (full report config).",
        **report_body,
    }
    out_path = out_dir / "ncs_reporter_config_schema.json"
    out_path.write_text(json.dumps(main_schema, indent=2) + "\n")
    print(f"Wrote {out_path}")

    # 3b. Sibling schema for `*_base_alerts.yaml` partials — bare array
    #     of AlertRule. Configs that are alert-only point at this file
    #     via `# yaml-language-server: $schema=../../.schemas/alert_list_schema.json`.
    alert_list_schema: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "NCS Reporter Alert List",
        "description": "Standalone alert list — included via $include in main configs.",
        "type": "array",
        "items": {"$ref": "#/$defs/AlertRule"},
        "$defs": report_defs,
    }
    alert_path = out_dir / "alert_list_schema.json"
    alert_path.write_text(json.dumps(alert_list_schema, indent=2) + "\n")
    print(f"Wrote {alert_path}")

    # Remove any superseded single-purpose schemas so the source of truth is clear.
    stale_path = out_dir / "report_schema.json"
    if stale_path.exists():
        stale_path.unlink()
        print(f"Removed stale {stale_path}")


if __name__ == "__main__":
    main()
