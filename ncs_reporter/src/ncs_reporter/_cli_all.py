"""Extract of the ``all`` command and its helper functions from ``cli``."""

from __future__ import annotations

import json
import logging
from collections import Counter as _Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from ._config import (
    default_paths,
    load_config_yaml,
    load_platforms,
    resolve_config_dir,
    resolve_path_from_config_root,
)
from ._renderers import PlatformRenderConfig, build_stig_host_views, render_platform, render_stig
from ._report_context import (
    generate_timestamps,
    get_jinja_env,
    load_hosts_data,
    report_context,
)
from .aggregation import deep_merge, hosts_unchanged, load_all_reports, normalize_host_bundle, read_report, write_output
from ._cli_stig_cklb import _generate_cklb_artifacts
from .models.platforms_config import PlatformEntry
from .pathing import render_template
from .platform_registry import PlatformRegistry
from .schema_loader import discover_schemas
from .view_models.site import build_site_dashboard_view

logger = logging.getLogger("ncs_reporter")


# ---------------------------------------------------------------------------
# all – helper functions
# ---------------------------------------------------------------------------


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
    """Scan platform ``report_dir`` paths for STIG artifacts.

    The ncs_collector writes STIG results to ``platform/{report_dir}/{host}/
    raw_stig_{target_type}.yaml``, which may differ from the ``input_dir``
    used by :func:`_aggregate_platforms`.  This function loads those files
    so STIG-only runs (no collection data) still produce reports.

    Returns a hosts dict (``{hostname: {audit_type: payload, ...}}``).
    """
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


def _augment_platforms_from_schemas(
    platforms: list[dict[str, Any]],
    extra_dirs: tuple[str, ...],
    p_root: Path,
) -> None:
    """Discover schemas not already in *platforms* and append synthetic entries in-place."""
    configured_platforms = {p["platform"] for p in platforms}
    custom_seen: set[str] = set()
    for _schema in discover_schemas(extra_dirs=extra_dirs).values():
        if _schema.platform in configured_platforms or _schema.platform in custom_seen:
            continue
        if not (p_root / _schema.platform).is_dir():
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
    """Return True if *bundle* matches the detection keys of any listed schema."""
    for sn in schema_names:
        schema = all_schemas.get(sn)
        if not schema:
            return True  # unknown schema — assume match
        det = schema.detection
        if not det.keys_any and not det.keys_all:
            return True  # no filter = match all
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
    """Return True if any host bundle matches the detection keys of listed schemas."""
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
    """Load platform data, write state files, and build render tasks.

    Returns ``(render_tasks, global_inventory_index, all_platform_data,
    platforms_by_report_dir, runtime_registry)``.
    """
    render_tasks: list[dict[str, Any]] = []
    global_inventory_index: dict[str, str] = {}
    platforms_by_report_dir: dict[str, dict[str, Any]] = {str(p["report_dir"]): p for p in platforms}
    runtime_registry = PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])
    all_platform_data: dict[str, dict[str, Any]] = {}

    _loaded_platform_cache: dict[str, dict[str, Any] | None] = {}
    _changed_dirs: set[str] = set()

    # Identify input_dirs shared by multiple platform entries.  When an
    # input_dir is shared (e.g. vmware/vcenter used by esxi, vcsa, vm),
    # we filter render tasks by schema detection keys so that only entries
    # with matching data get rendered.
    _input_dir_counts = _Counter(p["input_dir"] for p in platforms)
    _shared_input_dirs = {d for d, c in _input_dir_counts.items() if c > 1}

    _cached_schemas: dict[str, Any] | None = None
    if _shared_input_dirs:
        from .schema_loader import discover_schemas as _discover_schemas
        _cached_schemas = _discover_schemas(extra_dirs)

    for p in platforms:
        p_input = p["input_dir"]
        p_dir = p_root / p_input
        if not p_dir.is_dir():
            continue

        # Load data and write state once per input_dir
        if p_input not in _loaded_platform_cache:
            click.echo(f"--- Processing Platform: {p_input} ---")
            p_data = load_all_reports(str(p_dir), host_normalizer=normalize_host_bundle)
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

        # When multiple entries share the same input_dir, skip this entry
        # if no host bundles match its schema detection keys.
        if p_input in _shared_input_dirs and _cached_schemas is not None:
            schema_names = p.get("schema_names", [])
            if schema_names and not _any_host_matches_schemas(
                p_data["hosts"], schema_names, _cached_schemas,
            ):
                click.echo(f"  Skipping {p['report_dir']}: no data matches schemas {schema_names}")
                continue

        if p.get("render", True):
            from .models.platforms_config import PLATFORM_DIR_PREFIX as _PDP
            output_dir = r_root / _PDP / p["report_dir"]
            output_dir.mkdir(parents=True, exist_ok=True)
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
    """Render platform reports in parallel using a thread pool."""
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


