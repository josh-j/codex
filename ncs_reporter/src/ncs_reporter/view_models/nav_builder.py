"""Unified navigation builder for all report types.

Replaces the ad-hoc nav construction scattered across generic.py, stig.py,
and site.py with a single source of truth.  Output dicts match the existing
template contracts exactly (tree_fleets, tree_siblings, tree_host_peers, etc.)
so templates require zero changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..models.platforms_config import (
    FILENAME_HEALTH_REPORT,
    FILENAME_STIG_FLEET,
    NAV_LABEL_STIG,
    fleet_link_url,
)
from ..platform_registry import PlatformRegistry
from .common import fleet_entries_for_dir


class NavBuilder:
    """Build navigation dicts consumed by Jinja2 templates.

    Constructed once per rendering job and shared across all view model
    builders so fleet/sibling/peer link logic lives in one place.
    """

    def __init__(
        self,
        registry: PlatformRegistry,
        *,
        hosts_data: dict[str, Any] | None = None,
        generated_fleet_dirs: set[str] | None = None,
        has_stig_fleet: bool = False,
        has_site_report: bool = False,
    ) -> None:
        self._reg = registry
        self._hosts_data = hosts_data or {}
        self._generated_fleet_dirs = generated_fleet_dirs
        self._has_stig_fleet = has_stig_fleet
        self._has_site_report = has_site_report

        # Pre-compute immutable indices
        p_dirs = sorted(set(self._hosts_data.values()))
        if self._generated_fleet_dirs is not None:
            p_dirs = [d for d in p_dirs if d in self._generated_fleet_dirs]
        self._platform_dirs: list[str] = p_dirs

        # Sibling index: report_dir → sorted list of hostnames
        by_dir: dict[str, list[str]] = {}
        for h, d in self._hosts_data.items():
            by_dir.setdefault(d, []).append(h)
        for hosts in by_dir.values():
            hosts.sort()
        self._siblings_by_dir: dict[str, list[str]] = by_dir

    # -- shared building blocks -----------------------------------------------

    def _back_to_root(self, from_dir: str, *, is_node: bool = False) -> str:
        """Compute the ``../`` prefix to reach the report root from *from_dir*.

        *from_dir* is a platform report_dir like ``vmware/vcenter``.
        Node reports are one directory deeper (``{report_dir}/{hostname}/``),
        so *is_node* adds one extra ``../`` level.
        """
        depth = len(from_dir.split("/")) + (1 if is_node else 0)
        return "../" * (depth + 1)

    def build_tree_fleets(
        self, from_dir: str, *, is_node: bool = False,
    ) -> list[dict[str, str]]:
        """Fleet navigation links used by all templates."""
        back = self._back_to_root(from_dir, is_node=is_node)
        fleets: list[dict[str, str]] = []
        for plt_dir in self._platform_dirs:
            for label, schema_name in fleet_entries_for_dir(plt_dir):
                fleets.append({
                    "name": label,
                    "report": fleet_link_url(plt_dir, schema_name, back),
                })
        if self._has_stig_fleet:
            fleets.append({"name": NAV_LABEL_STIG, "report": f"{back}{FILENAME_STIG_FLEET}"})
        return fleets

    def build_tree_siblings(self, hostname: str) -> list[dict[str, str]]:
        """Peer hosts in the same platform directory."""
        if hostname not in self._hosts_data:
            return []
        current_dir = self._hosts_data[hostname]
        peers = self._siblings_by_dir.get(current_dir, [])
        return [
            {"name": h, "report": f"../{h}/{FILENAME_HEALTH_REPORT}" if h != hostname else "#"}
            for h in peers
        ]

    # -- composite builders (one per report type) -----------------------------

    def build_for_node(
        self,
        hostname: str,
        *,
        base_nav: Mapping[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Complete nav dict for a node (host) health report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        if history:
            nav["history"] = history
        if hostname in self._hosts_data:
            current_dir = self._hosts_data[hostname]
            nav["tree_siblings"] = self.build_tree_siblings(hostname)
            nav["tree_fleets"] = self.build_tree_fleets(current_dir, is_node=True)
        return nav

    def build_for_fleet(
        self,
        from_dir: str,
        *,
        base_nav: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Complete nav dict for a fleet report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        nav["tree_fleets"] = self.build_tree_fleets(from_dir)
        return nav

    def build_for_stig_host(
        self,
        hostname: str,
        *,
        base_nav: Mapping[str, Any] | None = None,
        history: list[dict[str, str]] | None = None,
        stig_host_peers: list[dict[str, str]] | None = None,
        stig_siblings: list[dict[str, str]] | None = None,
        host_bundle: dict[str, Any] | None = None,
        audit_type: str = "",
    ) -> dict[str, Any]:
        """Complete nav dict for a STIG host report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        if history:
            nav["history"] = history

        # Siblings: other STIG types for same host
        if stig_siblings is not None:
            nav["tree_siblings"] = stig_siblings
        elif host_bundle:
            from .stig import _infer_stig_target_type
            siblings: list[dict[str, str]] = []
            for k in host_bundle:
                if k.lower().startswith("stig_") and k != audit_type:
                    p = host_bundle[k]
                    t_type = _infer_stig_target_type(k, p)
                    siblings.append({
                        "name": f"{t_type.upper()} STIG",
                        "report": f"{hostname}_stig_{t_type}.html",
                    })
            siblings.sort(key=lambda x: x["name"])
            nav["tree_siblings"] = siblings

        if stig_host_peers:
            nav["tree_host_peers"] = stig_host_peers

        # Fleet navigation — delegate to build_tree_fleets
        if self._hosts_data:
            current_dir = self._hosts_data.get(hostname, "")
            nav["tree_fleets"] = self.build_tree_fleets(current_dir, is_node=True)

        return nav

    def build_for_stig_fleet(
        self,
        by_platform: dict[str, dict[str, int]],
        *,
        base_nav: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Complete nav dict for the STIG fleet report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        tree_fleets: list[dict[str, str]] = []

        for p_name in self._reg.all_platform_names():
            report_dir = self._reg.platform_to_report_dir(p_name)
            if report_dir is None:
                continue
            if self._generated_fleet_dirs is not None and report_dir not in self._generated_fleet_dirs:
                continue
            if by_platform.get(p_name, {}).get("hosts", 0) <= 0:
                continue
            fleet_link = self._reg.platform_fleet_link(p_name)
            if fleet_link:
                tree_fleets.append({
                    "name": self._reg.platform_display_name(p_name),
                    "report": fleet_link,
                })
            else:
                for label, schema_name in fleet_entries_for_dir(report_dir):
                    tree_fleets.append({
                        "name": label,
                        "report": fleet_link_url(report_dir, schema_name),
                    })

        tree_fleets.append({"name": NAV_LABEL_STIG, "report": FILENAME_STIG_FLEET})
        nav["tree_fleets"] = tree_fleets
        return nav

    def build_for_site(
        self,
        site_entries_with_assets: list[dict[str, Any]],
        *,
        has_stig_rows: bool = False,
    ) -> dict[str, Any]:
        """Build nav dict for the site dashboard.

        *site_entries_with_assets* is a list of dicts with keys
        ``display_name`` and ``fleet_link`` for platforms that have assets.
        """
        tree_fleets: list[dict[str, str]] = []
        for item in site_entries_with_assets:
            tree_fleets.append({
                "name": item["display_name"],
                "report": item["fleet_link"],
            })
        if has_stig_rows:
            tree_fleets.append({"name": NAV_LABEL_STIG, "report": FILENAME_STIG_FLEET})
        return {"tree_fleets": tree_fleets}
