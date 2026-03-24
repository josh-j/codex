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

from ncs_reporter.models.platforms_config import PlatformEntry, PlatformNode, PlatformsConfig


class PlatformRegistry:
    """Read-only accessor over a list of ``PlatformEntry`` objects."""

    def __init__(self, entries: list[PlatformEntry]) -> None:
        self._entries = tuple(entries)
        # Pre-build target-type lookup: lowered target_type → PlatformEntry
        self._tt_lookup: dict[str, PlatformEntry] = {}
        self._all_target_types: frozenset[str] = frozenset(
            t for e in self._entries for t in e.target_types
        )
        for e in self._entries:
            for t in e.target_types:
                self._tt_lookup.setdefault(t.lower(), e)

        # Pre-compute platform names (insertion-ordered, deduplicated)
        seen: set[str] = set()
        names: list[str] = []
        for e in self._entries:
            if e.platform not in seen:
                seen.add(e.platform)
                names.append(e.platform)
        self._platform_names: tuple[str, ...] = tuple(names)

        # Build platform hierarchy tree
        self._roots: tuple[PlatformNode, ...] = tuple(self._build_tree())
        self._node_by_id: dict[str, PlatformNode] = {
            n.id: n for root in self._roots for n in root.walk()
        }
        self._node_by_report_dir: dict[str, PlatformNode] = {
            n.entry.report_dir: n for root in self._roots for n in root.walk()
        }

    # -- basic accessors -----------------------------------------------------

    @property
    def entries(self) -> tuple[PlatformEntry, ...]:
        return self._entries

    def by_platform(self, name: str) -> list[PlatformEntry]:
        return [e for e in self._entries if e.platform == name]

    # -- tree accessors -------------------------------------------------------

    def _build_tree(self) -> list[PlatformNode]:
        """Build a platform hierarchy tree from the flat entry list.

        Groups entries by platform name. Renderable entries (render=True)
        become root nodes; non-renderable entries become their children.
        """
        by_platform: dict[str, list[PlatformEntry]] = {}
        for e in self._entries:
            by_platform.setdefault(e.platform, []).append(e)

        roots: list[PlatformNode] = []
        for entries in by_platform.values():
            primary = next((e for e in entries if e.render), entries[0])
            root_node = PlatformNode(entry=primary)
            for e in entries:
                if e is not primary:
                    child = PlatformNode(entry=e, parent=root_node)
                    root_node.children.append(child)
            roots.append(root_node)
        return roots

    @property
    def roots(self) -> tuple[PlatformNode, ...]:
        """Top-level platform nodes."""
        return self._roots

    def node_for_id(self, node_id: str) -> PlatformNode | None:
        """Find a tree node by its id (schema_name or platform)."""
        return self._node_by_id.get(node_id)

    def node_for_report_dir(self, report_dir: str) -> PlatformNode | None:
        """Find the tree node whose entry matches a report_dir path."""
        return self._node_by_report_dir.get(report_dir)

    # -- platform / target type sets -----------------------------------------

    def all_platform_names(self) -> tuple[str, ...]:
        return self._platform_names

    def all_target_types(self) -> frozenset[str]:
        return self._all_target_types

    # -- schema name lookup --------------------------------------------------

    def schema_names_for_platform(self, platform: str) -> list[str]:
        for e in self._entries:
            if e.platform == platform and e.schema_names:
                return list(e.schema_names)
        return [platform]

    # -- aggregation helpers -------------------------------------------------

    def host_exclude_set(self) -> set[str]:
        """Build the set of directory/file names to skip when walking host dirs."""
        from ncs_reporter.models.platforms_config import PLATFORM_DIR_PREFIX
        structural = {
            PLATFORM_DIR_PREFIX,
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
        e = self._tt_lookup.get(target_type.lower())
        return e.platform if e else "unknown"

    def entry_for_target_type(self, target_type: str) -> PlatformEntry | None:
        """Return the platform entry that owns a given target_type."""
        return self._tt_lookup.get(target_type.lower())

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
        from ncs_reporter.models.platforms_config import PLATFORM_DIR_PREFIX
        e = self._tt_lookup.get(target_type.lower())
        if e:
            return f"{PLATFORM_DIR_PREFIX}/{e.report_dir}"
        return f"{PLATFORM_DIR_PREFIX}/{target_type}"

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

    def legacy_raw_key_map(self) -> dict[str, str]:
        """Merged canonical_key → legacy_key across all entries."""
        merged: dict[str, str] = {}
        for e in self._entries:
            merged.update(e.legacy_raw_keys)
        return merged

    def legacy_audit_key_for(self, schema_name: str) -> str | None:
        """Return the legacy audit key alias for a schema name, or None."""
        for e in self._entries:
            if schema_name in e.schema_names and e.legacy_audit_key:
                return e.legacy_audit_key
        return None

    def stig_apply_plan(self, target_type: str) -> tuple[str, str] | None:
        """Return (playbook, target_var) for a STIG target type, or None.

        Also searches schema-embedded platform specs for configs whose target_types
        were merged into a shared primary entry.
        """
        t = target_type.lower()
        for e in self._entries:
            if t in [tt.lower() for tt in e.target_types] and e.stig_playbook:
                return (e.stig_playbook, e.stig_target_var)
        # Fall back to schema-level platform specs (covers merged schemas like vm.yaml)
        from .schema_loader import discover_schemas
        for schema in discover_schemas().values():
            spec = schema.platform_spec
            if spec and spec.stig_playbook and t in [tt.lower() for tt in spec.target_types]:
                return (spec.stig_playbook, spec.stig_target_var)
        return None

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
