from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ncs_reporter.pathing import validate_template

DEFAULT_PATH_TEMPLATES: dict[str, str] = {
    "raw_stig_artifact": "platform/{report_dir}/{hostname}/raw_stig_{target_type}.yaml",
    "report_fleet": "platform/{report_dir}/{schema_name}_fleet_report.html",
    "report_node_latest": "platform/{report_dir}/{hostname}/health_report.html",
    "report_node_historical": "platform/{report_dir}/{hostname}/health_report_{report_stamp}.html",
    "report_stig_host": "platform/{report_dir}/{hostname}/{hostname}_stig_{target_type}.html",
    "report_search_entry": "platform/{report_dir}/{hostname}/health_report.html",
    "report_site": "site_health_report.html",
    "report_stig_fleet": "stig_fleet_report.html",
}


class PlatformPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_stig_artifact: str
    report_fleet: str
    report_node_latest: str
    report_node_historical: str
    report_stig_host: str
    report_search_entry: str
    report_site: str
    report_stig_fleet: str

    @field_validator("*")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("path template must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _validate_templates(self) -> PlatformPaths:
        all_allowed = {"report_dir", "hostname", "schema_name", "target_type", "report_stamp"}
        validate_template(
            self.raw_stig_artifact,
            allowed=all_allowed,
            required={"report_dir", "hostname", "target_type"},
            field_name="paths.raw_stig_artifact",
        )
        validate_template(
            self.report_fleet,
            allowed=all_allowed,
            required={"report_dir", "schema_name"},
            field_name="paths.report_fleet",
        )
        validate_template(
            self.report_node_latest,
            allowed=all_allowed,
            required={"report_dir", "hostname"},
            field_name="paths.report_node_latest",
        )
        validate_template(
            self.report_node_historical,
            allowed=all_allowed,
            required={"report_dir", "hostname", "report_stamp"},
            field_name="paths.report_node_historical",
        )
        validate_template(
            self.report_stig_host,
            allowed=all_allowed,
            required={"report_dir", "hostname", "target_type"},
            field_name="paths.report_stig_host",
        )
        validate_template(
            self.report_search_entry,
            allowed=all_allowed,
            required={"report_dir", "hostname"},
            field_name="paths.report_search_entry",
        )
        validate_template(
            self.report_site,
            allowed=all_allowed,
            required=set(),
            field_name="paths.report_site",
        )
        validate_template(
            self.report_stig_fleet,
            allowed=all_allowed,
            required=set(),
            field_name="paths.report_stig_fleet",
        )
        return self


class PlatformEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_dir: str
    report_dir: str
    platform: str
    state_file: str = ""
    render: bool = True
    schema_name: str | None = None  # overrides platform-based schema lookup
    target_types: list[str]
    paths: PlatformPaths = None  # type: ignore[assignment]  # filled by before-validator
    # Extensibility metadata (all optional with sensible defaults)
    display_name: str | None = None  # human label; defaults to platform.capitalize()
    asset_label: str = "Nodes"  # "Nodes", "vCenters", etc.
    inventory_groups: list[str] = []  # groups to count for site dashboard
    schema_names: list[str] = []  # schema name preference; defaults to [platform]
    stig_skeleton_map: dict[str, str] = {}  # target_type -> skeleton filename
    stig_rule_prefixes: dict[str, str] = {}  # rule_version prefix -> target_type
    site_audit_key: str | None = None  # schema key for site dashboard lookup
    site_category: str | None = None  # alert category label for site dashboard
    fleet_link: str | None = None  # explicit fleet dashboard link override

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        platform = values.get("platform", "")

        # paths: merge missing keys from defaults
        paths = values.get("paths")
        if paths is None:
            values["paths"] = dict(DEFAULT_PATH_TEMPLATES)
        elif isinstance(paths, dict):
            merged = dict(DEFAULT_PATH_TEMPLATES)
            merged.update(paths)
            values["paths"] = merged

        # state_file
        if not values.get("state_file"):
            values["state_file"] = f"{platform}_fleet_state.yaml"

        # display_name
        if not values.get("display_name"):
            values["display_name"] = platform.capitalize() if platform else None

        # schema_names
        if not values.get("schema_names") and platform:
            values["schema_names"] = [platform]

        # Only auto-derive site dashboard fields for renderable entries
        render = values.get("render", True)
        schema_names = values.get("schema_names", [])

        # site_audit_key
        if not values.get("site_audit_key") and schema_names and render is not False:
            values["site_audit_key"] = schema_names[0]

        # site_category
        if not values.get("site_category") and values.get("site_audit_key"):
            values["site_category"] = values.get("display_name")

        # fleet_link
        if not values.get("fleet_link") and render is not False:
            report_dir = values.get("report_dir", "")
            schema = schema_names[0] if schema_names else platform
            if report_dir and schema:
                values["fleet_link"] = f"platform/{report_dir}/{schema}_fleet_report.html"

        return values


class PlatformsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[PlatformEntry]
