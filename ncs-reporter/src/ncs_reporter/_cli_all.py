"""Extract of the ``all`` command and its helper functions from ``cli``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click

from ._config import (
    load_config_yaml,
    load_platforms,
    resolve_config_dir,
)
from ._renderers import build_stig_host_views
from ._report_context import generate_timestamps
from .aggregation import deep_merge, hosts_unchanged, normalize_host_bundle, write_output
from .pipeline.history import (
    HISTORY_DIR,
    _format_stamp_label,
    _history_for_render_signature,
    _patch_history_groups_in_html,
    _read_archive_stamp_manifests,
    _refresh_archive_history_dropdowns,
    _refresh_history_index,
    _write_stamp_manifest,
)
from .pipeline.legacy import (
    _aggregate_platforms,
    _augment_platforms_from_schemas,
    _load_stig_artifacts,
    _merge_platform_data,
)
from .pipeline.site import _render_site_and_search, _write_empty_site_and_search, _write_tree_only_site_and_search
from .pipeline.stig import _render_stig_and_cklb
from .pipeline.tree import _merge_tree_bundles_into_global, _render_inventory_trees

logger = logging.getLogger("ncs_reporter")

__all__ = [
    "all_cmd",
    "HISTORY_DIR",
    "_format_stamp_label",
    "_history_for_render_signature",
    "_patch_history_groups_in_html",
    "_read_archive_stamp_manifests",
    "_refresh_archive_history_dropdowns",
    "_refresh_history_index",
    "_write_stamp_manifest",
]


# ---------------------------------------------------------------------------
# all – helper functions
# ---------------------------------------------------------------------------


def _resolve_effective_config(
    config_dir: str | None,
    report_stamp: str | None,
    extra_config_dir: tuple[str, ...],
    platforms_config: str | None,
) -> tuple[dict[str, Any], str | None, tuple[str, ...], list[dict[str, Any]]]:
    """Resolve config_yaml, effective stamp, extra dirs, and platforms list.

    Returns ``(config_yaml, effective_stamp, extra_dirs, platforms)``.
    The caller still needs to call ``generate_timestamps`` on *effective_stamp*.
    """
    config_yaml = load_config_yaml(config_dir)
    effective_stamp = report_stamp or (
        str(config_yaml["report_stamp"]) if config_yaml.get("report_stamp") is not None else None
    )

    _extra_dirs, _platforms_cfg = resolve_config_dir(config_dir, extra_config_dir, platforms_config, config_yaml)
    platforms = load_platforms(_platforms_cfg, extra_config_dirs=_extra_dirs)

    return config_yaml, effective_stamp, _extra_dirs, platforms


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------


@click.command("all")
@click.option("--platform-root", required=True, type=click.Path(exists=True))
@click.option("--reports-root", required=True, type=click.Path())
@click.option(
    "--bundle-root",
    default=None,
    type=click.Path(),
    help="Where raw.yaml tree bundles live. Defaults to --reports-root when omitted.",
)
@click.option("--report-stamp")
@click.option("--config-dir", default=None, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--extra-config-dir", "-S", multiple=True, metavar="DIR")
@click.option("--platforms-config", "-P", default=None, type=click.Path(exists=True))
@click.option("--force", is_flag=True, default=False, help="Force re-render even if data is unchanged.")
def all_cmd(
    platform_root: str,
    reports_root: str,
    bundle_root: str | None,
    report_stamp: str | None,
    config_dir: str | None,
    extra_config_dir: tuple[str, ...],
    platforms_config: str | None,
    force: bool,
) -> None:
    """Run full aggregation and rendering for all platforms and the site dashboard."""
    p_root = Path(platform_root)
    r_root = Path(reports_root)
    b_root = Path(bundle_root) if bundle_root else r_root
    r_root.mkdir(parents=True, exist_ok=True)

    # Step 0: Resolve configuration
    _config_yaml, effective_stamp, extra_dirs, platforms = (
        _resolve_effective_config(config_dir, report_stamp, extra_config_dir, platforms_config)
    )
    common_vars = generate_timestamps(effective_stamp)

    _augment_platforms_from_schemas(platforms, extra_dirs, p_root)

    # Step 1: Platform aggregation (sequential I/O)
    render_tasks, global_inventory_index, all_platform_data, platforms_by_report_dir, runtime_registry = (
        _aggregate_platforms(platforms, p_root, r_root, extra_dirs, force)
    )
    generated_fleet_dirs = {str(t["report_dir"]) for t in render_tasks}

    # Step 1b: Global aggregation (merge already-collected platform data)
    click.echo("--- Aggregating Global State ---")
    all_hosts_state = p_root / "all_hosts_state.yaml"
    global_data = _merge_platform_data(all_platform_data)
    # Step 1b: If the collector skipped the legacy platform/<p>/<h>/raw_*.yaml
    # layout and only wrote the hierarchical tree layout, hydrate global_data
    # from those tree bundles so the full site dashboard renders instead of
    # a bare landing-page fallback (ncs-console fetches site.html via SCP
    # and expects the dashboard shape).
    _merge_tree_bundles_into_global(b_root, global_data, global_inventory_index, extra_dirs=extra_dirs)
    # Step 1b′: Merge STIG artifacts from report_dir paths.
    # ncs_collector writes STIG results to platform/{report_dir}/ which may
    # differ from the input_dir used by platform aggregation above.
    stig_artifacts = _load_stig_artifacts(platforms, p_root)
    if stig_artifacts:
        click.echo(f"  Loaded STIG artifacts for {len(stig_artifacts)} host(s).")
        for hostname, stig_bundle in stig_artifacts.items():
            if hostname not in global_data["hosts"]:
                global_data["hosts"][hostname] = {}
            deep_merge(global_data["hosts"][hostname], stig_bundle)
        # Normalize only hosts that received STIG data (avoids re-normalizing
        # hosts already processed by _aggregate_platforms).
        for hostname in stig_artifacts:
            global_data["hosts"][hostname] = normalize_host_bundle(
                hostname, global_data["hosts"][hostname], extra_dirs=extra_dirs
            )
        global_data["metadata"]["fleet_stats"]["total_hosts"] = len(global_data["hosts"])

    if not global_data["hosts"]:
        # Legacy aggregation is empty. Tree-layout raw bundles may still
        # exist directly under reports_root (collector emitting only to the
        # hierarchical layout); render those and return. No STIG fleet
        # report (still tied to the legacy global_data), but site.html /
        # search_index.js are written from the tree output so downstream
        # verifiers see the same landing-page + search contract either way.
        try:
            tree_roots, _tree_host_urls, _tree_products = _render_inventory_trees(r_root, all_platform_data, extra_dirs, common_vars, bundle_root=b_root)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Hierarchical tree render failed: %s", exc)
            click.echo(f"--- Tree render failed: {exc} ---", err=True)
            return
        if not any(r_root.iterdir()):
            click.echo("No platform data or STIG artifacts found; writing empty site + search stubs.")
            _write_empty_site_and_search(r_root, common_vars)
            return
        _write_tree_only_site_and_search(r_root, tree_roots, common_vars)
        return

    global_changed = force or not hosts_unchanged(global_data, str(all_hosts_state))
    if global_changed:
        write_output(global_data, str(all_hosts_state))
    else:
        click.echo("  Global state unchanged.")
    global_hosts = global_data.get("hosts", global_data)

    # Step 1c: Build STIG host views (skeleton fallback; CKLB not yet generated)
    click.echo("--- Pre-building STIG widget views ---")
    stig_host_views = build_stig_host_views(
        global_hosts,
        common_vars,
        cklb_dir=None,
        generated_fleet_dirs=generated_fleet_dirs,
        global_inventory_index=global_inventory_index,
        registry=runtime_registry,
        has_site_report=True,
    )
    if stig_host_views:
        click.echo(f"  Built STIG views for {len(stig_host_views)} host(s).")

    # Step 2: Hierarchical tree render — the one and only page layer.
    _tree_roots, tree_host_urls, tree_products = _render_inventory_trees(
        r_root, all_platform_data, extra_dirs, common_vars, bundle_root=b_root,
    )

    # Step 3: Site dashboard + search index. Tree host URLs are the source
    # of truth for search-index entries now that legacy platform/<p>/<host>/
    # host.html pages are no longer generated.
    _render_site_and_search(
        r_root, global_data, global_changed,
        common_vars, global_inventory_index, platforms_by_report_dir,
        runtime_registry,
        generated_fleet_dirs,
        tree_host_urls=tree_host_urls,
        tree_products=tree_products,
    )

    # Step 4 & 5: CKLB export + STIG fleet rendering (tree-layout still feeds these)
    _render_stig_and_cklb(
        r_root, global_hosts, global_changed, all_hosts_state,
        common_vars, global_inventory_index, generated_fleet_dirs,
        runtime_registry, config_dir,
        tree_products=tree_products,
    )
