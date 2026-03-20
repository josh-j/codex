"""NCS Reporter CLI entry point."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from ._schema_utils import schema_from_bundle, schema_template
from .aggregation import hosts_unchanged, load_all_reports, normalize_host_bundle, write_output
from .cklb_export import generate_cklb
from .models.platforms_config import PlatformEntry
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


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
def linux(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Linux fleet and node reports."""
    _platform_command("linux", input_file, output_dir, report_stamp)


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
def vmware(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate VMware fleet and vCenter reports."""
    _platform_command("vmware", input_file, output_dir, report_stamp)


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
def windows(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Windows fleet and node reports."""
    _platform_command("windows", input_file, output_dir, report_stamp)


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

    click.echo("Rendering Global Site Health dashboard...")
    site_view = build_site_dashboard_view(data, inventory_groups=groups_data, **vm_kwargs(common_vars))
    env = get_jinja_env()
    content = env.get_template("site_health_report.html.j2").render(site_dashboard_view=site_view, **common_vars)
    (output_path / "site_health_report.html").write_text(content)
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
    effective_registry = registry or default_registry()
    builtin_skeleton_dir = Path(__file__).parent / "cklb_skeletons"

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
        platforms = load_platforms(_platforms_cfg, extra_schema_dirs=_extra_dirs)
        return PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])
    except Exception as exc:
        logger.warning("Could not build registry from config-dir '%s': %s", config_dir, exc)
        return None


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------


