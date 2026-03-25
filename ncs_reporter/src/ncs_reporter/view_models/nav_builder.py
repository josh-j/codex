"""Unified navigation builder for all report types.

Replaces the ad-hoc nav construction scattered across generic.py, stig.py,
and site.py with a single source of truth.  Output dicts match the existing
template contracts exactly (tree_fleets, tree_siblings, tree_host_peers, etc.)
so templates require zero changes.

Each ``build_for_*`` method also produces a ``breadcrumbs`` list – a generic,
ordered sequence of typed crumb dicts consumed by the shared
``_breadcrumb_bar.html.j2`` macro.  This keeps *all* breadcrumb logic in
Python so the templates have zero presentation logic for the nav bar.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
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

        # Pre-compute immutable indices.
        # Use generated_fleet_dirs as the authoritative list of platforms
        # that have rendered reports (handles cases where hosts appear in
        # multiple platform dirs, e.g. a vCenter hostname in vcsa, esxi, vm).
        if self._generated_fleet_dirs is not None:
            p_dirs = sorted(self._generated_fleet_dirs)
        else:
            p_dirs = sorted(set(self._hosts_data.values()))
        self._platform_dirs: list[str] = p_dirs

        # Sibling index: report_dir → sorted list of hostnames
        by_dir: dict[str, list[str]] = {}
        for h, d in self._hosts_data.items():
            by_dir.setdefault(d, []).append(h)
        for hosts in by_dir.values():
            hosts.sort()
        self._siblings_by_dir: dict[str, list[str]] = by_dir

    # -- shared building blocks -----------------------------------------------

    def _search_root(self, nav: Mapping[str, Any] | None) -> str:
        """Resolve the root path used by static global search/navigation JS."""
        if nav:
            explicit = str(nav.get("search_root") or "").strip()
            if explicit:
                return explicit

            site_report = str(nav.get("site_report") or "").strip()
            if site_report:
                parent = PurePosixPath(site_report).parent
                if str(parent) in ("", "."):
                    return "./"
                return f"{parent.as_posix()}/"

        return "./"

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

    # -- breadcrumb helpers ---------------------------------------------------

    @staticmethod
    def _fleet_dropdown_items(
        tree_fleets: list[dict[str, str]],
        active_fleet_name: str,
    ) -> list[dict[str, Any]]:
        """Convert a tree_fleets list into generic dropdown items."""
        return [
            {
                "text": f"{f['name']} Fleet",
                "href": f["report"],
                "active": f["name"] == active_fleet_name,
                "css_class": "stig-link" if f["name"] == NAV_LABEL_STIG else "",
            }
            for f in tree_fleets
        ]

    @staticmethod
    def _site_link_crumb(nav: Mapping[str, Any]) -> dict[str, Any] | None:
        """Return a site-dashboard link crumb, or *None* if unavailable."""
        site_report = str(nav.get("site_report") or "").strip()
        if not site_report:
            return None
        return {"type": "link", "text": "Site Dashboard", "href": site_report, "icon": "home"}

    @staticmethod
    def _search_crumb(search_root: str) -> dict[str, Any]:
        return {"type": "search", "search_root": search_root}

    @staticmethod
    def _history_crumb(history: list[dict[str, str]]) -> dict[str, Any] | None:
        if not history:
            return None
        return {
            "type": "dropdown",
            "text": "History",
            "group_label": "Report Versions",
            "scrollable": True,
            "items": [{"text": h["name"], "href": h["url"], "active": False, "css_class": ""} for h in history],
        }

    @staticmethod
    def _host_dropdown_crumb(
        current_name: str,
        peers: list[dict[str, str]],
        group_label: str = "Hosts",
    ) -> dict[str, Any] | None:
        if not peers:
            return None
        return {
            "type": "dropdown",
            "text": current_name,
            "group_label": group_label,
            "scrollable": True,
            "items": [
                {
                    "text": p["name"],
                    "href": p["report"],
                    "active": p["name"] == current_name or p["report"] == "#",
                    "css_class": "",
                }
                for p in peers
            ],
        }

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
        nav["search_root"] = self._search_root(nav)
        if history:
            nav["history"] = history
        if hostname in self._hosts_data:
            current_dir = self._hosts_data[hostname]
            nav["tree_siblings"] = self.build_tree_siblings(hostname)
            nav["tree_fleets"] = self.build_tree_fleets(current_dir, is_node=True)

        # --- breadcrumbs -----------------------------------------------------
        crumbs: list[dict[str, Any]] = []
        site_crumb = self._site_link_crumb(nav)
        if site_crumb:
            crumbs.append(site_crumb)

        tree_fleets = nav.get("tree_fleets", [])
        if tree_fleets:
            fleet_label = str(nav.get("fleet_label") or "Fleet").replace(" Fleet", "")
            crumbs.append({
                "type": "dropdown",
                "text": f"{fleet_label} Fleet",
                "href": nav.get("fleet_report") or "#",
                "group_label": "Fleets",
                "scrollable": False,
                "items": self._fleet_dropdown_items(tree_fleets, nav.get("fleet_label", "")),
            })
        elif nav.get("fleet_report"):
            crumbs.append({
                "type": "link",
                "text": nav.get("fleet_label", "Fleet Report"),
                "href": nav["fleet_report"],
            })

        host_crumb = self._host_dropdown_crumb(hostname, nav.get("tree_siblings", []))
        if host_crumb:
            crumbs.append(host_crumb)
        else:
            crumbs.append({"type": "label", "text": hostname})

        hist_crumb = self._history_crumb(history or [])
        if hist_crumb:
            crumbs.append(hist_crumb)

        crumbs.append(self._search_crumb(nav["search_root"]))
        if crumbs:
            nav["breadcrumbs"] = crumbs

        return nav

    def build_for_fleet(
        self,
        from_dir: str,
        *,
        base_nav: Mapping[str, Any] | None = None,
        display_name: str = "",
    ) -> dict[str, Any]:
        """Complete nav dict for a fleet report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        nav["search_root"] = self._search_root(nav)
        nav["tree_fleets"] = self.build_tree_fleets(from_dir)

        # --- breadcrumbs -----------------------------------------------------
        site_crumb = self._site_link_crumb(nav)
        if site_crumb:
            crumbs: list[dict[str, Any]] = [site_crumb]
            tree_fleets = nav["tree_fleets"]
            label = (display_name or "Fleet").replace(" Fleet", "")
            if tree_fleets:
                crumbs.append({
                    "type": "dropdown",
                    "text": f"{label} Fleet",
                    "group_label": "Fleets",
                    "scrollable": False,
                    "items": self._fleet_dropdown_items(tree_fleets, display_name),
                })
            else:
                crumbs.append({"type": "label", "text": f"{label} Fleet"})

            crumbs.append(self._search_crumb(nav["search_root"]))
            nav["breadcrumbs"] = crumbs

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
        target_type: str = "",
    ) -> dict[str, Any]:
        """Complete nav dict for a STIG host report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        nav["search_root"] = self._search_root(nav)
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

        # --- breadcrumbs -----------------------------------------------------
        crumbs: list[dict[str, Any]] = []
        site_crumb = self._site_link_crumb(nav)
        if site_crumb:
            crumbs.append(site_crumb)

        tree_fleets = nav.get("tree_fleets", [])
        if tree_fleets:
            crumbs.append({
                "type": "dropdown",
                "text": "STIG Fleet",
                "href": nav.get("fleet_report") or "#",
                "group_label": "Fleets",
                "scrollable": False,
                "items": self._fleet_dropdown_items(tree_fleets, NAV_LABEL_STIG),
            })
        elif nav.get("fleet_report"):
            crumbs.append({
                "type": "link",
                "text": nav.get("fleet_label", "STIG Fleet Dashboard"),
                "href": nav["fleet_report"],
            })

        # Host peers dropdown
        peers_crumb = self._host_dropdown_crumb(
            hostname, nav.get("tree_host_peers", []),
        )
        if peers_crumb:
            crumbs.append(peers_crumb)
        else:
            crumbs.append({"type": "label", "text": hostname})

        # STIG audit type siblings dropdown
        t_type_label = f"{target_type.upper()} STIG" if target_type else "STIG"
        stig_sibs = nav.get("tree_siblings", [])
        if stig_sibs or target_type:
            stig_items: list[dict[str, Any]] = [
                {"text": t_type_label, "href": "#", "active": True, "css_class": ""},
            ]
            for s in stig_sibs:
                stig_items.append({
                    "text": s["name"],
                    "href": s["report"],
                    "active": False,
                    "css_class": "",
                })
            crumbs.append({
                "type": "dropdown",
                "text": t_type_label,
                "group_label": "STIG Audits",
                "scrollable": False,
                "items": stig_items,
            })

        hist_crumb = self._history_crumb(history or [])
        if hist_crumb:
            crumbs.append(hist_crumb)

        crumbs.append(self._search_crumb(nav["search_root"]))
        if crumbs:
            nav["breadcrumbs"] = crumbs

        return nav

    def build_for_stig_fleet(
        self,
        by_platform: dict[str, dict[str, int]],
        *,
        base_nav: Mapping[str, Any] | None = None,
        host_links: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Complete nav dict for the STIG fleet report."""
        nav: dict[str, Any] = {**base_nav} if base_nav else {}
        nav["search_root"] = self._search_root(nav)
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

        # --- breadcrumbs -----------------------------------------------------
        site_crumb = self._site_link_crumb(nav)
        if site_crumb:
            crumbs: list[dict[str, Any]] = [site_crumb]

            if tree_fleets:
                crumbs.append({
                    "type": "dropdown",
                    "text": "STIG Fleet",
                    "group_label": "Fleets",
                    "scrollable": False,
                    "items": self._fleet_dropdown_items(tree_fleets, NAV_LABEL_STIG),
                })
            else:
                crumbs.append({"type": "label", "text": "STIG Fleet Compliance Overview"})

            if host_links:
                crumbs.append({
                    "type": "dropdown",
                    "text": "Hosts",
                    "group_label": "STIG Hosts",
                    "scrollable": True,
                    "items": [
                        {"text": h["name"], "href": h["href"], "active": False, "css_class": ""}
                        for h in host_links
                    ],
                })

            crumbs.append(self._search_crumb(nav["search_root"]))
            nav["breadcrumbs"] = crumbs

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

        # --- breadcrumbs -----------------------------------------------------
        crumbs: list[dict[str, Any]] = [
            {"type": "label", "text": "Site Dashboard", "icon": "home"},
        ]
        if tree_fleets:
            crumbs.append({
                "type": "dropdown",
                "text": "Select Fleet",
                "group_label": "Fleets",
                "scrollable": False,
                "items": self._fleet_dropdown_items(tree_fleets, ""),
            })
        crumbs.append(self._search_crumb("./"))

        return {"tree_fleets": tree_fleets, "search_root": "./", "breadcrumbs": crumbs}
