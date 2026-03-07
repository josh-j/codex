"""Data-driven platform registry.

Centralizes all platform metadata lookups that were previously hardcoded
across cli.py, aggregation.py, view_models/, and normalization/.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from ncs_reporter.models.report_schema import ReportSchema

from ncs_reporter.models.platforms_config import PlatformEntry, PlatformsConfig


class PlatformRegistry:
    """Read-only accessor over a list of ``PlatformEntry`` objects."""

    def __init__(self, entries: list[PlatformEntry]) -> None:
        self._entries = list(entries)

    # -- basic accessors -----------------------------------------------------

    @property
    def entries(self) -> list[PlatformEntry]:
        return list(self._entries)

    def by_platform(self, name: str) -> list[PlatformEntry]:
        return [e for e in self._entries if e.platform == name]

    # -- platform / target type sets -----------------------------------------

    def all_platform_names(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for e in self._entries:
            if e.platform not in seen:
                seen.add(e.platform)
                out.append(e.platform)
        return out

    def all_target_types(self) -> set[str]:
        return {t for e in self._entries for t in e.target_types}

    # -- schema name lookup --------------------------------------------------

    def schema_names_for_platform(self, platform: str) -> list[str]:
        for e in self._entries:
            if e.platform == platform and e.schema_names:
                return list(e.schema_names)
        return [platform]

    # -- aggregation helpers -------------------------------------------------

    def host_exclude_set(self) -> set[str]:
        """Build the set of directory/file names to skip when walking host dirs."""
        structural = {
            "platform",
            "all_hosts_state.yaml",
        }
        for e in self._entries:
            structural.add(e.platform)
            # Add path components from input_dir and report_dir
            for path_str in (e.input_dir, e.report_dir):
                for part in path_str.split("/"):
                    if part:
                        structural.add(part)
            structural.add(e.state_file)
            # state file without extension
            if e.state_file.endswith(".yaml"):
                structural.add(e.state_file[:-5])
        return structural

    def skip_keys_set(self) -> set[str]:
        """Build the set of keys to skip when iterating host bundles in view models."""
        structural = {
            "summary",
            "split",
            "platform",
            "history",
            "raw_state",
            "all_hosts_state",
            "all_hosts_state.yaml",
        }
        for e in self._entries:
            structural.add(e.platform)
            structural.add(e.state_file)
            if e.state_file.endswith(".yaml"):
                structural.add(e.state_file[:-5])
        return structural

    # -- STIG skeleton / rule prefix lookups ---------------------------------

    def stig_skeleton_for_target(self, target_type: str) -> str | None:
        for e in self._entries:
            if target_type in e.stig_skeleton_map:
                return e.stig_skeleton_map[target_type]
        return None

    def infer_target_type_from_rule_prefix(self, rule_version: str) -> str:
        rv = rule_version.upper()
        for e in self._entries:
            for prefix, target_type in e.stig_rule_prefixes.items():
                if rv.startswith(prefix.upper()):
                    return target_type
        return ""

    def infer_platform_from_target_type(self, target_type: str) -> str:
        tt = target_type.lower()
        for e in self._entries:
            if tt in (t.lower() for t in e.target_types):
                return e.platform
        return "unknown"

    def entry_for_target_type(self, target_type: str) -> PlatformEntry | None:
        """Return the platform entry that owns a given target_type."""
        tt = target_type.lower()
        for e in self._entries:
            if tt in (t.lower() for t in e.target_types):
                return e
        return None

    # -- site dashboard helpers -----------------------------------------------

    def site_dashboard_entries(self) -> list[PlatformEntry]:
        """Return entries that contribute to the site dashboard (have site_audit_key)."""
        return [e for e in self._entries if e.site_audit_key]

    def count_inventory_assets(self, entry: PlatformEntry, groups: dict[str, Any]) -> int:
        for group_name in entry.inventory_groups:
            members = groups.get(group_name)
            if members:
                return len(list(members))
        return 0

    # -- STIG fleet nav / link helpers ----------------------------------------

    def platform_fleet_link(self, platform: str) -> str | None:
        for e in self._entries:
            if e.platform == platform and e.fleet_link:
                return e.fleet_link
        return None

    def platform_display_name(self, platform: str) -> str:
        for e in self._entries:
            if e.platform == platform and e.display_name:
                return e.display_name
        return platform.capitalize()

    def link_base_for_target(self, target_type: str) -> str:
        """Return the report_dir path prefix for a given STIG target type."""
        for e in self._entries:
            if target_type in (t.lower() for t in e.target_types):
                return f"platform/{e.report_dir}"
        return f"platform/{target_type}"

    def platform_to_report_dir(self, platform: str) -> str | None:
        """Return the primary report_dir for a platform (first renderable entry)."""
        for e in self._entries:
            if e.platform == platform and e.render:
                return e.report_dir
        for e in self._entries:
            if e.platform == platform:
                return e.report_dir
        return None

    # -- all stig skeleton map (merged) --------------------------------------

    def all_stig_skeleton_map(self) -> dict[str, str]:
        merged: dict[str, str] = {}
        for e in self._entries:
            for tt, skeleton in e.stig_skeleton_map.items():
                if tt not in merged:
                    merged[tt] = skeleton
        return merged


def registry_from_schemas(schemas: dict[str, "ReportSchema"]) -> PlatformRegistry:
    """Build a PlatformRegistry from schemas that have embedded platform metadata."""
    from ncs_reporter.schema_loader import build_platform_entries_from_schemas

    entry_dicts = build_platform_entries_from_schemas(schemas)
    entries = [PlatformEntry.model_validate(e) for e in entry_dicts]
    return PlatformRegistry(entries)


@functools.lru_cache(maxsize=1)
def default_registry() -> PlatformRegistry:
    """Load and cache the built-in default platform registry.

    Prefers schema-embedded platform metadata. Falls back to platforms_default.yaml
    if no schemas have platform specs.
    """
    from ncs_reporter.schema_loader import build_platform_entries_from_schemas, discover_schemas

    schemas = discover_schemas()
    entry_dicts = build_platform_entries_from_schemas(schemas)
    if entry_dicts:
        entries = [PlatformEntry.model_validate(e) for e in entry_dicts]
        return PlatformRegistry(entries)

    # Legacy fallback
    default_yaml = Path(__file__).parent / "platforms_default.yaml"
    if default_yaml.is_file():
        with open(default_yaml) as f:
            raw = yaml.safe_load(f)
        config = PlatformsConfig.model_validate(raw)
        return PlatformRegistry(config.platforms)

    return PlatformRegistry([])


def registry_from_entries(entries: list[PlatformEntry]) -> PlatformRegistry:
    return PlatformRegistry(entries)
