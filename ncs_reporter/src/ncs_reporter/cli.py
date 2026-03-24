"""NCS Reporter CLI entry point."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import yaml

from ._config import (
    default_paths,
    load_config_yaml,
    load_platforms,
    resolve_config_dir,
    resolve_path_from_config_root,
)
from ._report_context import (
    generate_timestamps,
    get_jinja_env,
    load_hosts_data,
    load_yaml,
    vm_kwargs,
    write_report,
)
from ._renderers import build_stig_host_views, render_platform, render_stig
from ._schema_utils import annotated_template, schema_from_bundle, schema_template
from .aggregation import deep_merge, hosts_unchanged, load_all_reports, normalize_host_bundle, read_report, write_output
from .cklb_export import generate_cklb
from .models.platforms_config import PlatformEntry
from .models.report_schema import ReportSchema
from .pathing import rel_href, render_template
from .platform_registry import PlatformRegistry, default_registry
from .schema_loader import (
    discover_schemas,
    load_example_bundle,
    load_schema_from_file,
    validate_schema_paths,
)
from .view_models.generic import build_generic_fleet_view, build_generic_node_view
from .view_models.site import build_site_dashboard_view

logger = logging.getLogger("ncs_reporter")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug-level logging.")
def main(verbose: bool) -> None:
    """NCS Reporter: Standalone reporting CLI for Codex."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )


# ---------------------------------------------------------------------------
# validate-config
# ---------------------------------------------------------------------------


@main.command("validate-config")
@click.option(
    "--platforms-config", "-P",
    type=click.Path(exists=True), default=None,
    help="Path to platforms.yaml config.",
)
def validate_config(platforms_config: str | None) -> None:
    """Validate a platforms config file."""
    try:
        entries = load_platforms(platforms_config)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    from ncs_path_contract import validate_platforms_config_dict
    try:
        validate_platforms_config_dict({"platforms": entries})
    except ValueError as exc:
        raise click.ClickException(f"Path contract error: {exc}") from exc

    target_types = sorted({t for e in entries for t in e.get("target_types", [])})
    seen: set[str] = set()
    renderable = [p for e in entries if e.get("render", True) for p in [e["platform"]] if p not in seen and not seen.add(p)]  # type: ignore[func-returns-value]
    click.echo(f"Valid! {len(entries)} platform entries, {len(target_types)} target types.")
    click.echo(f"  Target types: {', '.join(target_types)}")
    click.echo(f"  Renderable platforms: {', '.join(renderable)}")


# ---------------------------------------------------------------------------
# Single-platform commands (linux, vmware, windows)
# ---------------------------------------------------------------------------


def _platform_command(platform: str, input_file: str, output_dir: str, report_stamp: str | None) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)
    report_dir = default_registry().platform_to_report_dir(platform) or platform
    render_platform(
        platform,
        hosts_data,
        output_path,
        common_vars,
        report_dir=report_dir,
        platform_paths=default_paths(),
    )
    click.echo(f"Done! Reports generated in {output_dir}")


def _register_platform_commands() -> None:
    """Dynamically register per-platform CLI commands from the default registry."""
    for p_name in default_registry().all_platform_names():
        display = default_registry().platform_display_name(p_name)

        @main.command(name=p_name)
        @click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
        @click.option("--output-dir", "-o", required=True, type=click.Path())
        @click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
        @click.pass_context
        def _cmd(ctx: click.Context, input_file: str, output_dir: str, report_stamp: str | None,
                 _platform: str = p_name, _display: str = display) -> None:
            f"""Generate {_display} fleet and node reports."""
            _platform_command(_platform, input_file, output_dir, report_stamp)

        _cmd.__doc__ = f"Generate {display} fleet and node reports."


_register_platform_commands()


