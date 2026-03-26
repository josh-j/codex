#!/usr/bin/env python3
"""Generate JSON Schema from Pydantic models for YAML editor autocomplete."""

from __future__ import annotations

import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from ncs_reporter.models.report_schema import AlertRule, ReportSchema  # noqa: E402


def main() -> None:
    out_dir = Path(__file__).resolve().parent / "schemas"
    out_dir.mkdir(exist_ok=True)

    # Main schema (vcsa.yaml, windows.yaml, esxi.yaml, etc.)
    schema = ReportSchema.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "NCS Reporter Schema Config"
    schema["description"] = "YAML-driven report schema for ncs_reporter."

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

    alert_path = out_dir / "alert_list_schema.json"
    alert_path.write_text(json.dumps(alert_list_schema, indent=2) + "\n")
    print(f"Wrote {alert_path}")


if __name__ == "__main__":
    main()
