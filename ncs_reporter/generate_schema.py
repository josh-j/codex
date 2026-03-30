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


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "schemas"
    out_dir.mkdir(exist_ok=True)

    # Main schema (vcsa.yaml, windows.yaml, esxi.yaml, etc.)
    schema = ReportSchema.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "NCS Reporter Schema Config"
    schema["description"] = "YAML-driven report schema for ncs_reporter."
    _add_aliases(schema)

    main_path = out_dir / "report_schema.json"
    main_path.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"Wrote {main_path}")

    # Alert list schema (linux_base_alerts.yaml, etc.)
    alert_schema = AlertRule.model_json_schema()
    alert_list_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "NCS Reporter Alert List",
        "description": "A list of alert rules, included via $include in main config files.",
        "type": "array",
        "items": {"$ref": "#/$defs/AlertRule"},
        "$defs": alert_schema.get("$defs", {}),
    }
    # If AlertRule is the root, put it in $defs
    if "$defs" not in alert_schema:
        alert_list_schema["$defs"] = {"AlertRule": alert_schema}
    else:
        alert_list_schema["$defs"]["AlertRule"] = {
            k: v for k, v in alert_schema.items() if k != "$defs"
        }
    _add_aliases(alert_list_schema)

    alert_path = out_dir / "alert_list_schema.json"
    alert_path.write_text(json.dumps(alert_list_schema, indent=2) + "\n")
    print(f"Wrote {alert_path}")


if __name__ == "__main__":
    main()