# ---------------------------------------------------------------------------
# site
# ---------------------------------------------------------------------------


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--groups", "-g", "groups_file", type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
def site(input_file: str, groups_file: str | None, output_dir: str, report_stamp: str | None) -> None:
    """Generate Global Site Health dashboard."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    data = load_yaml(input_file)
    common_vars = generate_timestamps(report_stamp)
    groups_data = _load_groups(groups_file)

    from .models.platforms_config import FILENAME_SITE_HEALTH, TEMPLATE_SITE
    click.echo("Rendering Global Site Health dashboard...")
    site_view = build_site_dashboard_view(data, inventory_groups=groups_data, **vm_kwargs(common_vars))
    env = get_jinja_env()
    content = env.get_template(TEMPLATE_SITE).render(site_dashboard_view=site_view, **common_vars)
    (output_path / FILENAME_SITE_HEALTH).write_text(content)
    click.echo(f"Done! Global dashboard generated in {output_dir}")


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


@main.command()
@click.option("--report-dir", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--filter", "audit_filter")
def collect(report_dir: str, output: str, audit_filter: str | None) -> None:
    """Aggregate host YAML reports into a single fleet state file."""
    click.echo(f"Aggregating reports from {report_dir}...")
    data = load_all_reports(report_dir, audit_filter=audit_filter)
    if data:
        write_output(data, output)
        click.echo(f"Success: Aggregated {len(data['hosts'])} hosts into {output}")
    else:
        click.echo("Error: No data found or directory invalid.")


# ---------------------------------------------------------------------------
# CKLB generation core logic
# ---------------------------------------------------------------------------


def _resolve_skeleton_path(
    skeleton_file: str,
    *,
    explicit_skeleton_dir: Path | None,
    config_dir: Path | None,
    builtin_skeleton_dir: Path,
) -> Path | None:
    """Resolve a skeleton file path using a layered search.

    Resolution order:
      1. --skeleton-dir / bare filename  (legacy explicit CLI override)
      2. --config-dir / path-from-schema (supports subdirs like cklb_skeletons/)
      3. Package builtins / bare filename (bundled VMware/Photon skeletons)
    """
    bare_name = Path(skeleton_file).name

    if explicit_skeleton_dir:
        candidate = explicit_skeleton_dir / bare_name
        if candidate.exists():
            return candidate

    if config_dir:
        candidate = config_dir / skeleton_file
        if candidate.exists():
            return candidate

    candidate = builtin_skeleton_dir / bare_name
    if candidate.exists():
        return candidate

    return None


def _generate_cklb_artifacts(
    hosts_data: dict[str, Any],
    output_path: Path,
    *,
    registry: PlatformRegistry | None = None,
    explicit_skeleton_dir: Path | None = None,
    config_dir: Path | None = None,
) -> None:
    """Core CKLB generation logic.

    Called directly from ``all_cmd`` (with the runtime registry already built
    from --config-dir) and wrapped by the ``cklb`` CLI command for standalone
    invocation.
    """
    from .models.platforms_config import CKLB_SKELETONS_DIR
    effective_registry = registry or default_registry()
    builtin_skeleton_dir = Path(__file__).parent / CKLB_SKELETONS_DIR

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig") or not isinstance(payload, dict):
                continue
            target_type = str(payload.get("target_type", ""))
            skeleton_file = effective_registry.stig_skeleton_for_target(target_type)
            if not skeleton_file:
                logger.debug(
                    "No skeleton mapping for target_type '%s' on host '%s' (audit_type='%s')",
                    target_type, hostname, audit_type,
                )
                continue

            sk_path = _resolve_skeleton_path(
                skeleton_file,
                explicit_skeleton_dir=explicit_skeleton_dir,
                config_dir=config_dir,
                builtin_skeleton_dir=builtin_skeleton_dir,
            )

            if sk_path is None:
                searched = " \u2192 ".join(filter(None, [
                    str(explicit_skeleton_dir / Path(skeleton_file).name) if explicit_skeleton_dir else None,
                    str(config_dir / skeleton_file) if config_dir else None,
                    str(builtin_skeleton_dir / Path(skeleton_file).name),
                ]))
                click.echo(
                    f"Warning: Skeleton not found for {target_type}: {skeleton_file} "
                    f"(searched: {searched})"
                )
                continue

            ip_addr = str(payload.get("ip_address") or bundle.get("ip_address") or "")
            dest = output_path / f"{hostname}_{target_type}.cklb"
            generate_cklb(hostname, payload.get("full_audit", []), sk_path, dest, ip_address=ip_addr)
            click.echo(f"Generated CKLB: {dest}")


def _registry_from_config_dir(config_dir: str | None) -> PlatformRegistry | None:
    """Build a PlatformRegistry from --config-dir if provided, else None."""
    if not config_dir:
        return None
    try:
        config_yaml = load_config_yaml(config_dir)
        _extra_dirs, _platforms_cfg = resolve_config_dir(config_dir, (), None, config_yaml)
        platforms = load_platforms(_platforms_cfg, extra_config_dirs=_extra_dirs)
        return PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])
    except Exception as exc:
        logger.warning("Could not build registry from config-dir '%s': %s", config_dir, exc)
        return None


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


# ---------------------------------------------------------------------------
# all – helper functions
# ---------------------------------------------------------------------------


def _resolve_effective_config(
    config_dir: str | None,
    report_stamp: str | None,
    groups_file: str | None,
    extra_config_dir: tuple[str, ...],
    platforms_config: str | None,
) -> tuple[dict[str, Any], str | None, str | None, tuple[str, ...], list[dict[str, Any]]]:
    """Resolve config_yaml, effective stamp, groups file, extra dirs, and platforms list.

    Returns ``(common_vars_seed, effective_stamp, effective_groups_file,
    extra_dirs, platforms)``.  The caller still needs to call
    ``generate_timestamps`` on *effective_stamp*.
    """
    config_yaml = load_config_yaml(config_dir)
    effective_stamp = report_stamp or (
        str(config_yaml["report_stamp"]) if config_yaml.get("report_stamp") is not None else None
    )
    effective_groups_file = groups_file or (
        resolve_path_from_config_root(config_dir, config_yaml["groups_file"].strip())
        if isinstance(config_yaml.get("groups_file"), str) and config_yaml["groups_file"].strip()
        else None
    )

    _extra_dirs, _platforms_cfg = resolve_config_dir(config_dir, extra_config_dir, platforms_config, config_yaml)
    platforms = load_platforms(_platforms_cfg, extra_config_dirs=_extra_dirs)

    return config_yaml, effective_stamp, effective_groups_file, _extra_dirs, platforms


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
            "state_file": f"{_schema.platform}_fleet_state.yaml",
            "render": True,
            "schema_name": _schema.name,
            "schema_names": [_schema.name],
            "target_types": [],
            "paths": default_paths(),
        })


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
                global_inventory_index[hostname] = p["report_dir"]
            state_path = str(p_dir / p["state_file"])
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
                global_inventory_index=global_inventory_index,
                generated_fleet_dirs=generated_fleet_dirs,
                report_dir=t["report_dir"],
                platform_paths=t["platform_paths"],
                extra_config_dirs=t.get("extra_config_dirs", ()),
                schema_names_override=t.get("schema_names_override"),
                has_site_report=True,
                has_stig_fleet=True,
                stig_widgets_by_host=stig_host_views,
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
    effective_groups_file: str | None,
    common_vars: dict[str, Any],
    global_inventory_index: dict[str, str],
    platforms_by_report_dir: dict[str, dict[str, Any]],
) -> None:
    """Render the site dashboard and generate the search index."""
    # Site dashboard
    if not global_changed:
        click.echo("--- Skipping Global Site Dashboard (unchanged) ---")
    else:
        from .models.platforms_config import FILENAME_SITE_HEALTH as _FILENAME_SITE_HEALTH, TEMPLATE_SITE as _TEMPLATE_SITE
        click.echo("--- Processing Global Site Dashboard ---")
        groups_data = _load_groups(effective_groups_file)
        site_view = build_site_dashboard_view(global_data, inventory_groups=groups_data, **vm_kwargs(common_vars))
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
    *,
    has_site_report: bool = True,
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
            has_site_report=has_site_report,
        )
        click.echo("STIG fleet reports and CKLB artifacts generated.")


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------


@main.command("all")
@click.option("--platform-root", required=True, type=click.Path(exists=True))
@click.option("--reports-root", required=True, type=click.Path())
@click.option("--groups", "groups_file", type=click.Path(exists=True))
@click.option("--report-stamp")
@click.option("--config-dir", default=None, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--extra-config-dir", "-S", multiple=True, metavar="DIR")
@click.option("--platforms-config", "-P", default=None, type=click.Path(exists=True))
@click.option("--force", is_flag=True, default=False, help="Force re-render even if data is unchanged.")
def all_cmd(
    platform_root: str,
    reports_root: str,
    groups_file: str | None,
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
    _config_yaml, effective_stamp, effective_groups_file, extra_dirs, platforms = (
        _resolve_effective_config(config_dir, report_stamp, groups_file, extra_config_dir, platforms_config)
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
    has_platform_data = bool(global_data["hosts"])

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
        has_site_report=has_platform_data,
    )
    if stig_host_views:
        click.echo(f"  Built STIG views for {len(stig_host_views)} host(s).")

    # Step 2: Parallel platform rendering
    _render_platforms(render_tasks, common_vars, global_inventory_index, generated_fleet_dirs, stig_host_views)

    # Step 3: Site dashboard + search index (skip if no collection data)
    if has_platform_data:
        _render_site_and_search(
            r_root, global_data, global_changed, effective_groups_file,
            common_vars, global_inventory_index, platforms_by_report_dir,
        )
    else:
        click.echo("--- Skipping Site Dashboard (no collection data) ---")

    # Step 4 & 5: CKLB export + STIG fleet rendering
    _render_stig_and_cklb(
        r_root, global_hosts, global_changed, all_hosts_state,
        common_vars, global_inventory_index, generated_fleet_dirs,
        runtime_registry, config_dir,
        has_site_report=has_platform_data,
    )


# ---------------------------------------------------------------------------
# node
# ---------------------------------------------------------------------------


@main.command()
@click.option("--platform", "-p", required=True, type=click.Choice(default_registry().all_platform_names()))
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--hostname", "-n", required=True)
@click.option("--output-dir", "-o", required=True, type=click.Path())
def node(platform: str, input_file: str, hostname: str, output_dir: str) -> None:
    """Generate a report for a single host from a raw YAML file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        bundle = yaml.safe_load(f)

    common_vars = generate_timestamps()
    kw = vm_kwargs(common_vars)
    schema_names = default_registry().schema_names_for_platform(platform)
    all_schemas = discover_schemas()
    schema = next((all_schemas[n] for n in schema_names if n in all_schemas), None)
    if schema is None:
        click.echo(f"ERROR: no config found for platform '{platform}'", err=True)
        raise SystemExit(1)

    from .models.platforms_config import TEMPLATE_NODE
    view = build_generic_node_view(schema, hostname, bundle, **kw)
    content = get_jinja_env().get_template(TEMPLATE_NODE).render(
        generic_node_view=view, **common_vars
    )
    dest = output_path / f"{hostname}_health_report.html"
    dest.write_text(content)
    click.echo(f"Success: Report generated at {dest}")


