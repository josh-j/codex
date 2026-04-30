from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ncs_reporter.pathing import validate_template

# ---------------------------------------------------------------------------
# Canonical filenames and prefixes (single source of truth)
# ---------------------------------------------------------------------------

FILENAME_SITE_HEALTH = "site.html"
FILENAME_STIG_FLEET = "site.stig.html"


def host_report_basename(hostname: str) -> str:
    """Filename a per-host HTML report lands at inside its own directory."""
    return f"{hostname}.html"


def host_report_historical_basename(hostname: str, report_stamp: str) -> str:
    return f"{hostname}_{report_stamp}.html"
NAV_LABEL_STIG = "STIG"
CKLB_SKELETONS_DIR = "cklb_skeletons"

# Jinja2 template names
TEMPLATE_NODE = "generic_node_report.html.j2"
TEMPLATE_FLEET = "generic_fleet_report.html.j2"
TEMPLATE_SITE = "site_health_report.html.j2"
TEMPLATE_STIG_HOST = "stig_host_report.html.j2"
TEMPLATE_STIG_FLEET = "stig_fleet_report.html.j2"

def stig_host_url(target_type: str, hostname: str, back_to_root: str = "") -> str:
    return f"{back_to_root}stig/{target_type}/{hostname}/{hostname}_stig_{target_type}.html"


def stig_fleet_url(back_to_root: str = "") -> str:
    return f"{back_to_root}{FILENAME_STIG_FLEET}"


def site_report_url(back_to_root: str = "") -> str:
    return f"{back_to_root}{FILENAME_SITE_HEALTH}"


def raw_stig_artifact_path(hostname: str, target_type: str) -> str:
    return f"stig/{target_type}/{hostname}/raw_stig_{target_type}.yaml"


DEFAULT_PATH_TEMPLATES: dict[str, str] = {
    "raw_stig_artifact": "stig/{target_type}/{hostname}/raw_stig_{target_type}.yaml",
    "report_fleet": "{report_dir}/{schema_name}.html",
    "report_node_latest": "{report_dir}/{hostname}/{hostname}.html",
    "report_node_historical": "{report_dir}/{hostname}/{hostname}_{report_stamp}.html",
    "report_stig_host": "stig/{target_type}/{hostname}/{hostname}_stig_{target_type}.html",
    "report_search_entry": "{report_dir}/{hostname}/{hostname}.html",
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
            required={"hostname", "target_type"},
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
            required={"hostname", "target_type"},
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
    render: bool = True
    schema_name: str | None = None  # overrides platform-based schema lookup
    paths: PlatformPaths = None  # type: ignore[assignment]  # filled by before-validator
    display_name: str | None = None  # human label; defaults to platform.capitalize()
    schema_names: list[str] = []  # schema name preference; defaults to [platform]
    stig_platform_to_checklist: dict[str, str] = {}  # target_type -> skeleton relative path
    stig_rule_prefix_to_platform: dict[str, str] = {}  # rule_version prefix -> target_type
    stig_playbook: str = ""
    stig_target_var: str = ""

    @property
    def state_file(self) -> str:
        return f"{self.platform}_fleet_state.yaml"

    @property
    def site_audit_key(self) -> str | None:
        if self.render and self.schema_names:
            return self.schema_names[0]
        return None

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

        # display_name
        if not values.get("display_name"):
            values["display_name"] = platform.capitalize() if platform else None

        # schema_names
        if not values.get("schema_names") and platform:
            values["schema_names"] = [platform]

        return values


@dataclasses.dataclass
class PlatformNode:
    """Runtime tree node wrapping a PlatformEntry with explicit parent/child links.

    Leaf nodes are platforms with no children (linux, windows).
    Branch nodes are parents with children (vmware → vcsa, esxi, vm).
    """

    entry: PlatformEntry
    parent: PlatformNode | None = None
    children: list[PlatformNode] = dataclasses.field(default_factory=list)

    @property
    def id(self) -> str:
        """Unique identifier: schema_name for primary entries, platform for others."""
        return self.entry.schema_name or self.entry.platform

    @property
    def display_name(self) -> str:
        # PlatformEntry._apply_defaults always populates display_name.
        return self.entry.display_name  # type: ignore[return-value]

    @property
    def is_root(self) -> bool:
        return self.parent is None

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    @property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def ancestors(self) -> list[PlatformNode]:
        """Walk up to root, returning [root, ..., parent] (excludes self)."""
        result: list[PlatformNode] = []
        node = self.parent
        while node is not None:
            result.append(node)
            node = node.parent
        result.reverse()
        return result

    def siblings(self) -> list[PlatformNode]:
        """Other children of the same parent (excludes self)."""
        if self.parent is None:
            return []
        return [c for c in self.parent.children if c is not self]

    def walk(self) -> Iterator[PlatformNode]:
        """Pre-order traversal of this subtree."""
        yield self
        for child in self.children:
            yield from child.walk()


class PlatformsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platforms: list[PlatformEntry]
