"""STIG HTML report renderers."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ._cklb import resolve_cklb_lookup
from ._report_context import get_jinja_env, report_context, write_report
from ._config import default_paths
from .pathing import rel_href, render_template
from .platform_registry import PlatformRegistry, default_registry
from .view_models.nav_builder import NavBuilder
from .view_models.stig import StigNavContext, build_stig_fleet_view, build_stig_host_view, build_stig_nav, collect_stig_entries

logger = logging.getLogger("ncs_reporter")


# ---------------------------------------------------------------------------
# STIG renderer
# ---------------------------------------------------------------------------

def render_stig(
    hosts_data: dict[str, Any],
    output_path: Path,
    common_vars: dict[str, str],
    global_inventory_index: dict[str, str] | None = None,
    cklb_dir: Path | None = None,
    generated_fleet_dirs: set[str] | None = None,
    registry: PlatformRegistry | None = None,
    has_site_report: bool = False,
    tree_products: list[dict[str, str]] | None = None,
    tree_host_urls: dict[str, str] | None = None,
) -> None:
    """Render per-host STIG reports and the fleet overview.

    Always rebuilds host views from scratch using the fully-populated CKLB
    directory (if available), so dedicated STIG HTML files have complete
    check/fix content hydration.
    """
    reg = registry or default_registry()
    env = get_jinja_env()
    stamp = common_vars["report_stamp"]
    rc = report_context(common_vars)
    from .models.platforms_config import TEMPLATE_STIG_HOST, TEMPLATE_STIG_FLEET as _TEMPLATE_STIG_FLEET
    host_tpl = env.get_template(TEMPLATE_STIG_HOST)
    all_hosts_data: dict[str, Any] = {}
    cklb_cache: dict[str, dict[str, dict[str, Any]]] = {}

    stig_nav_builder = NavBuilder(
        reg,
        hosts_data=global_inventory_index,
        generated_fleet_dirs=generated_fleet_dirs,
        has_stig_fleet=True,
        has_site_report=has_site_report,
        tree_products=tree_products,
    )

    stig_entries, all_stig_reports = collect_stig_entries(hosts_data, stamp, reg, tree_host_urls=tree_host_urls)

    for se in stig_entries:
        hostname = se["hostname"]
        target_type = se["target_type"]
        path_templates = se["path_templates"]
        report_dir = se["report_dir"]
        host_report_abs = se["host_report_abs"]
        host_rel_dir = se["host_rel_dir"]

        stig_fleet_abs = render_template(
            path_templates["report_stig_fleet"],
            report_dir=report_dir, schema_name="", hostname=hostname,
            target_type=target_type, report_stamp=stamp,
        )
        site_report_abs: str | None = None
        if has_site_report:
            site_report_abs = render_template(
                path_templates["report_site"],
                report_dir=report_dir, schema_name="", hostname=hostname,
                target_type=target_type, report_stamp=stamp,
            )

        host_nav, stig_host_peers, stig_siblings = build_stig_nav(
            se, all_stig_reports, stig_fleet_abs, site_report_abs, has_site_report,
        )
        cklb_lookup = resolve_cklb_lookup(hostname, target_type, cklb_dir, reg, cklb_cache)

        host_dir = output_path / host_rel_dir
        host_dir.mkdir(parents=True, exist_ok=True)

        history = _build_history(host_dir, Path(host_report_abs).stem)

        host_view = build_stig_host_view(
            hostname,
            se["audit_type"],
            se["payload"],
            ctx=rc,
            cklb_rule_lookup=cklb_lookup,
            nav_ctx=StigNavContext(
                nav=host_nav,
                host_bundle=se["bundle"],
                hosts_data=global_inventory_index,
                generated_fleet_dirs=generated_fleet_dirs,
                history=history,
                stig_host_peers=stig_host_peers,
                stig_siblings=stig_siblings,
                nav_builder=stig_nav_builder,
            ),
        )

        content = host_tpl.render(stig_host_view=host_view, **common_vars)
        write_report(host_dir, Path(host_report_abs).name, content, stamp)

        all_hosts_data.setdefault(hostname, {})[se["audit_type"]] = se["payload"]

    if not all_hosts_data:
        return

    first_entry = reg.entries[0] if reg.entries else None
    fleet_paths = first_entry.paths.model_dump() if first_entry else default_paths()

    stig_fleet_abs = render_template(
        fleet_paths["report_stig_fleet"],
        report_dir="", schema_name="", hostname="", target_type="", report_stamp=stamp,
    )
    stig_fleet_nav: dict[str, str] = {}
    if has_site_report:
        site_report_abs = render_template(
            fleet_paths["report_site"],
            report_dir="", schema_name="", hostname="", target_type="", report_stamp=stamp,
        )
        stig_fleet_nav["site_report"] = rel_href(".", site_report_abs)

    fleet_view = build_stig_fleet_view(
        all_hosts_data,
        ctx=rc,
        nav=stig_fleet_nav,
        generated_fleet_dirs=generated_fleet_dirs,
        cklb_dir=cklb_dir,
        nav_builder=stig_nav_builder,
        registry=reg,
        tree_host_urls=tree_host_urls,
    )
    fleet_tpl = env.get_template(_TEMPLATE_STIG_FLEET)
    content = fleet_tpl.render(stig_fleet_view=fleet_view, **common_vars)
    write_report(output_path, Path(stig_fleet_abs).name, content, stamp)


def _build_history(host_dir: Path, file_stem: str) -> list[dict[str, str]]:
    """Scan host_dir for stamped report files and return sorted history entries.

    *file_stem* may contain ``.`` (e.g. ``10.78.0.10_stig_esxi``); ``Path.glob``
    treats ``.`` literally, so we pass the raw stem to ``glob`` and only
    use ``re.escape`` in the regex that extracts the date suffix.
    """
    history: list[dict[str, str]] = []
    stamp_re = re.compile(rf"{re.escape(file_stem)}_(\d+)\.html")
    for f in host_dir.glob(f"{file_stem}_*.html"):
        m = stamp_re.search(f.name)
        if m:
            date_str = m.group(1)
            display = (
                f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
                if len(date_str) == 8
                else date_str
            )
            history.append({"name": display, "url": f.name})
    history.sort(key=lambda x: x["name"], reverse=True)
    return history
