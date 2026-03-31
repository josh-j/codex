"""Platform and STIG HTML report renderers."""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models.report_schema import ReportSchema

from ._cklb import resolve_cklb_lookup
from ._report_context import ReportContext, get_jinja_env, report_context, write_report
from ._config import default_paths
from .pathing import rel_href, render_template
from .platform_registry import PlatformRegistry, default_registry
from .schema_loader import discover_schemas
from .view_models.common import GenericNavContext
from .view_models.generic import build_generic_fleet_view, build_generic_node_view, merge_stig_into_node_view
from .view_models.nav_builder import NavBuilder
from .view_models.stig import StigNavContext, build_stig_fleet_view, build_stig_host_view, build_stig_nav, collect_stig_entries

logger = logging.getLogger("ncs_reporter")


@dataclasses.dataclass
class PlatformRenderConfig:
    """Configuration bundle for :func:`render_platform`."""
    global_inventory_index: dict[str, str] | None = None
    generated_fleet_dirs: set[str] | None = None
    report_dir: str | None = None
    platform_paths: dict[str, str] | None = None
    extra_config_dirs: tuple[str, ...] = ()
    schema_names_override: list[str] | None = None
    has_site_report: bool = False
    has_stig_fleet: bool = False
    stig_widgets_by_host: dict[str, list[dict[str, Any]]] | None = None


# ---------------------------------------------------------------------------
# Build pass: produce stig_host_views without writing files
# ---------------------------------------------------------------------------

