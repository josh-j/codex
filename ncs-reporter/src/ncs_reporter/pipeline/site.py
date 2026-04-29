"""Site dashboard and search-index writers for the full report pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from .._report_context import get_jinja_env, report_context
from ..pathing import render_template
from ..platform_registry import PlatformRegistry
from ..view_models.site import build_site_dashboard_view


def _render_site_and_search(
    r_root: Path,
    global_data: dict[str, Any],
    global_changed: bool,
    common_vars: dict[str, Any],
    global_inventory_index: dict[str, str],
    platforms_by_report_dir: dict[str, dict[str, Any]],
    runtime_registry: PlatformRegistry,
    generated_fleet_dirs: set[str] | None = None,
    tree_host_urls: dict[str, str] | None = None,
    tree_products: list[dict[str, str]] | None = None,
) -> None:
    """Render the site dashboard and generate the search index."""
    if not global_changed:
        click.echo("--- Skipping Global Site Dashboard (unchanged) ---")
    else:
        from ..models.platforms_config import FILENAME_SITE_HEALTH, TEMPLATE_SITE

        click.echo("--- Processing Global Site Dashboard ---")
        site_view = build_site_dashboard_view(
            global_data,
            ctx=report_context(common_vars),
            registry=runtime_registry,
            generated_fleet_dirs=generated_fleet_dirs,
            tree_host_urls=tree_host_urls,
            tree_products=tree_products,
        )
        content = get_jinja_env().get_template(TEMPLATE_SITE).render(
            site_dashboard_view=site_view, **common_vars
        )
        (r_root / FILENAME_SITE_HEALTH).write_text(content)
        click.echo(f"Global dashboard generated at {r_root}/{FILENAME_SITE_HEALTH}")

    tree_host_urls = tree_host_urls or {}
    search_index = []
    for hostname, rep_dir in global_inventory_index.items():
        tree_url = tree_host_urls.get(hostname)
        if tree_url:
            search_url = tree_url
        else:
            platform_cfg = platforms_by_report_dir.get(rep_dir)
            if not platform_cfg:
                continue
            path_templates = dict(platform_cfg["paths"])
            search_url = render_template(
                path_templates["report_search_entry"],
                report_dir=rep_dir,
                schema_name=str(platform_cfg.get("schema_name") or platform_cfg["platform"]),
                hostname=hostname,
                target_type="",
                report_stamp=common_vars["report_stamp"],
            )
        search_index.append({
            "h": hostname,
            "u": search_url,
            "p": rep_dir.split("/")[0] if "/" in rep_dir else rep_dir,
        })
    (r_root / "search_index.js").write_text(
        "window.NCS_SEARCH_INDEX = " + json.dumps(search_index, separators=(",", ":")) + ";",
        encoding="utf-8",
    )
    click.echo(f"Search index generated at {r_root}/search_index.js")


def _write_tree_only_site_and_search(
    r_root: Path,
    tree_roots: list[tuple[str, str, Path, list[str]]],
    common_vars: dict[str, Any],
) -> None:
    """Emit site.html + search_index.js from tree-only output."""
    if not tree_roots:
        return
    stamp = common_vars.get("report_stamp", "")
    items_html: list[str] = []
    search_index: list[dict[str, str]] = []
    for slug, title, root_html, host_ids in tree_roots:
        rel = root_html.relative_to(r_root).as_posix()
        items_html.append(f'  <li><a href="{rel}">{title}</a> — {len(host_ids)} host(s)</li>')
        for host in host_ids:
            search_index.append({"h": host, "u": rel, "p": slug})
    site_html = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>NCS Reports</title></head>\n"
        "<body>\n<h1>NCS Reports</h1>\n"
        f"<p>Tree-layout render{(' — ' + stamp) if stamp else ''}.</p>\n"
        "<ul>\n"
        + "\n".join(items_html)
        + "\n</ul>\n</body></html>\n"
    )
    (r_root / "site.html").write_text(site_html, encoding="utf-8")
    (r_root / "search_index.js").write_text(
        "window.NCS_SEARCH_INDEX = " + json.dumps(search_index, separators=(",", ":")) + ";",
        encoding="utf-8",
    )
    click.echo(f"Tree-only site landing written at {r_root}/site.html ({len(search_index)} searchable hosts)")


def _write_empty_site_and_search(r_root: Path, common_vars: dict[str, Any]) -> None:
    """Emit placeholder site.html + search_index.js for an empty fleet."""
    stamp = common_vars.get("report_stamp", "")
    site_html = (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\"><title>NCS Reports</title></head>\n"
        "<body>\n<h1>NCS Reports</h1>\n"
        f"<p>No fleet data yet{(' — ' + stamp) if stamp else ''}.</p>\n"
        "<p>Run <code>just site-collect</code> (or <code>just site</code>) to populate telemetry, "
        "then re-render with <code>just report</code>.</p>\n"
        "</body></html>\n"
    )
    r_root.mkdir(parents=True, exist_ok=True)
    (r_root / "site.html").write_text(site_html, encoding="utf-8")
    (r_root / "search_index.js").write_text("window.NCS_SEARCH_INDEX = [];", encoding="utf-8")
    click.echo(f"Empty-state site + search stubs written at {r_root}/site.html")
