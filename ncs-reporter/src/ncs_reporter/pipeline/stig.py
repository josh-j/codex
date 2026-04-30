"""STIG and CKLB writers for the full report pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from .._cli_stig_cklb import _generate_cklb_artifacts, _resolve_extra_config_dirs
from .._report_context import load_hosts_data
from .._renderers import render_stig
from ..platform_registry import PlatformRegistry


def _render_stig_and_cklb(
    r_root: Path,
    global_hosts: dict[str, Any],
    global_changed: bool,
    all_hosts_state: Path,
    common_vars: dict[str, Any],
    global_inventory_index: dict[str, str],
    generated_fleet_dirs: set[str],
    runtime_registry: PlatformRegistry,
    config_dir: str | None,
    tree_products: list[dict[str, str]] | None = None,
    tree_host_urls: dict[str, str] | None = None,
) -> None:
    """Generate CKLB artifacts and render STIG fleet reports."""
    if not global_changed:
        click.echo("--- Skipping CKLB Artifacts (unchanged) ---")
    else:
        click.echo("--- Generating CKLB Artifacts ---")
        cklb_output = r_root / "cklb"
        cklb_output.mkdir(parents=True, exist_ok=True)
        _generate_cklb_artifacts(
            load_hosts_data(str(all_hosts_state)),
            cklb_output,
            registry=runtime_registry,
            config_dir=Path(config_dir) if config_dir else None,
            extra_config_dirs=_resolve_extra_config_dirs(config_dir),
        )

    if not global_changed:
        click.echo("--- Skipping STIG Fleet Reports (unchanged) ---")
    else:
        click.echo("--- Processing STIG Fleet Reports ---")
        render_stig(
            global_hosts,
            r_root,
            common_vars,
            global_inventory_index=global_inventory_index,
            cklb_dir=r_root / "cklb",
            generated_fleet_dirs=generated_fleet_dirs,
            registry=runtime_registry,
            has_site_report=True,
            tree_products=tree_products,
            tree_host_urls=tree_host_urls,
        )
        click.echo("STIG fleet reports and CKLB artifacts generated.")