# ---------------------------------------------------------------------------
# platform config command group
# ---------------------------------------------------------------------------


def _validate_config_references(
    s: ReportSchema,
    config_file: Path,
) -> tuple[list[str], list[str]]:
    """Check field references, message formats, and script existence.

    Returns (warnings, errors).
    """
    warnings: list[str] = []
    errors: list[str] = []

    # Unused fields
    referenced: set[str] = set()
    for rule in s.alerts:
        cond = rule.condition
        if hasattr(cond, "field"):
            referenced.add(cond.field)
        for f in rule.detail_fields:
            referenced.add(f)
        if rule.affected_items_field:
            referenced.add(rule.affected_items_field)
    for widget in s.widgets:
        from .models.report_schema import KeyValueWidget, ProgressBarWidget, TableWidget
        if isinstance(widget, KeyValueWidget):
            for kv in widget.fields:
                referenced.add(kv.field)
        elif isinstance(widget, TableWidget):
            referenced.add(widget.rows_field)
        elif isinstance(widget, ProgressBarWidget):
            referenced.add(widget.field)
            if widget.label:
                referenced.add(widget.label)
    for col in s.fleet_columns:
        referenced.add(col.field)
    for spec in s.fields.values():
        for tmpl in [spec.compute or "", *((spec.script_args or {}).values())]:
            if isinstance(tmpl, str):
                for ref in re.findall(r"\{(\w+)\}", tmpl):
                    referenced.add(ref)

    unreferenced = {k for k in s.fields if not k.startswith("_") and k not in referenced}
    if unreferenced:
        warnings.append(f"Unused fields: {', '.join(sorted(unreferenced))}")

    # Message format string references
    import difflib
    declared = set(s.fields.keys())
    for rule in s.alerts:
        for match in re.finditer(r"\{(\w+)", rule.message):
            ref = match.group(1)
            if ref != "value" and not ref.startswith("_") and ref not in declared:
                hint = difflib.get_close_matches(ref, list(declared), n=1, cutoff=0.6)
                suffix = f" (did you mean '{hint[0]}'?)" if hint else ""
                errors.append(f"alert '{rule.id}': message references undeclared field '{ref}'{suffix}")

    # Script file existence
    from .normalization._fields import _resolve_script
    for name, spec in s.fields.items():
        if spec.script is None:
            continue
        if _resolve_script(spec.script, str(config_file)) is None:
            errors.append(f"field '{name}': script '{spec.script}' not found")

    return warnings, errors