@main.command("all")
@click.option("--platform-root", required=True, type=click.Path(exists=True))
@click.option("--reports-root", required=True, type=click.Path())
@click.option("--groups", "groups_file", type=click.Path(exists=True))
@click.option("--report-stamp")
@click.option("--config-dir", default=None, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--extra-schema-dir", "-S", multiple=True, metavar="DIR")
@click.option("--platforms-config", "-P", default=None, type=click.Path(exists=True))
@click.option("--force", is_flag=True, default=False, help="Force re-render even if data is unchanged.")
def all_cmd(
    platform_root: str,
    reports_root: str,
    groups_file: str | None,
    report_stamp: str | None,
    config_dir: str | None,
    extra_schema_dir: tuple[str, ...],
    platforms_config: str | None,
    force: bool,
) -> None:
    """Run full aggregation and rendering for all platforms and the site dashboard."""
    p_root = Path(platform_root)
    r_root = Path(reports_root)
    r_root.mkdir(parents=True, exist_ok=True)

    config_yaml = load_config_yaml(config_dir)
    effective_stamp = report_stamp or (
        str(config_yaml["report_stamp"]) if config_yaml.get("report_stamp") is not None else None
    )
    effective_groups_file = groups_file or (
        resolve_path_from_config_root(config_dir, config_yaml["groups_file"].strip())
        if isinstance(config_yaml.get("groups_file"), str) and config_yaml["groups_file"].strip()
        else None
    )
    common_vars = generate_timestamps(effective_stamp)

    _extra_dirs, _platforms_cfg = resolve_config_dir(config_dir, extra_schema_dir, platforms_config, config_yaml)
    platforms = load_platforms(_platforms_cfg, extra_schema_dirs=_extra_dirs)

    # Augment with custom schema platforms not already in the config
    _configured_platforms = {p["platform"] for p in platforms}
    _custom_seen: set[str] = set()
    for _schema in discover_schemas(extra_dirs=_extra_dirs).values():
        if _schema.platform in _configured_platforms or _schema.platform in _custom_seen:
            continue
        if not (p_root / _schema.platform).is_dir():
            continue
        _custom_seen.add(_schema.platform)
        platforms.append({
            "input_dir": _schema.platform,
            "report_dir": _schema.platform,
            "platform": _schema.platform,
            "state_file": f"{_schema.platform}_fleet_state.yaml",
            "render": True,
            "schema_name": _schema.name,
            "target_types": [],
            "paths": default_paths(),
        })

    # --- Step 1: Platform aggregation (sequential I/O) ---
    render_tasks: list[dict[str, Any]] = []
    global_inventory_index: dict[str, str] = {}
    platforms_by_report_dir: dict[str, dict[str, Any]] = {str(p["report_dir"]): p for p in platforms}
    runtime_registry = PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])

    for p in platforms:
        p_dir = p_root / p["input_dir"]
        if not p_dir.is_dir():
            continue
        click.echo(f"--- Processing Platform: {p['input_dir']} ---")
        p_data = load_all_reports(str(p_dir), host_normalizer=normalize_host_bundle)
        if not p_data or not p_data["hosts"]:
            click.echo(f"No data for {p['input_dir']}, skipping.")
            continue
        for hostname in p_data["hosts"]:
            global_inventory_index[hostname] = p["report_dir"]
        state_path = str(p_dir / p["state_file"])
        if not force and hosts_unchanged(p_data, state_path):
            click.echo(f"  {p['input_dir']} unchanged, skipping.")
            continue
        write_output(p_data, state_path)
        if p.get("render", True):
            output_dir = r_root / "platform" / p["report_dir"]
            output_dir.mkdir(parents=True, exist_ok=True)
            task: dict[str, Any] = {
                "platform": p["platform"],
                "hosts_data": p_data["hosts"],
                "output_path": output_dir,
                "report_dir": p["report_dir"],
                "platform_paths": p["paths"],
                "extra_schema_dirs": _extra_dirs,
            }
            if p.get("schema_name") is not None:
                task["schema_names_override"] = [p["schema_name"]]
            render_tasks.append(task)

    generated_fleet_dirs = {str(t["report_dir"]) for t in render_tasks}

    # --- Step 1b: Global aggregation (needed by STIG build pass + site dashboard) ---
    click.echo("--- Aggregating Global State ---")
    all_hosts_state = p_root / "all_hosts_state.yaml"
    global_data = load_all_reports(str(p_root), host_normalizer=normalize_host_bundle)
    if not global_data:
        click.echo("No global data found; skipping site dashboard and STIG rendering.")
        return

    global_changed = force or not hosts_unchanged(global_data, str(all_hosts_state))
    if global_changed:
        write_output(global_data, str(all_hosts_state))
    else:
        click.echo("  Global state unchanged.")
    global_hosts = global_data.get("hosts", global_data)

    # --- Step 1c: Build STIG host views (skeleton fallback; CKLB not yet generated) ---
    # These are embedded into node reports during step 2 so operators see compliance
    # status inline without navigating to a separate STIG report.
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

    # --- Step 2: Parallel platform rendering ---
    if render_tasks:
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
                    extra_schema_dirs=t.get("extra_schema_dirs", ()),
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

    # --- Step 3: Site dashboard ---
    if not global_changed:
        click.echo("--- Skipping Global Site Dashboard (unchanged) ---")
    else:
        click.echo("--- Processing Global Site Dashboard ---")
        groups_data = _load_groups(effective_groups_file)
        site_view = build_site_dashboard_view(global_data, inventory_groups=groups_data, **vm_kwargs(common_vars))
        env = get_jinja_env()
        content = env.get_template("site_health_report.html.j2").render(site_dashboard_view=site_view, **common_vars)
        (r_root / "site_health_report.html").write_text(content)
        click.echo(f"Global dashboard generated at {r_root}/site_health_report.html")

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

    # --- Step 4: CKLB export ---
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

    # --- Step 5: STIG fleet rendering (full CKLB-hydrated dedicated STIG reports) ---
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
        click.echo(f"ERROR: no schema found for platform '{platform}'", err=True)
        raise SystemExit(1)

    view = build_generic_node_view(schema, hostname, bundle, **kw)
    content = get_jinja_env().get_template("generic_node_report.html.j2").render(
        generic_node_view=view, **common_vars
    )
    dest = output_path / f"{hostname}_health_report.html"
    dest.write_text(content)
    click.echo(f"Success: Report generated at {dest}")


# ---------------------------------------------------------------------------
# schema command group
# ---------------------------------------------------------------------------


@main.group()
def schema() -> None:
    """Inspect and validate YAML report schemas."""


@schema.command("list")
@click.option("--extra-schema-dir", "-S", multiple=True, metavar="DIR")
def schema_list(extra_schema_dir: tuple[str, ...]) -> None:
    """List all discovered schemas and their source paths."""
    schemas = discover_schemas(extra_dirs=tuple(extra_schema_dir))
    if not schemas:
        click.echo("No schemas found.")
        return
    for name, s in sorted(schemas.items()):
        source = getattr(s, "_source_path", "unknown")
        example_status = "example OK" if load_example_bundle(s) else "no example file"
        click.echo(f"  {name:20s}  platform={s.platform:10s}  {example_status:14s}  {source}")


