from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ncs_reporter.pathing import validate_template

# ---------------------------------------------------------------------------
# Canonical filenames and prefixes (single source of truth)
# ---------------------------------------------------------------------------

PLATFORM_DIR_PREFIX = "platform"
FILENAME_HEALTH_REPORT = "health_report.html"
FILENAME_SITE_HEALTH = "site_health_report.html"
FILENAME_STIG_FLEET = "stig_fleet_report.html"
FILENAME_FLEET_SUFFIX = "_fleet_report.html"
CKLB_SKELETONS_DIR = "cklb_skeletons"

# Jinja2 template names
TEMPLATE_NODE = "generic_node_report.html.j2"
TEMPLATE_FLEET = "generic_fleet_report.html.j2"
TEMPLATE_SITE = "site_health_report.html.j2"
TEMPLATE_STIG_HOST = "stig_host_report.html.j2"
TEMPLATE_STIG_FLEET = "stig_fleet_report.html.j2"

def fleet_link_url(report_dir: str, schema_name: str, back_to_root: str = "") -> str:
    """Build a fleet report URL from components."""
    return f"{back_to_root}{PLATFORM_DIR_PREFIX}/{report_dir}/{schema_name}{FILENAME_FLEET_SUFFIX}"


DEFAULT_PATH_TEMPLATES: dict[str, str] = {
    "raw_stig_artifact": f"{PLATFORM_DIR_PREFIX}/{{report_dir}}/{{hostname}}/raw_stig_{{target_type}}.yaml",
    "report_fleet": f"{PLATFORM_DIR_PREFIX}/{{report_dir}}/{{schema_name}}{FILENAME_FLEET_SUFFIX}",
    "report_node_latest": f"{PLATFORM_DIR_PREFIX}/{{report_dir}}/{{hostname}}/{FILENAME_HEALTH_REPORT}",
    "report_node_historical": f"{PLATFORM_DIR_PREFIX}/{{report_dir}}/{{hostname}}/health_report_{{report_stamp}}.html",
    "report_stig_host": f"{PLATFORM_DIR_PREFIX}/{{report_dir}}/{{hostname}}/{{hostname}}_stig_{{target_type}}.html",
    "report_search_entry": f"{PLATFORM_DIR_PREFIX}/{{report_dir}}/{{hostname}}/{FILENAME_HEALTH_REPORT}",
    "report_site": FILENAME_SITE_HEALTH,
    "report_stig_fleet": FILENAME_STIG_FLEET,
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
    # Legacy raw data key aliases (canonical_key -> legacy_key)
    legacy_raw_keys: dict[str, str] = {}
    # Legacy schema audit key alias (for site dashboard _get_schema_audit lookup)
    legacy_audit_key: str | None = None
    # Site dashboard: fields to aggregate into infra dict (VMware-specific use case)
    site_infra_fields: list[str] = []
    # Site dashboard: whether this platform contributes compute_node rows
    site_compute_node: bool = False
    # STIG apply: playbook path and target variable name
    stig_playbook: str = ""
    stig_target_var: str = ""

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
                values["fleet_link"] = fleet_link_url(report_dir, schema)

        return values


class PlatformsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[PlatformEntry]