@main.group("platform")
def platform() -> None:
    """Manage platform config files."""


@platform.command("list")
@click.option("--extra-config-dir", "-S", multiple=True, metavar="DIR")
def platform_list(extra_config_dir: tuple[str, ...]) -> None:
    """List all discovered platform configs and their source paths."""
    schemas = discover_schemas(extra_dirs=tuple(extra_config_dir))
    if not schemas:
        click.echo("No platform configs found.")
        return
    for name, s in sorted(schemas.items()):
        source = getattr(s, "_source_path", "unknown")
        example_status = "example OK" if load_example_bundle(s) else "no example file"
        click.echo(f"  {name:20s}  platform={s.platform:10s}  {example_status:14s}  {source}")


@platform.command("validate")
@click.argument("config_file", type=click.Path(exists=True, path_type=Path))
def platform_validate(config_file: Path) -> None:
    """Validate a platform config file with comprehensive checks."""
    try:
        s = load_schema_from_file(config_file)
    except ValueError as exc:
        click.echo(f"INVALID: {exc}", err=True)
        raise SystemExit(1)

    warnings, errors = _validate_config_references(s, config_file)

    # Path validation against example bundle
    example = load_example_bundle(s)
    if example is not None:
        for msg in validate_schema_paths(s, example).values():
            errors.append(msg)

    click.echo(f"Config '{s.name}' — {len(s.fields)} fields, {len(s.alerts)} alerts, {len(s.widgets)} widgets")
    for w in warnings:
        click.echo(f"  WARNING: {w}")
    if errors:
        click.echo(f"FAIL: {len(errors)} error(s):")
        for e in errors:
            click.echo(f"  {e}")
        raise SystemExit(1)
    if example is None:
        click.echo(f"  WARNING: no example file ({s.name}.example.yaml) — path validation skipped")
    else:
        path_fields = sum(1 for spec in s.fields.values() if spec.path is not None)
        click.echo(f"  OK: all {path_fields} path field(s) resolve against {s.name}.example.yaml")
    click.echo("Valid!")


