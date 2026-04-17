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

# Alias mappings: {definition_name: {canonical_field: [aliases]}}
# Sourced from AliasChoices declarations in the Pydantic models.
_ALIASES: dict[str, dict[str, list[str]]] = {
    "AlertRule": {"msg": ["message"]},
    "FieldSpec": {"path": ["from"], "compute": ["expr"]},
    "ScriptSpec": {"path": ["run"], "args": ["script_args"], "timeout": ["script_timeout"]},
    "TableWidget": {"rows_field": ["rows"]},
    "GroupedTableWidget": {"rows_field": ["rows"]},
    "DetectionSpec": {"keys_any": ["any"], "keys_all": ["all"]},
    "ReportSchema": {"display_name": ["title"], "fields": ["vars"]},
}


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


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "schemas"
    out_dir.mkdir(exist_ok=True)

    # 1. Generate the report-schema JSON (applies aliases to $defs + root props).
    report_schema = ReportSchema.model_json_schema()
    _add_aliases(report_schema)

    # 2. Generate the alert-rule JSON and extract its AlertRule definition so
    #    we can embed it as a second oneOf branch in the unified schema.
    alert_schema = AlertRule.model_json_schema()
    report_defs = report_schema.setdefault("$defs", {})
    for def_name, defn in alert_schema.get("$defs", {}).items():
        report_defs.setdefault(def_name, defn)
    # AlertRule itself lives at the top level of its own schema — move to $defs.
    alert_rule_def = {k: v for k, v in alert_schema.items() if k != "$defs"}
    report_defs["AlertRule"] = alert_rule_def

    # 3. Build the unified oneOf root: accept either a full report config
    #    (object) or a bare alert list (array of AlertRule).
    report_body = {k: v for k, v in report_schema.items() if k not in {"$schema", "$defs", "title", "description"}}
    unified: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "NCS Reporter Config",
        "description": (
            "YAML-driven report schema for ncs_reporter. Accepts either a full "
            "report config (object) or a standalone alert list (array of AlertRule)."
        ),
        "oneOf": [
            report_body,
            {
                "type": "array",
                "items": {"$ref": "#/$defs/AlertRule"},
                "description": "Standalone alert list — included via $include in main configs.",
            },
        ],
        "$defs": report_defs,
    }

    out_path = out_dir / "ncs_reporter_config_schema.json"
    out_path.write_text(json.dumps(unified, indent=2) + "\n")
    print(f"Wrote {out_path}")

    # Remove any superseded single-purpose schemas so the source of truth is clear.
    for stale in ("report_schema.json", "alert_list_schema.json"):
        stale_path = out_dir / stale
        if stale_path.exists():
            stale_path.unlink()
            print(f"Removed stale {stale_path}")


if __name__ == "__main__":
    main()
