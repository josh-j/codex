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
from ._report_context import generate_timestamps
from .aggregation import hosts_unchanged, write_output
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
from .models.platforms_config import PlatformEntry
from .pipeline.site import _render_site_and_search, _write_empty_site_and_search
from .pipeline.stig import _render_stig_and_cklb
from .pipeline.tree import (
    _merge_tree_bundles_into_global,
    _merge_tree_stig_artifacts_into_global,
    _render_inventory_trees,
)
from .platform_registry import PlatformRegistry

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
    reports_root: str,
    bundle_root: str | None,
    report_stamp: str | None,
    config_dir: str | None,
    extra_config_dir: tuple[str, ...],
    platforms_config: str | None,
    force: bool,
) -> None:
    """Run full tree aggregation and render the site dashboard."""
    r_root = Path(reports_root)
    b_root = Path(bundle_root) if bundle_root else r_root
    r_root.mkdir(parents=True, exist_ok=True)

    # Step 0: Resolve configuration
    _config_yaml, effective_stamp, extra_dirs, platforms = (
        _resolve_effective_config(config_dir, report_stamp, extra_config_dir, platforms_config)
    )
    common_vars = generate_timestamps(effective_stamp)

    runtime_registry = PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])
    generated_fleet_dirs: set[str] = set()
    global_inventory_index: dict[str, str] = {}
    global_data: dict[str, Any] = {
        "metadata": {
            "generated_at": common_vars["now_datetime"],
            "fleet_stats": {"total_hosts": 0, "critical_alerts": 0, "warning_alerts": 0},
        },
        "hosts": {},
    }

    # Step 1: Global aggregation from tree-layout bundles only.
    click.echo("--- Aggregating Global State ---")
    _merge_tree_bundles_into_global(b_root, global_data, global_inventory_index, extra_dirs=extra_dirs)
    _merge_tree_stig_artifacts_into_global(b_root, global_data, extra_dirs=extra_dirs)

    all_hosts_state = r_root / "all_hosts_state.yaml"
    if not global_data["hosts"]:
        try:
            tree_roots, _tree_host_urls, _tree_products = _render_inventory_trees(
                r_root, extra_dirs, common_vars, bundle_root=b_root
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Hierarchical tree render failed: %s", exc)
            click.echo(f"--- Tree render failed: {exc} ---", err=True)
            return
        if not any(r_root.iterdir()):
            click.echo("No platform data or STIG artifacts found; writing empty site + search stubs.")
            _write_empty_site_and_search(r_root, common_vars)
            return
        _render_site_and_search(
            r_root, global_data, True,
            common_vars, global_inventory_index, {},
            runtime_registry,
            generated_fleet_dirs=generated_fleet_dirs,
            tree_host_urls=_tree_host_urls,
            tree_products=_tree_products,
        )
        return

    global_changed = force or not hosts_unchanged(global_data, str(all_hosts_state))
    if global_changed:
        write_output(global_data, str(all_hosts_state))
    else:
        click.echo("  Global state unchanged.")
    global_hosts = global_data.get("hosts", global_data)

    # Step 2: Hierarchical tree render — the one and only inventory page layer.
    _tree_roots, tree_host_urls, tree_products = _render_inventory_trees(
        r_root, extra_dirs, common_vars, bundle_root=b_root,
    )

    # Step 3: Site dashboard + search index. Tree host URLs are the source
    # of truth for search-index entries.
    _render_site_and_search(
        r_root, global_data, global_changed,
        common_vars, global_inventory_index, {},
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
        tree_host_urls=tree_host_urls,
    )