@platform.command("init")
@click.option("--name", required=True)
@click.option("--from-bundle", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--annotated", is_flag=True, default=False, help="Include commented examples of every feature.")
def platform_init(name: str, from_bundle: Path | None, output: Path | None, annotated: bool) -> None:
    """Generate a starter platform config YAML template."""
    if from_bundle:
        content = schema_from_bundle(name, from_bundle)
    elif annotated:
        content = annotated_template(name)
    else:
        content = schema_template(name)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        click.echo(f"Config written to {output}")
    else:
        click.echo(content)


@platform.command("run")
@click.argument("config_file", type=click.Path(exists=True, path_type=Path))
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--hostname", "-n", default="host", show_default=True)
@click.option("--report-stamp")
@click.option("--site-report", "site_report_href", default=None)
def platform_run(
    config_file: Path,
    input_file: str,
    output_dir: str,
    hostname: str,
    report_stamp: str | None,
    site_report_href: str | None,
) -> None:
    """Run a single platform config report against a raw YAML bundle."""
    try:
        s = load_schema_from_file(config_file)
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        bundle = yaml.safe_load(f) or {}

    from .models.platforms_config import (
        FILENAME_HEALTH_REPORT as _FHR,
        FILENAME_FLEET_SUFFIX as _FFS,
        TEMPLATE_NODE as _TN,
        TEMPLATE_FLEET as _TF,
    )
    common_vars = generate_timestamps(report_stamp)
    kw = vm_kwargs(common_vars)
    env = get_jinja_env()
    fleet_filename = f"{s.name}{_FFS}"
    node_nav: dict[str, str] = {"fleet_report": f"../{fleet_filename}", "fleet_label": f"{s.display_name} Fleet"}
    fleet_nav: dict[str, str] = {}
    if site_report_href:
        fleet_nav["site_report"] = site_report_href
        node_nav["site_report"] = f"../{site_report_href}"

    node_view = build_generic_node_view(s, hostname, bundle, nav=node_nav, **kw)
    host_dir = output_path / hostname
    host_dir.mkdir(exist_ok=True)
    content = env.get_template(_TN).render(generic_node_view=node_view, **common_vars)
    write_report(host_dir, _FHR, content, common_vars["report_stamp"])
    click.echo(f"Node report: {host_dir}/{_FHR}")

    fleet_view = build_generic_fleet_view(s, {hostname: bundle}, nav=fleet_nav, **kw)
    content = env.get_template(_TF).render(generic_fleet_view=fleet_view, **common_vars)
    write_report(output_path, fleet_filename, content, common_vars["report_stamp"])
    click.echo(f"Fleet report: {output_path}/{fleet_filename}")
    click.echo("Done!")


# ---------------------------------------------------------------------------
# platform info subcommands
# ---------------------------------------------------------------------------


@platform.group("info")
def platform_info() -> None:
    """Show reference information about platform config features."""


@platform_info.command("widgets")
def info_widgets() -> None:
    """List available widget types for platform configs."""
    widgets = [
        ("alert_panel", "Active alerts panel"),
        ("key_value", "Key-value pairs display"),
        ("table", "Data table with columns"),
        ("progress_bar", "Progress/gauge bar with thresholds"),
        ("stat_cards", "KPI summary cards"),
        ("bar_chart", "Horizontal bar chart"),
        ("markdown", "Rendered markdown text"),
        ("list", "Bulleted/numbered list"),
        ("grouped_table", "Table grouped by a field"),
    ]
    click.echo("Widget Types:")
    for name, desc in widgets:
        click.echo(f"  {name:20s} {desc}")


@platform_info.command("conditions")
def info_conditions() -> None:
    """List available alert condition operators."""
    click.echo("Numeric Comparisons:")
    for op, desc in [
        ("gt", "Greater than threshold"),
        ("lt", "Less than threshold"),
        ("gte", "Greater than or equal to threshold"),
        ("lte", "Less than or equal to threshold"),
        ("eq", "Equal to threshold"),
        ("ne", "Not equal to threshold"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nRange:")
    click.echo(f"  {'range':20s} Value within min/max bounds")

    click.echo("\nPresence:")
    for op, desc in [
        ("exists", "Field is present and non-empty"),
        ("not_exists", "Field is absent or empty"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nString:")
    for op, desc in [
        ("eq_str", "String equals value"),
        ("ne_str", "String does not equal value"),
        ("in_str", "String is in list of values"),
        ("not_in_str", "String is not in list of values"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nList Filtering:")
    for op, desc in [
        ("filter_count", "Count items matching field=value > threshold"),
        ("filter_multi", "Count items matching multiple filters > threshold"),
        ("computed_filter", "Evaluate expression on each item"),
    ]:
        click.echo(f"  {op:20s} {desc}")

    click.echo("\nDate/Time:")
    for op, desc in [
        ("age_gt", "Timestamp age > N days"),
        ("age_lt", "Timestamp age < N days"),
        ("age_gte", "Timestamp age >= N days"),
        ("age_lte", "Timestamp age <= N days"),
    ]:
        click.echo(f"  {op:20s} {desc}")


@platform_info.command("transforms")
def info_transforms() -> None:
    """List available pipe transforms for field paths."""
    from .normalization._transforms import _PARAM_TRANSFORMS, _TRANSFORMS

    click.echo("Simple Transforms (usage: path | transform_name):")
    for name, fn in sorted(_TRANSFORMS.items()):
        doc = (fn.__doc__ or "").strip().split("\n")[0] if fn.__doc__ else ""
        click.echo(f"  {name:20s} {doc}")

    click.echo("\nParameterized Transforms (usage: path | name(args)):")
    for name, fn in sorted(_PARAM_TRANSFORMS.items()):
        doc = (fn.__doc__ or "").strip().split("\n")[0] if fn.__doc__ else ""
        click.echo(f"  {name:20s} {doc}")


@platform_info.command("types")
def info_types() -> None:
    """List available field types and their default fallbacks."""
    from .models.report_schema import _TYPE_DEFAULT_FALLBACKS

    from .normalization._fields import _TYPE_COERCERS

    click.echo("Field Types:")
    for type_name in sorted({*_TYPE_DEFAULT_FALLBACKS.keys(), *_TYPE_COERCERS.keys()}):
        fallback = _TYPE_DEFAULT_FALLBACKS.get(type_name)
        click.echo(f"  {type_name:20s} default: {fallback!r}")


@platform_info.command("aliases")
def info_aliases() -> None:
    """List YAML shorthand aliases for config fields."""
    aliases = [
        ("from", "path", "Field data source path"),
        ("expr", "compute", "Computed expression"),
        ("run", "script", "Script to execute"),
        ("args", "script_args", "Script arguments"),
        ("timeout", "script_timeout", "Script timeout"),
        ("default", "fallback", "Default value when null"),
        ("title", "display_name", "Human-readable name"),
        ("title", "label", "Widget/column label"),
        ("rows", "rows_field", "Table data source"),
        ("any", "keys_any", "Detection: match any key"),
        ("all", "keys_all", "Detection: match all keys"),
    ]
    click.echo("YAML Aliases (shorthand → canonical):")
    for alias, canonical, desc in aliases:
        click.echo(f"  {alias:20s} → {canonical:20s} {desc}")


# Deprecated alias — keep `schema` working with a warning
@main.group("schema", hidden=True)
def schema() -> None:
    """Deprecated: use 'platform' instead."""
    click.echo("Warning: 'schema' command is deprecated, use 'platform' instead.", err=True)


schema.add_command(platform_list, "list")
schema.add_command(platform_validate, "validate")
schema.add_command(platform_init, "init")
schema.add_command(platform_run, "run")


# ---------------------------------------------------------------------------
# stig
# ---------------------------------------------------------------------------


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp")
@click.option("--config-dir", default=None, type=click.Path(exists=True, file_okay=False))
def stig(input_file: str, output_dir: str, report_stamp: str | None, config_dir: str | None) -> None:
    """Generate STIG compliance reports (per-host and fleet overview)."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)

    registry = _registry_from_config_dir(config_dir)
    cklb_output = output_path / "cklb"
    cklb_output.mkdir(parents=True, exist_ok=True)
    _generate_cklb_artifacts(
        hosts_data,
        cklb_output,
        registry=registry,
        config_dir=Path(config_dir) if config_dir else None,
    )

    render_stig(hosts_data, output_path, common_vars, cklb_dir=cklb_output)
    click.echo(f"Done! STIG reports generated in {output_dir}")


# ---------------------------------------------------------------------------
# cklb
# ---------------------------------------------------------------------------


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--skeleton-dir", type=click.Path(exists=True), help="Legacy: explicit skeleton directory override.")
@click.option("--config-dir", type=click.Path(exists=True, file_okay=False),
              help="Config directory containing platform configs and skeleton files.")
def cklb(input_file: str, output_dir: str, skeleton_dir: str | None, config_dir: str | None) -> None:
    """Generate CKLB artifacts for STIG results.

    Skeleton resolution order:
      1. --skeleton-dir (legacy explicit override, bare filename)
      2. --config-dir + path from stig_skeleton_map (e.g. cklb_skeletons/foo.cklb)
      3. Package builtins in src/ncs_reporter/cklb_skeletons/ (bare filename)
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)

    registry = _registry_from_config_dir(config_dir)

    _generate_cklb_artifacts(
        hosts_data,
        output_path,
        registry=registry,
        explicit_skeleton_dir=Path(skeleton_dir) if skeleton_dir else None,
        config_dir=Path(config_dir) if config_dir else None,
    )


# ---------------------------------------------------------------------------
# stig-apply
# ---------------------------------------------------------------------------


@main.command("stig-apply")
@click.argument("artifact", type=click.Path(exists=True, path_type=Path))
@click.option("--inventory", default="inventory/production/", show_default=True)
@click.option("--limit", required=True)
@click.option("--target-type", default="")
@click.option("--target-host", default="")
@click.option("--esxi-host", default="", help="Legacy alias for --target-host.")
@click.option("--skip-snapshot", is_flag=True)
@click.option("--post-audit", is_flag=True)
@click.option("--extra-vars", "-e", "extra_vars", multiple=True)
@click.option("--dry-run", is_flag=True)
def stig_apply(
    artifact: Path,
    inventory: str,
    limit: str,
    target_type: str,
    target_host: str,
    esxi_host: str,
    skip_snapshot: bool,
    post_audit: bool,
    extra_vars: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Apply STIG remediation interactively from a raw STIG YAML artifact."""
    from ._stig_apply import (
        SUPPORTED_TARGET_TYPES,
        detect_target_type,
        infer_target_host,
        load_stig_artifact,
        run_generic_interactive_apply,
        run_interactive_apply,
    )

    raw = load_stig_artifact(artifact)
    detected = detect_target_type(raw, artifact, override=target_type)
    if not detected:
        raise click.ClickException(
            "Could not determine target type. Provide --target-type (esxi/vm/vcsa/photon/ubuntu)."
        )
    normalized = detected.lower()
    if normalized not in SUPPORTED_TARGET_TYPES:
        raise click.ClickException(
            f"Unsupported target type '{normalized}'. Supported: {', '.join(sorted(SUPPORTED_TARGET_TYPES))}."
        )

    effective_host = target_host or esxi_host or infer_target_host(raw)
    if normalized == "esxi":
        if not effective_host:
            raise click.ClickException("ESXi apply requires --target-host.")
        run_interactive_apply(
            artifact=artifact, inventory=inventory, limit=limit, esxi_host=effective_host,
            skip_snapshot=skip_snapshot, post_audit=post_audit, extra_vars=extra_vars, dry_run=dry_run,
        )
    else:
        run_generic_interactive_apply(
            artifact=artifact, inventory=inventory, limit=limit, target_type=normalized,
            target_host=effective_host, extra_vars=extra_vars, dry_run=dry_run,
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_groups(groups_file: str | None) -> dict[str, Any]:
    if not groups_file:
        return {}
    with open(groups_file) as f:
        return json.load(f) if str(groups_file).endswith(".json") else yaml.safe_load(f)


if __name__ == "__main__":
    main()
