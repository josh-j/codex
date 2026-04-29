"""Legacy platform-layout adapter for the full report pipeline."""

from __future__ import annotations

import logging
from collections import Counter as _Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

import click

from .._config import default_paths
from .._renderers import PlatformRenderConfig, render_platform
from ..aggregation import hosts_unchanged, load_all_reports, normalize_host_bundle, read_report, write_output
from ..models.platforms_config import PLATFORM_DIR_PREFIX, PlatformEntry
from ..platform_registry import PlatformRegistry
from ..schema_loader import discover_schemas

logger = logging.getLogger("ncs_reporter")


def _merge_platform_data(platform_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Merge per-platform aggregated data into a single global dict."""
    merged: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "fleet_stats": {"total_hosts": 0, "critical_alerts": 0, "warning_alerts": 0},
        },
        "hosts": {},
    }
    for p_data in platform_data.values():
        if not p_data or "hosts" not in p_data:
            continue
        for hostname, bundle in p_data["hosts"].items():
            if hostname in merged["hosts"] and isinstance(bundle, dict):
                merged["hosts"][hostname].update(bundle)
            else:
                merged["hosts"][hostname] = bundle
        p_stats = p_data.get("metadata", {}).get("fleet_stats", {})
        merged["metadata"]["fleet_stats"]["critical_alerts"] += p_stats.get("critical_alerts", 0)
        merged["metadata"]["fleet_stats"]["warning_alerts"] += p_stats.get("warning_alerts", 0)
    merged["metadata"]["fleet_stats"]["total_hosts"] = len(merged["hosts"])
    return merged


def _load_stig_artifacts(
    platforms: list[dict[str, Any]],
    p_root: Path,
) -> dict[str, dict[str, Any]]:
    """Scan platform ``report_dir`` paths for STIG artifacts."""
    stig_hosts: dict[str, dict[str, Any]] = {}
    seen_dirs: set[str] = set()

    for p in platforms:
        report_dir = p.get("report_dir", "")
        if not report_dir or report_dir in seen_dirs:
            continue
        seen_dirs.add(report_dir)

        stig_dir = p_root / report_dir
        if not stig_dir.is_dir():
            continue

        for host_entry in sorted(stig_dir.iterdir()):
            if not host_entry.is_dir():
                continue
            hostname = host_entry.name
            for yaml_file in sorted(host_entry.glob("raw_stig_*.yaml")):
                try:
                    _raw, report, audit_type = read_report(str(yaml_file))
                    if report is None or audit_type is None:
                        continue
                    stig_hosts.setdefault(hostname, {})[audit_type] = report
                except Exception:
                    continue

    return stig_hosts


def _augment_platforms_from_schemas(
    platforms: list[dict[str, Any]],
    extra_dirs: tuple[str, ...],
    p_root: Path,
) -> None:
    """Append synthetic platform entries for discoverable schemas not in platforms."""
    del p_root  # retained for backwards-compatible callers
    configured_platforms = {p["platform"] for p in platforms}
    custom_seen: set[str] = set()
    for _schema in discover_schemas(extra_dirs=extra_dirs).values():
        if _schema.platform in configured_platforms or _schema.platform in custom_seen:
            continue
        custom_seen.add(_schema.platform)
        platforms.append({
            "input_dir": _schema.platform,
            "report_dir": _schema.platform,
            "platform": _schema.platform,
            "render": True,
            "schema_name": _schema.name,
            "schema_names": [_schema.name],
            "paths": default_paths(),
        })


def _bundle_matches_schemas(
    bundle: dict[str, Any],
    schema_names: list[str],
    all_schemas: dict[str, Any],
) -> bool:
    """Return True if *bundle* matches detection keys of any listed schema."""
    for sn in schema_names:
        schema = all_schemas.get(sn)
        if not schema:
            return True
        det = schema.detection
        if not det.keys_any and not det.keys_all:
            return True
        if det.keys_any and any(k in bundle for k in det.keys_any):
            return True
        if det.keys_all and all(k in bundle for k in det.keys_all):
            return True
    return False


def _any_host_matches_schemas(
    hosts: dict[str, dict[str, Any]],
    schema_names: list[str],
    all_schemas: dict[str, Any],
) -> bool:
    """Return True if any host bundle matches the listed schemas."""
    for bundle in hosts.values():
        if _bundle_matches_schemas(bundle, schema_names, all_schemas):
            return True
    return False


def _aggregate_platforms(
    platforms: list[dict[str, Any]],
    p_root: Path,
    r_root: Path,
    extra_dirs: tuple[str, ...],
    force: bool,
) -> tuple[
    list[dict[str, Any]],
    dict[str, str],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    PlatformRegistry,
]:
    """Load legacy platform data, write state files, and build render tasks."""
    render_tasks: list[dict[str, Any]] = []
    global_inventory_index: dict[str, str] = {}
    platforms_by_report_dir: dict[str, dict[str, Any]] = {str(p["report_dir"]): p for p in platforms}
    runtime_registry = PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])
    all_platform_data: dict[str, dict[str, Any]] = {}

    _loaded_platform_cache: dict[str, dict[str, Any] | None] = {}
    _changed_dirs: set[str] = set()

    _input_dir_counts = _Counter(p["input_dir"] for p in platforms)
    _shared_input_dirs = {d for d, c in _input_dir_counts.items() if c > 1}

    _cached_schemas: dict[str, Any] | None = None
    if _shared_input_dirs:
        _cached_schemas = discover_schemas(extra_dirs)

    for p in platforms:
        p_input = p["input_dir"]
        p_dir = p_root / p_input
        if not p_dir.is_dir():
            continue

        if p_input not in _loaded_platform_cache:
            click.echo(f"--- Processing Platform: {p_input} ---")
            p_data = load_all_reports(
                str(p_dir),
                host_normalizer=partial(normalize_host_bundle, extra_dirs=extra_dirs),
            )
            if not p_data or not p_data["hosts"]:
                click.echo(f"No data for {p_input}, skipping.")
                _loaded_platform_cache[p_input] = None
                continue
            _loaded_platform_cache[p_input] = p_data
            all_platform_data[p_input] = p_data
            for hostname in p_data["hosts"]:
                if hostname not in global_inventory_index:
                    global_inventory_index[hostname] = p["report_dir"]
            state_path = str(p_dir / f"{p['platform']}_fleet_state.yaml")
            if not force and hosts_unchanged(p_data, state_path):
                click.echo(f"  {p_input} unchanged, skipping.")
            else:
                write_output(p_data, state_path)
                _changed_dirs.add(p_input)
        else:
            p_data = _loaded_platform_cache[p_input]
            if p_data is None:
                continue

        if p_input not in _changed_dirs:
            continue

        if p_input in _shared_input_dirs and _cached_schemas is not None:
            schema_names = p.get("schema_names", [])
            if schema_names and not _any_host_matches_schemas(
                p_data["hosts"], schema_names, _cached_schemas,
            ):
                click.echo(f"  Skipping {p['report_dir']}: no data matches schemas {schema_names}")
                continue

        if p.get("render", True):
            output_dir = r_root / PLATFORM_DIR_PREFIX / p["report_dir"]
            task: dict[str, Any] = {
                "platform": p["platform"],
                "hosts_data": p_data["hosts"],
                "output_path": output_dir,
                "report_dir": p["report_dir"],
                "platform_paths": p["paths"],
                "extra_config_dirs": extra_dirs,
            }
            if p.get("schema_names"):
                task["schema_names_override"] = p["schema_names"]
            render_tasks.append(task)

    return render_tasks, global_inventory_index, all_platform_data, platforms_by_report_dir, runtime_registry


def _render_platforms(
    render_tasks: list[dict[str, Any]],
    common_vars: dict[str, Any],
    global_inventory_index: dict[str, str],
    generated_fleet_dirs: set[str],
    stig_host_views: dict[str, Any],
    *,
    has_stig_fleet: bool = False,
) -> None:
    """Render legacy platform reports in parallel using a thread pool."""
    if not render_tasks:
        return
    with ThreadPoolExecutor(max_workers=min(len(render_tasks), 3)) as pool:
        futures = {
            pool.submit(
                render_platform,
                t["platform"],
                t["hosts_data"],
                t["output_path"],
                common_vars,
                config=PlatformRenderConfig(
                    global_inventory_index=global_inventory_index,
                    generated_fleet_dirs=generated_fleet_dirs,
                    report_dir=t["report_dir"],
                    platform_paths=t["platform_paths"],
                    extra_config_dirs=t.get("extra_config_dirs", ()),
                    schema_names_override=t.get("schema_names_override"),
                    has_site_report=True,
                    has_stig_fleet=has_stig_fleet,
                    stig_widgets_by_host=stig_host_views,
                ),
            ): t["platform"]
            for t in render_tasks
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                click.echo(f"  Rendered {name} reports.")
            except Exception as exc:
                logger.error("Failed to render %s: %s", name, exc)
                click.echo(f"  ERROR rendering {name}: {exc}")