def _render_site_and_search(
    r_root: Path,
    global_data: dict[str, Any],
    global_changed: bool,
    common_vars: dict[str, Any],
    global_inventory_index: dict[str, str],
    platforms_by_report_dir: dict[str, dict[str, Any]],
    generated_fleet_dirs: set[str] | None = None,
) -> None:
    """Render the site dashboard and generate the search index."""
    # Site dashboard
    if not global_changed:
        click.echo("--- Skipping Global Site Dashboard (unchanged) ---")
    else:
        from .models.platforms_config import FILENAME_SITE_HEALTH as _FILENAME_SITE_HEALTH, TEMPLATE_SITE as _TEMPLATE_SITE
        click.echo("--- Processing Global Site Dashboard ---")
        site_view = build_site_dashboard_view(
            global_data,
            ctx=report_context(common_vars),
            generated_fleet_dirs=generated_fleet_dirs,
        )
        env = get_jinja_env()
        content = env.get_template(_TEMPLATE_SITE).render(site_dashboard_view=site_view, **common_vars)
        (r_root / _FILENAME_SITE_HEALTH).write_text(content)
        click.echo(f"Global dashboard generated at {r_root}/{_FILENAME_SITE_HEALTH}")

    # Search index
    search_index = []
    for hostname, rep_dir in global_inventory_index.items():
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
) -> None:
    """Generate CKLB artifacts and render STIG fleet reports."""
    # CKLB export
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
        )

    # STIG fleet rendering
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
        )
        click.echo("STIG fleet reports and CKLB artifacts generated.")


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------


@click.command("all")
@click.option("--platform-root", required=True, type=click.Path(exists=True))
@click.option("--reports-root", required=True, type=click.Path())
@click.option("--report-stamp")
@click.option("--config-dir", default=None, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--extra-config-dir", "-S", multiple=True, metavar="DIR")
@click.option("--platforms-config", "-P", default=None, type=click.Path(exists=True))
@click.option("--force", is_flag=True, default=False, help="Force re-render even if data is unchanged.")
def all_cmd(
    platform_root: str,
    reports_root: str,
    report_stamp: str | None,
    config_dir: str | None,
    extra_config_dir: tuple[str, ...],
    platforms_config: str | None,
    force: bool,
) -> None:
    """Run full aggregation and rendering for all platforms and the site dashboard."""
    p_root = Path(platform_root)
    r_root = Path(reports_root)
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
                hostname, global_data["hosts"][hostname]
            )
        global_data["metadata"]["fleet_stats"]["total_hosts"] = len(global_data["hosts"])

    if not global_data["hosts"]:
        click.echo("No platform data or STIG artifacts found; nothing to render.")
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
    has_stig_fleet = bool(stig_host_views)
    if stig_host_views:
        click.echo(f"  Built STIG views for {len(stig_host_views)} host(s).")

    # Step 2: Parallel platform rendering
    _render_platforms(render_tasks, common_vars, global_inventory_index, generated_fleet_dirs, stig_host_views, has_stig_fleet=has_stig_fleet)

    # Step 3: Site dashboard + search index
    _render_site_and_search(
        r_root, global_data, global_changed,
        common_vars, global_inventory_index, platforms_by_report_dir,
        generated_fleet_dirs,
    )

    # Step 4 & 5: CKLB export + STIG fleet rendering
    _render_stig_and_cklb(
        r_root, global_hosts, global_changed, all_hosts_state,
        common_vars, global_inventory_index, generated_fleet_dirs,
        runtime_registry, config_dir,
    )