def build_stig_host_views(
    hosts_data: dict[str, Any],
    common_vars: dict[str, str],
    *,
    cklb_dir: Path | None = None,
    generated_fleet_dirs: set[str] | None = None,
    global_inventory_index: dict[str, str] | None = None,
    registry: PlatformRegistry | None = None,
    has_site_report: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Build stig_host_view dicts for all hosts without writing any files.

    Called before parallel platform rendering so node reports can embed STIG
    summary widgets.  Uses skeleton CKLB fallback when ``cklb_dir`` is None or
    not yet populated.

    Returns:
        ``{hostname: [stig_host_view, ...]}`` — one view per STIG audit type.
        Each view has a ``_report_url`` key with a relative href from the
        corresponding node report directory to the STIG host report.
    """
    reg = registry or default_registry()
    stamp = common_vars["report_stamp"]
    rc = report_context(common_vars)
    cklb_cache: dict[str, dict[str, dict[str, Any]]] = {}

    stig_entries, all_stig_reports = collect_stig_entries(hosts_data, stamp, reg)

    nav_builder = NavBuilder(
        reg,
        hosts_data=global_inventory_index,
        generated_fleet_dirs=generated_fleet_dirs,
        has_stig_fleet=True,
        has_site_report=has_site_report,
    )

    result: dict[str, list[dict[str, Any]]] = {}

    for se in stig_entries:
        hostname = se["hostname"]
        target_type = se["target_type"]
        path_templates = se["path_templates"]
        report_dir = se["report_dir"]
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
                history=[],
                stig_host_peers=stig_host_peers,
                stig_siblings=stig_siblings,
                nav_builder=nav_builder,
            ),
        )

        # Annotate with a relative URL from the node report dir to this STIG report.
        # Node reports live at platform/{report_dir}/{hostname}/health_report.html
        if global_inventory_index and hostname in global_inventory_index:
            from .models.platforms_config import PLATFORM_DIR_PREFIX
            node_plt_dir = global_inventory_index[hostname]
            node_rel_dir = f"{PLATFORM_DIR_PREFIX}/{node_plt_dir}/{hostname}"
            host_report_filename = Path(se["host_report_abs"]).name
            stig_abs = f"{host_rel_dir}/{host_report_filename}"
            host_view["_report_url"] = rel_href(node_rel_dir, stig_abs)

        result.setdefault(hostname, []).append(host_view)

    return result


# ---------------------------------------------------------------------------
# Platform renderer
# ---------------------------------------------------------------------------

def render_platform(
    platform: str,
    hosts_data: dict[str, Any],
    output_path: Path,
    common_vars: dict[str, str],
    *,
    config: PlatformRenderConfig | None = None,
) -> None:
    """Render node + fleet reports for one platform using the schema engine.

    When multiple schemas match for a platform, each schema produces its own
    fleet report and per-host node report.  The first (primary) schema renders
    node reports as ``health_report.html``; additional schemas use
    ``{schema_name}_report.html``.

    When ``config.stig_widgets_by_host`` is provided, STIG summary widgets are
    embedded directly into each node report so operators don't have to navigate
    to a separate STIG report to see compliance status.
    """
    cfg = config or PlatformRenderConfig()
    schema_names = (
        cfg.schema_names_override
        if cfg.schema_names_override is not None
        else default_registry().schema_names_for_platform(platform)
    )
    all_schemas = discover_schemas(extra_dirs=cfg.extra_config_dirs)

    # Resolve all matching schemas (not just the first)
    matched_schemas = []
    for name in schema_names:
        s = all_schemas.get(name)
        if s:
            matched_schemas.append(s)

    if not matched_schemas:
        logger.warning("No schema found for platform '%s' (tried: %s)", platform, schema_names)
        return

    if not cfg.report_dir:
        logger.warning("Missing report_dir for platform '%s'", platform)
        return
    if not cfg.platform_paths:
        logger.warning("Missing path templates for platform '%s'", platform)
        return

    env = get_jinja_env()
    stamp = common_vars["report_stamp"]
    rc = report_context(common_vars)
    from .models.platforms_config import (
        PLATFORM_DIR_PREFIX,
        TEMPLATE_NODE,
        TEMPLATE_FLEET,
    )
    node_tpl = env.get_template(TEMPLATE_NODE)
    fleet_tpl = env.get_template(TEMPLATE_FLEET)

    reg = default_registry()
    nav_builder = NavBuilder(
        reg,
        hosts_data=cfg.global_inventory_index,
        generated_fleet_dirs=cfg.generated_fleet_dirs,
        has_stig_fleet=cfg.has_stig_fleet,
        has_site_report=cfg.has_site_report,
    )

    # Render each schema independently
    for schema_idx, schema in enumerate(matched_schemas):
        is_primary = schema_idx == 0
        node_file_stem = "health_report" if is_primary else f"{schema.name}_report"

        schema_name_for_file = schema.name
        fleet_report_abs = render_template(
            cfg.platform_paths["report_fleet"],
            report_dir=cfg.report_dir, schema_name=schema_name_for_file,
            hostname="", target_type="", report_stamp=stamp,
        )
        fleet_filename = Path(fleet_report_abs).name
        site_report_abs = render_template(
            cfg.platform_paths["report_site"],
            report_dir=cfg.report_dir, schema_name=schema_name_for_file,
            hostname="", target_type="", report_stamp=stamp,
        )

        node_nav: dict[str, str] = {"fleet_label": f"{schema.display_name} Fleet"}
        fleet_nav: dict[str, Any] = {}

        # When split_field is set, expand each vCenter bundle into
        # multiple synthetic per-host entries (e.g. ESXi hosts).
        effective_hosts = hosts_data
        if schema.split_field:
            effective_hosts = _split_hosts_data(hosts_data, schema)

        rendered_host_count = 0
        for hostname, bundle in effective_hosts.items():
            # For non-primary schemas in a multi-schema render, skip hosts
            # that lack detection keys (e.g. skip ESXi-only hosts in the
            # VM schema render).
            if not is_primary:
                det = schema.detection
                if det.keys_any and not any(k in bundle for k in det.keys_any):
                    continue

            rendered_host_count += 1
            host_dir = output_path / hostname
            host_dir.mkdir(exist_ok=True)
            node_rel_dir = f"{PLATFORM_DIR_PREFIX}/{cfg.report_dir}/{hostname}"
            node_nav["fleet_report"] = rel_href(node_rel_dir, fleet_report_abs)
            if cfg.has_site_report:
                node_nav["site_report"] = rel_href(node_rel_dir, site_report_abs)

            history = _build_history(host_dir, node_file_stem)

            node_view = build_generic_node_view(
                schema,
                hostname,
                bundle,
                ctx=rc,
                nav_ctx=GenericNavContext(
                    nav=node_nav,
                    hosts_data=cfg.global_inventory_index,
                    generated_fleet_dirs=cfg.generated_fleet_dirs,
                    history=history,
                    nav_builder=nav_builder,
                ),
            )

            # Embed STIG widgets only into the primary node report
            if is_primary and cfg.stig_widgets_by_host and hostname in cfg.stig_widgets_by_host:
                merge_stig_into_node_view(node_view, cfg.stig_widgets_by_host[hostname])

            content = node_tpl.render(generic_node_view=node_view, **common_vars)
            write_report(host_dir, f"{node_file_stem}.html", content, stamp)

        # Skip fleet report when no hosts matched this schema's detection keys.
        if rendered_host_count == 0:
            continue

        if cfg.has_site_report:
            fleet_nav["site_report"] = rel_href(f"{PLATFORM_DIR_PREFIX}/{cfg.report_dir}", site_report_abs)

        fleet_view = build_generic_fleet_view(
            schema,
            effective_hosts,
            ctx=rc,
            nav_ctx=GenericNavContext(
                nav=fleet_nav,
                hosts_data=cfg.global_inventory_index,
                generated_fleet_dirs=cfg.generated_fleet_dirs,
                nav_builder=nav_builder,
            ),
        )
        content = fleet_tpl.render(generic_fleet_view=fleet_view, **common_vars)
        write_report(output_path, fleet_filename, content, stamp)


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
    )

    stig_entries, all_stig_reports = collect_stig_entries(hosts_data, stamp, reg)

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
    )
    fleet_tpl = env.get_template(_TEMPLATE_STIG_FLEET)
    content = fleet_tpl.render(stig_fleet_view=fleet_view, **common_vars)
    write_report(output_path, Path(stig_fleet_abs).name, content, stamp)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------


def _split_hosts_data(
    hosts_data: dict[str, Any],
    schema: "ReportSchema",
) -> dict[str, dict[str, Any]]:
    """Expand hosts_data using a schema's split_field.

    When a schema defines ``split_field`` (e.g. ``"esxi_hosts"``), each
    bundle in *hosts_data* has its fields extracted (including script
    fields), then the resulting list at ``fields[split_field]`` is
    iterated.  Each item becomes a synthetic host entry keyed by the
    item's ``split_name_key`` field (default ``"name"``).

    Only runs field extraction (no alerts, rollups, or widgets) to
    minimize overhead.
    """
    from .normalization.schema_driven import extract_fields

    result: dict[str, dict[str, Any]] = {}
    name_key = schema.split_name_key or "name"
    split_key = schema.split_field

    for _parent_host, bundle in hosts_data.items():
        fields, _ = extract_fields(schema, bundle)
        items = fields.get(split_key)
        if not isinstance(items, list):
            result[_parent_host] = bundle
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            child_name = str(item.get(name_key, "")).strip()
            if not child_name:
                continue
            result[child_name] = dict(item)

    return result


def _build_history(host_dir: Path, file_stem: str) -> list[dict[str, str]]:
    """Scan host_dir for stamped report files and return sorted history entries."""
    history: list[dict[str, str]] = []
    pattern = f"{re.escape(file_stem)}_*.html"
    for f in host_dir.glob(pattern):
        m = re.search(rf"{re.escape(file_stem)}_(\d+)\.html", f.name)
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