@schema.command("validate")
@click.argument("schema_file", type=click.Path(exists=True, path_type=Path))
def schema_validate(schema_file: Path) -> None:
    """Validate a schema file with comprehensive checks."""
    try:
        s = load_schema_from_file(schema_file)
    except ValueError as exc:
        click.echo(f"INVALID: {exc}", err=True)
        raise SystemExit(1)

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
    declared = set(s.fields.keys())
    for rule in s.alerts:
        for match in re.finditer(r"\{(\w+)", rule.message):
            ref = match.group(1)
            if ref != "value" and not ref.startswith("_") and ref not in declared:
                errors.append(f"alert '{rule.id}': message references undeclared field '{ref}'")

    # Script file existence
    from .normalization.schema_driven import _BUILTIN_SCRIPTS_DIR
    for name, spec in s.fields.items():
        if spec.script is None:
            continue
        p = Path(spec.script)
        if not any([
            p.is_absolute() and p.exists(),
            (schema_file.parent / spec.script).exists(),
            p.exists(),
            (_BUILTIN_SCRIPTS_DIR / spec.script).exists(),
        ]):
            errors.append(f"field '{name}': script '{spec.script}' not found")

    # Path validation against example bundle
    example = load_example_bundle(s)
    if example is not None:
        for msg in validate_schema_paths(s, example).values():
            errors.append(msg)

    click.echo(f"Schema '{s.name}' — {len(s.fields)} fields, {len(s.alerts)} alerts, {len(s.widgets)} widgets")
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


@schema.command("init")
@click.option("--name", required=True)
@click.option("--from-bundle", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def schema_init(name: str, from_bundle: Path | None, output: Path | None) -> None:
    """Generate a starter schema YAML template."""
    content = schema_from_bundle(name, from_bundle) if from_bundle else schema_template(name)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        click.echo(f"Schema written to {output}")
    else:
        click.echo(content)


@schema.command("run")
@click.argument("schema_file", type=click.Path(exists=True, path_type=Path))
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--hostname", "-n", default="host", show_default=True)
@click.option("--report-stamp")
@click.option("--site-report", "site_report_href", default=None)
def schema_run(
    schema_file: Path,
    input_file: str,
    output_dir: str,
    hostname: str,
    report_stamp: str | None,
    site_report_href: str | None,
) -> None:
    """Run a single schema-driven report against a raw YAML bundle."""
    try:
        s = load_schema_from_file(schema_file)
    except ValueError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise SystemExit(1)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        bundle = yaml.safe_load(f) or {}

    common_vars = generate_timestamps(report_stamp)
    kw = vm_kwargs(common_vars)
    env = get_jinja_env()
    fleet_filename = f"{s.name}_fleet_report.html"
    node_nav: dict[str, str] = {"fleet_report": f"../{fleet_filename}", "fleet_label": f"{s.display_name} Fleet"}
    fleet_nav: dict[str, str] = {}
    if site_report_href:
        fleet_nav["site_report"] = site_report_href
        node_nav["site_report"] = f"../{site_report_href}"

    node_view = build_generic_node_view(s, hostname, bundle, nav=node_nav, **kw)
    host_dir = output_path / hostname
    host_dir.mkdir(exist_ok=True)
    content = env.get_template("generic_node_report.html.j2").render(generic_node_view=node_view, **common_vars)
    write_report(host_dir, "health_report.html", content, common_vars["report_stamp"])
    click.echo(f"Node report: {host_dir}/health_report.html")

    fleet_view = build_generic_fleet_view(s, {hostname: bundle}, nav=fleet_nav, **kw)
    content = env.get_template("generic_fleet_report.html.j2").render(generic_fleet_view=fleet_view, **common_vars)
    write_report(output_path, fleet_filename, content, common_vars["report_stamp"])
    click.echo(f"Fleet report: {output_path}/{fleet_filename}")
    click.echo("Done!")


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
              help="Config directory containing platform schemas and skeleton files.")
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
@click.option("--inventory", default="inventory/production/hosts.yaml", show_default=True)
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
