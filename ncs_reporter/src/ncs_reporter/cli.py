import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import click
import pydantic
import yaml

from ._report_context import (
    generate_timestamps,
    get_jinja_env,
    load_hosts_data,
    load_yaml,
    vm_kwargs,
    write_report,
)
from .aggregation import load_all_reports, normalize_host_bundle, write_output
from .cklb_export import generate_cklb
from .models.platforms_config import DEFAULT_PATH_TEMPLATES, PlatformEntry, PlatformsConfig
from .platform_registry import PlatformRegistry, default_registry
from .pathing import rel_href, render_template
from .schema_loader import discover_schemas, load_example_bundle, load_schema_from_file, validate_schema_paths
from .view_models.generic import build_generic_fleet_view, build_generic_node_view
from .view_models.site import build_site_dashboard_view
from .view_models.stig import build_stig_fleet_view, build_stig_host_view

logger = logging.getLogger("ncs_reporter")


# ---------------------------------------------------------------------------
# Schema-driven platform renderer
# ---------------------------------------------------------------------------

_USER_PLATFORMS_CONFIG = Path.home() / ".config" / "ncs_reporter" / "platforms.yaml"


def _default_paths() -> dict[str, str]:
    return dict(DEFAULT_PATH_TEMPLATES)


def _builtin_platforms() -> list[dict[str, Any]]:
    return [e.model_dump() for e in default_registry().entries]


def _resolve_path_from_config_root(config_dir: str | None, value: str) -> str:
    p = Path(value)
    if p.is_absolute() or not config_dir:
        return str(p)
    return str(Path(config_dir) / p)


def _load_config_yaml(config_dir: str | None) -> dict[str, Any]:
    """Load optional config.yaml from config_dir."""
    if not config_dir:
        return {}
    cfg_path = Path(config_dir) / "config.yaml"
    if not cfg_path.is_file():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise click.ClickException(f"Invalid config file: {cfg_path} (expected YAML mapping)")
    return raw


def _unique_preserve_order(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return tuple(out)


def _resolve_config_dir(
    config_dir: str | None,
    extra_schema_dir: tuple[str, ...],
    platforms_config: str | None,
    config_yaml: dict[str, Any],
) -> tuple[tuple[str, ...], str | None]:
    """Resolve schema dirs + platforms config from a single config directory.

    Supported layouts:
      1. <config_dir>/platforms.yaml + <config_dir>/*.yaml schemas
      2. <config_dir>/schemas/platforms.yaml + <config_dir>/schemas/*.yaml schemas
    """
    resolved_schema_dirs = list(extra_schema_dir)
    resolved_platforms = platforms_config

    if not config_dir:
        return _unique_preserve_order(resolved_schema_dirs), resolved_platforms

    root = Path(config_dir)

    cfg_extra = config_yaml.get("extra_schema_dirs")
    if isinstance(cfg_extra, list):
        for entry in cfg_extra:
            if isinstance(entry, str) and entry.strip():
                resolved_schema_dirs.append(_resolve_path_from_config_root(config_dir, entry.strip()))

    if resolved_platforms is None:
        cfg_platforms = config_yaml.get("platforms_config")
        if isinstance(cfg_platforms, str) and cfg_platforms.strip():
            resolved_platforms = _resolve_path_from_config_root(config_dir, cfg_platforms.strip())

    # Support both root-level schemas and nested schemas/ layout.
    schema_candidates = [root / "schemas", root]
    for cand in schema_candidates:
        if cand.is_dir():
            resolved_schema_dirs.append(str(cand))

    if resolved_platforms is None:
        platform_candidates = [root / "platforms.yaml", root / "schemas" / "platforms.yaml"]
        for cand in platform_candidates:
            if cand.is_file():
                resolved_platforms = str(cand)
                break

    return _unique_preserve_order(resolved_schema_dirs), resolved_platforms


def _format_validation_error(path: Path, exc: pydantic.ValidationError) -> str:
    lines = [f"Invalid platforms config {path}:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def _load_platforms(
    explicit_path: str | None,
    extra_schema_dirs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Locate and load a platforms config YAML.

    Falls back to schema-embedded platform metadata, then built-in defaults.
    """
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates += [Path("platforms.yaml"), _USER_PLATFORMS_CONFIG]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
            config = PlatformsConfig.model_validate(raw)
            logger.info("Loaded platforms config from %s", path)
            return [p.model_dump() for p in config.platforms]
        except pydantic.ValidationError as exc:
            msg = _format_validation_error(path, exc)
            if explicit_path and path == Path(explicit_path):
                raise click.ClickException(msg) from exc
            logger.warning(msg)
        except Exception as exc:
            if explicit_path and path == Path(explicit_path):
                raise click.ClickException(f"Invalid platforms config {path}: {exc}") from exc
            logger.warning("Failed to load platforms config %s: %s", path, exc)

    # Fall back to schema-embedded platform metadata
    from .schema_loader import build_platform_entries_from_schemas

    schemas = discover_schemas(extra_dirs=extra_schema_dirs)
    schema_entries = build_platform_entries_from_schemas(schemas)
    if schema_entries:
        entries = [PlatformEntry.model_validate(e) for e in schema_entries]
        return [e.model_dump() for e in entries]

    return _builtin_platforms()


def _render_platform(
    platform: str,
    hosts_data: dict[str, Any],
    output_path: Path,
    common_vars: dict[str, str],
    *,
    global_inventory_index: dict[str, str] | None = None,
    generated_fleet_dirs: set[str] | None = None,
    report_dir: str | None = None,
    platform_paths: dict[str, str] | None = None,
    extra_schema_dirs: tuple[str, ...] = (),
    schema_names_override: list[str] | None = None,
    has_site_report: bool = False,
    has_stig_fleet: bool = False,
) -> None:
    """Render node + fleet reports for a platform using the schema engine.

    Paths and filenames are resolved from the platform path templates.
    """
    schema_names = (
        schema_names_override if schema_names_override is not None else default_registry().schema_names_for_platform(platform)
    )
    all_schemas = discover_schemas(extra_dirs=extra_schema_dirs)

    schema = None
    for name in schema_names:
        schema = all_schemas.get(name)
        if schema:
            break

    if schema is None:
        logger.warning("No schema found for platform '%s' (tried: %s)", platform, schema_names)
        return

    env = get_jinja_env()
    stamp = common_vars["report_stamp"]
    kw = vm_kwargs(common_vars)
    node_tpl = env.get_template("generic_node_report.html.j2")
    if not report_dir:
        logger.warning("Missing report_dir for platform '%s'", platform)
        return
    if not platform_paths:
        logger.warning("Missing path templates for platform '%s'", platform)
        return
    schema_name_for_file = schema.name
    fleet_report_abs = render_template(
        platform_paths["report_fleet"],
        report_dir=report_dir,
        schema_name=schema_name_for_file,
        hostname="",
        target_type="",
        report_stamp=stamp,
    )
    fleet_filename = Path(fleet_report_abs).name
    site_report_abs = render_template(
        platform_paths["report_site"],
        report_dir=report_dir,
        schema_name=schema_name_for_file,
        hostname="",
        target_type="",
        report_stamp=stamp,
    )

    # Nav for node reports: back to fleet, and optionally site (one dir deeper than fleet)
    node_nav: dict[str, str] = {"fleet_label": f"{schema.display_name} Fleet"}

    # Nav for fleet report: optionally back to site
    fleet_nav: dict[str, str] = {}

    import re

    for hostname, bundle in hosts_data.items():
        host_dir = output_path / hostname
        host_dir.mkdir(exist_ok=True)
        node_rel_dir = f"platform/{report_dir}/{hostname}"
        node_nav["fleet_report"] = rel_href(node_rel_dir, fleet_report_abs)
        if has_site_report:
            node_nav["site_report"] = rel_href(node_rel_dir, site_report_abs)
        
        # Build history list
        history = []
        for f in host_dir.glob("health_report_*.html"):
            m = re.search(r"health_report_(\d+)\.html", f.name)
            if m:
                date_str = m.group(1)
                display_name = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}" if len(date_str) == 8 else date_str
                history.append({"name": display_name, "url": f.name})
        history.sort(key=lambda x: x["name"], reverse=True)

        node_view = build_generic_node_view(
            schema,
            hostname,
            bundle,
            nav=node_nav,
            hosts_data=global_inventory_index,
            generated_fleet_dirs=generated_fleet_dirs,
            has_stig_fleet=has_stig_fleet,
            history=history,
            **kw,
        )
        content = node_tpl.render(generic_node_view=node_view, **common_vars)
        write_report(host_dir, "health_report.html", content, stamp)

    if has_site_report:
        fleet_nav["site_report"] = rel_href(f"platform/{report_dir}", site_report_abs)
    fleet_view = build_generic_fleet_view(
        schema,
        hosts_data,
        nav=fleet_nav,
        hosts_data=global_inventory_index,
        generated_fleet_dirs=generated_fleet_dirs,
        has_stig_fleet=has_stig_fleet,
        **kw,
    )
    fleet_tpl = env.get_template("generic_fleet_report.html.j2")
    content = fleet_tpl.render(generic_fleet_view=fleet_view, **common_vars)
    write_report(output_path, fleet_filename, content, stamp)


# ---------------------------------------------------------------------------
# STIG renderer (shared between `stig` and `all` commands)
# ---------------------------------------------------------------------------


def _render_stig(
    hosts_data: dict[str, Any],
    output_path: Path,
    common_vars: dict[str, str],
    global_inventory_index: dict[str, str] | None = None,
    cklb_dir: Path | None = None,
    generated_fleet_dirs: set[str] | None = None,
    registry: PlatformRegistry | None = None,
    has_site_report: bool = False,
) -> None:
    """Render per-host STIG reports and fleet overview."""
    reg = registry or default_registry()
    env = get_jinja_env()
    stamp = common_vars["report_stamp"]
    kw = vm_kwargs(common_vars)
    host_tpl = env.get_template("stig_host_report.html.j2")
    all_hosts_data: dict[str, Any] = {}
    cklb_rule_cache: dict[str, dict[str, dict[str, Any]]] = {}

    def _load_cklb_rule_lookup(cklb_path: Path) -> dict[str, dict[str, Any]]:
        cached = cklb_rule_cache.get(str(cklb_path))
        if cached is not None:
            return cached
        if not cklb_path.is_file():
            cklb_rule_cache[str(cklb_path)] = {}
            return {}

        try:
            payload = json.loads(cklb_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse CKLB %s: %s", cklb_path, exc)
            cklb_rule_cache[str(cklb_path)] = {}
            return {}

        out: dict[str, dict[str, Any]] = {}
        for stig in payload.get("stigs", []) if isinstance(payload, dict) else []:
            if not isinstance(stig, dict):
                continue
            for rule in stig.get("rules", []) if isinstance(stig.get("rules"), list) else []:
                if not isinstance(rule, dict):
                    continue
                for key in ("rule_id", "rule_version", "group_id"):
                    val = str(rule.get(key) or "").strip()
                    if val and val not in out:
                        out[val] = rule
        cklb_rule_cache[str(cklb_path)] = out
        return out

    import re

    # First pass: collect all STIG entries and build navigation indices
    stig_entries: list[dict[str, Any]] = []
    # All STIG reports indexed by hostname → list of {target_type, host_report_abs, host_rel_dir}
    all_stig_reports: dict[str, list[dict[str, str]]] = {}

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            target_type = str(payload.get("target_type", "")).strip().lower()
            entry = reg.entry_for_target_type(target_type)
            if entry is None:
                linux_entries = reg.by_platform("linux")
                entry = linux_entries[0] if linux_entries else None
            if entry is None:
                logger.warning("No STIG platform mapping available for target_type '%s'", target_type)
                continue

            report_dir = entry.report_dir
            path_templates = entry.paths.model_dump()
            host_report_abs = render_template(
                path_templates["report_stig_host"],
                report_dir=report_dir,
                schema_name="",
                hostname=hostname,
                target_type=target_type,
                report_stamp=stamp,
            )
            host_rel_dir = str(Path(host_report_abs).parent).replace("\\", "/")

            stig_entries.append({
                "hostname": hostname,
                "bundle": bundle,
                "audit_type": audit_type,
                "payload": payload,
                "target_type": target_type,
                "entry": entry,
                "report_dir": report_dir,
                "path_templates": path_templates,
                "host_report_abs": host_report_abs,
                "host_rel_dir": host_rel_dir,
            })

            all_stig_reports.setdefault(hostname, []).append({
                "target_type": target_type,
                "host_report_abs": host_report_abs,
                "host_rel_dir": host_rel_dir,
            })

    # Second pass: render each STIG host report
    for se in stig_entries:
        hostname = se["hostname"]
        bundle = se["bundle"]
        audit_type = se["audit_type"]
        payload = se["payload"]
        target_type = se["target_type"]
        entry = se["entry"]
        report_dir = se["report_dir"]
        path_templates = se["path_templates"]
        host_report_abs = se["host_report_abs"]
        host_rel_dir = se["host_rel_dir"]

        site_report_abs = render_template(
            path_templates["report_site"],
            report_dir=report_dir,
            schema_name="",
            hostname=hostname,
            target_type=target_type,
            report_stamp=stamp,
        )
        stig_fleet_abs = render_template(
            path_templates["report_stig_fleet"],
            report_dir=report_dir,
            schema_name="",
            hostname=hostname,
            target_type=target_type,
            report_stamp=stamp,
        )
        host_nav: dict[str, str] = {
            "fleet_report": rel_href(host_rel_dir, stig_fleet_abs),
            "fleet_label": "STIG Fleet Dashboard",
        }
        if has_site_report:
            host_nav["site_report"] = rel_href(host_rel_dir, site_report_abs)
        cklb_lookup: dict[str, dict[str, Any]] = {}
        if cklb_dir is not None and target_type:
            cklb_path = cklb_dir / f"{hostname}_{target_type}.cklb"
            cklb_lookup = _load_cklb_rule_lookup(cklb_path)

        if not cklb_lookup and target_type:
            skeleton_file = reg.stig_skeleton_for_target(target_type)
            if skeleton_file:
                sk_path = Path(__file__).parent / "cklb_skeletons" / skeleton_file
                cklb_lookup = _load_cklb_rule_lookup(sk_path)

        host_dir = output_path / host_rel_dir
        host_dir.mkdir(parents=True, exist_ok=True)

        # Build history list for stig
        history = []
        file_prefix = Path(host_report_abs).stem
        for f in host_dir.glob(f"{file_prefix}_*.html"):
            m = re.search(f"{file_prefix}_(\\d+)\\.html", f.name)
            if m:
                date_str = m.group(1)
                display_name = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}" if len(date_str) == 8 else date_str
                history.append({"name": display_name, "url": f.name})
        history.sort(key=lambda x: x["name"], reverse=True)

        # Build peer host links — all STIG hosts (prefer same target_type, else first)
        stig_host_peers = []
        seen_peer_hosts: set[str] = set()
        for peer_host, peer_reports in sorted(all_stig_reports.items()):
            if peer_host in seen_peer_hosts:
                continue
            seen_peer_hosts.add(peer_host)
            # Prefer linking to the same target_type if this peer has it
            pr = next((r for r in peer_reports if r["target_type"] == target_type), peer_reports[0])
            peer_abs = pr["host_rel_dir"] + "/" + Path(pr["host_report_abs"]).name
            stig_host_peers.append({
                "name": peer_host,
                "report": rel_href(host_rel_dir, peer_abs),
            })

        # Build sibling links with proper relative paths (other STIG types for same host)
        stig_siblings = []
        for sr in all_stig_reports.get(hostname, []):
            if sr["target_type"] == target_type:
                continue
            sibling_abs = sr["host_rel_dir"] + "/" + Path(sr["host_report_abs"]).name
            stig_siblings.append({
                "name": f"{sr['target_type'].upper()} STIG",
                "report": rel_href(host_rel_dir, sibling_abs),
            })
        stig_siblings.sort(key=lambda x: x["name"])

        host_view = build_stig_host_view(
            hostname,
            audit_type,
            payload,
            nav=host_nav,
            host_bundle=bundle,
            hosts_data=global_inventory_index,
            cklb_rule_lookup=cklb_lookup,
            generated_fleet_dirs=generated_fleet_dirs,
            history=history,
            stig_host_peers=stig_host_peers,
            stig_siblings=stig_siblings,
            **kw,
        )

        content = host_tpl.render(stig_host_view=host_view, **common_vars)
        dest_name = Path(host_report_abs).name
        with open(host_dir / dest_name, "w") as f:
            f.write(content)
        if stamp:
            stem = Path(dest_name).stem
            suffix = Path(dest_name).suffix or ".html"
            with open(host_dir / f"{stem}_{stamp}{suffix}", "w") as f:
                f.write(content)

        all_hosts_data.setdefault(hostname, {})[audit_type] = payload

    if all_hosts_data:
        first_entry = reg.entries[0] if reg.entries else None
        fleet_paths = first_entry.paths.model_dump() if first_entry else _default_paths()
        site_report_abs = render_template(
            fleet_paths["report_site"],
            report_dir="",
            schema_name="",
            hostname="",
            target_type="",
            report_stamp=stamp,
        )
        stig_fleet_abs = render_template(
            fleet_paths["report_stig_fleet"],
            report_dir="",
            schema_name="",
            hostname="",
            target_type="",
            report_stamp=stamp,
        )
        stig_fleet_nav: dict[str, str] = {}
        if has_site_report:
            stig_fleet_nav["site_report"] = rel_href(".", site_report_abs)
        fleet_view = build_stig_fleet_view(
            all_hosts_data,
            nav=stig_fleet_nav,
            generated_fleet_dirs=generated_fleet_dirs,
            **kw,
        )
        fleet_tpl = env.get_template("stig_fleet_report.html.j2")
        content = fleet_tpl.render(stig_fleet_view=fleet_view, **common_vars)
        write_report(output_path, Path(stig_fleet_abs).name, content, stamp)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug-level logging.")
def main(verbose: bool) -> None:
    """NCS Reporter: Standalone reporting CLI for Codex."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )


# ---------------------------------------------------------------------------
# validate-config command
# ---------------------------------------------------------------------------


@main.command("validate-config")
@click.option(
    "--platforms-config",
    "-P",
    type=click.Path(exists=True),
    default=None,
    help="Path to platforms.yaml config. Defaults: ./platforms.yaml, ~/.config/ncs_reporter/platforms.yaml, built-in.",
)
def validate_config(platforms_config: str | None) -> None:
    """Validate a platforms config file."""
    try:
        entries = _load_platforms(platforms_config)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    # Also run path contract validation
    from ncs_path_contract import validate_platforms_config_dict

    try:
        validate_platforms_config_dict({"platforms": entries})
    except ValueError as exc:
        raise click.ClickException(f"Path contract error: {exc}") from exc

    target_types = sorted({t for e in entries for t in e.get("target_types", [])})
    renderable = [e["platform"] for e in entries if e.get("render", True)]
    seen: set[str] = set()
    unique_renderable = [p for p in renderable if p not in seen and not seen.add(p)]  # type: ignore[func-returns-value]
    click.echo(f"Valid! {len(entries)} platform entries, {len(target_types)} target types.")
    click.echo(f"  Target types: {', '.join(target_types)}")
    click.echo(f"  Renderable platforms: {', '.join(unique_renderable)}")


# ---------------------------------------------------------------------------
# Platform commands (linux, vmware, windows)
# ---------------------------------------------------------------------------


def _platform_command(platform: str, input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Shared implementation for single-platform report commands."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)
    report_dir = default_registry().platform_to_report_dir(platform) or platform
    _render_platform(
        platform,
        hosts_data,
        output_path,
        common_vars,
        report_dir=report_dir,
        platform_paths=_default_paths(),
    )
    click.echo(f"Done! Reports generated in {output_dir}")


@main.command()
@click.option(
    "--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state."
)
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def linux(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Linux fleet and node reports."""
    _platform_command("linux", input_file, output_dir, report_stamp)


@main.command()
@click.option(
    "--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state."
)
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def vmware(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate VMware fleet and vCenter reports."""
    _platform_command("vmware", input_file, output_dir, report_stamp)


@main.command()
@click.option(
    "--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state."
)
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def windows(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Windows fleet and node reports."""
    _platform_command("windows", input_file, output_dir, report_stamp)


# ---------------------------------------------------------------------------
# site command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--input",
    "-i",
    "input_file",
    required=True,
    type=click.Path(exists=True),
    help="Path to global aggregated YAML state.",
)
@click.option("--groups", "-g", "groups_file", type=click.Path(exists=True), help="Path to inventory groups JSON/YAML.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def site(input_file: str, groups_file: str | None, output_dir: str, report_stamp: str | None) -> None:
    """Generate Global Site Health dashboard."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    data = load_yaml(input_file)
    common_vars = generate_timestamps(report_stamp)

    groups_data: dict[str, Any] = {}
    if groups_file:
        with open(groups_file) as f:
            if groups_file.endswith(".json"):
                groups_data = json.load(f)
            else:
                groups_data = yaml.safe_load(f)

    click.echo("Rendering Global Site Health dashboard...")
    site_view = build_site_dashboard_view(data, inventory_groups=groups_data, **vm_kwargs(common_vars))

    env = get_jinja_env()
    tpl = env.get_template("site_health_report.html.j2")
    content = tpl.render(site_dashboard_view=site_view, **common_vars)

    with open(output_path / "site_health_report.html", "w") as f:
        f.write(content)

    click.echo(f"Done! Global dashboard generated in {output_dir}")


# ---------------------------------------------------------------------------
# collect command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--report-dir", required=True, type=click.Path(exists=True), help="Directory containing host YAML reports."
)
@click.option("--output", required=True, type=click.Path(), help="Path to write aggregated YAML.")
@click.option("--filter", "audit_filter", help="Optional audit type filter.")
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
# all command
# ---------------------------------------------------------------------------


@main.command("all")
@click.option("--platform-root", required=True, type=click.Path(exists=True), help="Root directory for platforms.")
@click.option("--reports-root", required=True, type=click.Path(), help="Root directory for generated HTML reports.")
@click.option("--groups", "groups_file", type=click.Path(exists=True), help="Path to inventory groups JSON/YAML.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
@click.option(
    "--config-dir",
    default=None,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Single config directory containing schemas and platforms.yaml.",
)
@click.option(
    "--extra-schema-dir", "-S", multiple=True, metavar="DIR", help="Additional schema directory to search (repeatable)."
)
@click.option(
    "--platforms-config",
    "-P",
    default=None,
    type=click.Path(exists=True),
    help="Path to platforms.yaml config. Defaults: ./platforms.yaml, ~/.config/ncs_reporter/platforms.yaml, built-in.",
)
def all_cmd(
    platform_root: str,
    reports_root: str,
    groups_file: str | None,
    report_stamp: str | None,
    config_dir: str | None,
    extra_schema_dir: tuple[str, ...],
    platforms_config: str | None,
) -> None:
    """Run full aggregation and rendering for all platforms and the site dashboard."""
    p_root = Path(platform_root)
    r_root = Path(reports_root)
    r_root.mkdir(parents=True, exist_ok=True)
    config_yaml = _load_config_yaml(config_dir)
    effective_stamp = report_stamp or (
        str(config_yaml.get("report_stamp")) if config_yaml.get("report_stamp") is not None else None
    )
    effective_groups_file = groups_file
    if effective_groups_file is None:
        cfg_groups = config_yaml.get("groups_file")
        if isinstance(cfg_groups, str) and cfg_groups.strip():
            effective_groups_file = _resolve_path_from_config_root(config_dir, cfg_groups.strip())
    common_vars = generate_timestamps(effective_stamp)

    _extra_dirs, _platforms_cfg = _resolve_config_dir(config_dir, extra_schema_dir, platforms_config, config_yaml)
    platforms = _load_platforms(_platforms_cfg, extra_schema_dirs=_extra_dirs)

    # Append custom schemas (platforms not already in the loaded config)
    _configured_platforms = {p["platform"] for p in platforms}
    _custom_platforms_seen: set[str] = set()
    for _schema in discover_schemas(extra_dirs=_extra_dirs).values():
        if _schema.platform in _configured_platforms or _schema.platform in _custom_platforms_seen:
            continue
        _custom_dir = p_root / _schema.platform
        if not _custom_dir.is_dir():
            logger.debug("Custom schema '%s' (platform=%s): no data dir, skipping", _schema.name, _schema.platform)
            continue
        _custom_platforms_seen.add(_schema.platform)
        platforms.append(
            {
                "input_dir": _schema.platform,
                "report_dir": _schema.platform,
                "platform": _schema.platform,
                "state_file": f"{_schema.platform}_fleet_state.yaml",
                "render": True,
                "schema_name": _schema.name,
                "target_types": [],
                "paths": _default_paths(),
            }
        )

    # 1. Platform Aggregation (sequential — I/O bound directory walk)
    render_tasks: list[dict[str, Any]] = []
    global_inventory_index: dict[str, str] = {}
    platforms_by_report_dir: dict[str, dict[str, Any]] = {str(p["report_dir"]): p for p in platforms}
    _runtime_entries = [PlatformEntry.model_validate(p) for p in platforms]
    runtime_registry = PlatformRegistry(_runtime_entries)

    for p in platforms:
        p_dir = p_root / p["input_dir"]
        if not p_dir.is_dir():
            continue

        state_path = p_dir / p["state_file"]
        click.echo(f"--- Processing Platform: {p['input_dir']} ---")

        p_data = load_all_reports(str(p_dir), host_normalizer=normalize_host_bundle)
        if not p_data or not p_data["hosts"]:
            click.echo(f"No data for {p['input_dir']}, skipping.")
            continue

        # Build global index for cross-platform linking
        for hostname in p_data["hosts"].keys():
            global_inventory_index[hostname] = p["report_dir"]

        write_output(p_data, str(state_path))

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

    # 2. Parallel platform rendering
    generated_fleet_dirs = {str(t["report_dir"]) for t in render_tasks}
    if render_tasks:
        with ThreadPoolExecutor(max_workers=min(len(render_tasks), 3)) as pool:
            futures = {
                pool.submit(
                    _render_platform,
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

    # 3. Global Site Aggregation & Rendering
    click.echo("--- Processing Global Site Dashboard ---")
    all_hosts_state = p_root / "all_hosts_state.yaml"
    global_data = load_all_reports(str(p_root), host_normalizer=normalize_host_bundle)
    if global_data:
        write_output(global_data, str(all_hosts_state))

        groups_data: dict[str, Any] = {}
        if effective_groups_file:
            with open(effective_groups_file) as f:
                groups_data = json.load(f) if str(effective_groups_file).endswith(".json") else yaml.safe_load(f)

        site_view = build_site_dashboard_view(global_data, inventory_groups=groups_data, **vm_kwargs(common_vars))
        env = get_jinja_env()
        tpl = env.get_template("site_health_report.html.j2")
        content = tpl.render(site_dashboard_view=site_view, **common_vars)
        with open(r_root / "site_health_report.html", "w") as f:
            f.write(content)

        click.echo(f"Global dashboard generated at {r_root}/site_health_report.html")

        # Generate search index
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
            search_index.append(
                {
                    "h": hostname,
                    "u": search_url,
                    "p": rep_dir.split("/")[0] if "/" in rep_dir else rep_dir,
                }
            )

        with open(r_root / "search_index.js", "w", encoding="utf-8") as f:
            f.write("window.NCS_SEARCH_INDEX = " + json.dumps(search_index, separators=(",", ":")) + ";")
        click.echo(f"Global search index generated at {r_root}/search_index.js")

        # 4. CKLB Export
        click.echo("--- Generating CKLB Artifacts ---")
        ctx = click.get_current_context()
        ctx.invoke(cklb, input_file=str(all_hosts_state), output_dir=str(r_root / "cklb"))

        # 5. STIG Fleet Rendering
        click.echo("--- Processing STIG Fleet Reports ---")
        _render_stig(
            global_data.get("hosts", global_data),
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
# node command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--platform", "-p", required=True, type=click.Choice(default_registry().all_platform_names()), help="Target platform type."
)
@click.option(
    "--input",
    "-i",
    "input_file",
    required=True,
    type=click.Path(exists=True),
    help="Path to raw audit/discovery YAML file.",
)
@click.option("--hostname", "-n", required=True, help="Hostname to use in the report.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Directory to write the report.")
def node(platform: str, input_file: str, hostname: str, output_dir: str) -> None:
    """Generate a report for a single host from a raw YAML file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        bundle = yaml.safe_load(f)

    common_vars = generate_timestamps()
    env = get_jinja_env()
    kw = vm_kwargs(common_vars)

    schema_names = default_registry().schema_names_for_platform(platform)
    all_schemas = discover_schemas()
    schema = next((all_schemas[n] for n in schema_names if n in all_schemas), None)
    if schema is None:
        click.echo(f"ERROR: no schema found for platform '{platform}'", err=True)
        raise SystemExit(1)

    view = build_generic_node_view(schema, hostname, bundle, **kw)
    tpl = env.get_template("generic_node_report.html.j2")
    content = tpl.render(generic_node_view=view, **common_vars)

    dest = output_path / f"{hostname}_health_report.html"
    with open(dest, "w") as f:
        f.write(content)

    click.echo(f"Success: Report generated at {dest}")


# ---------------------------------------------------------------------------
# schema command group
# ---------------------------------------------------------------------------


@main.group()
def schema() -> None:
    """Inspect and validate YAML report schemas."""


@schema.command("list")
@click.option(
    "--extra-schema-dir", "-S", multiple=True, metavar="DIR", help="Additional schema directory to search (repeatable)."
)
def schema_list(extra_schema_dir: tuple[str, ...]) -> None:
    """List all discovered schemas and their source paths."""
    schemas = discover_schemas(extra_dirs=tuple(extra_schema_dir))
    if not schemas:
        click.echo("No schemas found.")
        return
    for name, s in sorted(schemas.items()):
        source = getattr(s, "_source_path", "unknown")
        example = load_example_bundle(s)
        example_status = "example OK" if example else "no example file"
        click.echo(f"  {name:20s}  platform={s.platform:10s}  {example_status:14s}  {source}")


@schema.command("validate")
@click.argument("schema_file", type=click.Path(exists=True, path_type=Path))
def schema_validate(schema_file: Path) -> None:
    """Validate a schema file with comprehensive checks.

    SCHEMA_FILE: path to a *.yaml schema file.

    Checks performed:
      - YAML + Pydantic structural validation
      - Unused fields (declared but not referenced in alerts/widgets/fleet_columns)
      - Message format strings reference valid fields
      - Script files exist in the schema scripts directory
      - Field paths resolve against example data (if .example.yaml exists)
    """
    try:
        s = load_schema_from_file(schema_file)
    except ValueError as exc:
        click.echo(f"INVALID: {exc}", err=True)
        raise SystemExit(1)

    warnings: list[str] = []
    errors: list[str] = []

    # --- Check unused fields ---
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
    # Also count compute/script dependencies as referenced
    for spec in s.fields.values():
        if spec.compute:
            import re

            for ref in re.findall(r"\{(\w+)\}", spec.compute):
                referenced.add(ref)
        if spec.script_args:
            for v in spec.script_args.values():
                if isinstance(v, str):
                    import re

                    for ref in re.findall(r"\{(\w+)\}", v):
                        referenced.add(ref)
    unreferenced = {k for k in s.fields if not k.startswith("_") and k not in referenced}
    if unreferenced:
        warnings.append(f"Unused fields (not referenced in alerts/widgets/fleet_columns): {', '.join(sorted(unreferenced))}")

    # --- Check message format strings ---
    import re

    declared = set(s.fields.keys())
    for rule in s.alerts:
        for match in re.finditer(r"\{(\w+)", rule.message):
            ref = match.group(1)
            if ref != "value" and not ref.startswith("_") and ref not in declared:
                errors.append(f"alert '{rule.id}': message references undeclared field '{ref}'")

    # --- Check script files exist ---
    from .normalization.schema_driven import _BUILTIN_SCRIPTS_DIR

    schema_dir = schema_file.parent
    for name, spec in s.fields.items():
        if spec.script is None:
            continue
        p = Path(spec.script)
        found = p.is_absolute() and p.exists()
        if not found:
            found = (schema_dir / spec.script).exists()
        if not found:
            found = p.exists()
        if not found:
            found = (_BUILTIN_SCRIPTS_DIR / spec.script).exists()
        if not found:
            errors.append(f"field '{name}': script '{spec.script}' not found")

    # --- Check field paths against example data ---
    example = load_example_bundle(s)
    path_errors: dict[str, str] = {}
    if example is not None:
        path_errors = validate_schema_paths(s, example)
        for msg in path_errors.values():
            errors.append(msg)

    # --- Output ---
    click.echo(
        f"Schema '{s.name}' — {len(s.fields)} fields, {len(s.alerts)} alerts, {len(s.widgets)} widgets"
    )

    if warnings:
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
@click.option("--name", required=True, help="Schema name (e.g. 'linux', 'my_platform').")
@click.option(
    "--from-bundle",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Raw YAML data bundle to generate field entries from.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Write output to file instead of stdout.",
)
def schema_init(name: str, from_bundle: Path | None, output: Path | None) -> None:
    """Generate a starter schema YAML template.

    Without --from-bundle: produces a starter template with example entries.
    With --from-bundle: walks the key tree of a raw YAML bundle and generates
    field entries for every leaf key with inferred types.
    """
    if from_bundle is not None:
        content = _schema_from_bundle(name, from_bundle)
    else:
        content = _schema_template(name)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        click.echo(f"Schema written to {output}")
    else:
        click.echo(content)


def _schema_template(name: str) -> str:
    """Generate a minimal starter schema template."""
    return f"""name: {name}

detection:
  keys_any: [{name}_raw_data]

# Uncomment to reduce path repetition — paths starting with '.' are relative.
# path_prefix: "{name}_raw_data.data"

fields:
  hostname:
    path: "{name}_raw_data.data.hostname"
    fallback: "unknown"

  example_metric:
    path: "{name}_raw_data.data.some_metric"
    type: float

  example_computed:
    compute: "{{example_metric}} * 100"
    type: float

alerts:
  - id: example_alert
    category: "Example"
    severity: WARNING
    condition:
      op: gt
      field: example_metric
      threshold: 90.0
    message: "Example metric is high: {{example_metric:.1f}}"

widgets:
  - id: alerts
    title: "Active Alerts"
    type: alert_panel

  - id: overview
    title: "Overview"
    type: key_value
    fields:
      - {{ label: "Hostname", field: hostname }}
      - {{ label: "Example Metric", field: example_metric }}
"""


def _infer_type(value: Any) -> str:
    """Infer a schema field type string from a Python value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "str"


def _walk_keys(data: Any, prefix: str, result: list[tuple[str, str, str]]) -> None:
    """Recursively walk a nested dict, collecting (path, field_name, type) tuples."""
    if isinstance(data, dict):
        for key, value in data.items():
            full_path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                _walk_keys(value, full_path, result)
            elif isinstance(value, list):
                # Record the list itself as a field
                safe_name = full_path.replace(".", "_").replace("-", "_")
                result.append((full_path, safe_name, "list"))
            else:
                safe_name = full_path.replace(".", "_").replace("-", "_")
                result.append((full_path, safe_name, _infer_type(value)))


def _schema_from_bundle(name: str, bundle_path: Path) -> str:
    """Generate a schema from a raw YAML data bundle."""
    with open(bundle_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise click.ClickException(f"Bundle {bundle_path} is not a YAML mapping")

    # Walk the key tree
    entries: list[tuple[str, str, str]] = []
    _walk_keys(data, "", entries)

    # Detect a common prefix
    top_key = next(iter(data.keys())) if data else name
    detection_key = top_key

    lines = [
        f"name: {name}",
        "",
        "detection:",
        f"  keys_any: [{detection_key}]",
        "",
        "# Uncomment and adjust to reduce path repetition:",
        f'# path_prefix: "{top_key}.data"',
        "",
        f"# Generated from {bundle_path.name} — {len(entries)} leaf keys discovered",
        "fields:",
    ]

    for path, field_name, ftype in entries:
        lines.append(f"  {field_name}:")
        lines.append(f'    path: "{path}"')
        if ftype != "str":
            lines.append(f"    type: {ftype}")
        lines.append("")

    lines.append("alerts: []")
    lines.append("")
    lines.append("widgets:")
    lines.append("  - id: alerts")
    lines.append('    title: "Active Alerts"')
    lines.append("    type: alert_panel")
    lines.append("")

    return "\n".join(lines)


@schema.command("run")
@click.argument("schema_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to raw YAML bundle."
)
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Directory to write reports.")
@click.option("--hostname", "-n", default="host", show_default=True, help="Hostname label for node report.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
@click.option(
    "--site-report",
    "site_report_href",
    default=None,
    help="Relative path from output-dir to site report (enables site breadcrumb).",
)
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
        import yaml as _yaml

        bundle = _yaml.safe_load(f) or {}

    common_vars = generate_timestamps(report_stamp)
    kw = vm_kwargs(common_vars)
    env = get_jinja_env()

    fleet_filename = f"{s.name}_fleet_report.html"
    node_nav: dict[str, str] = {"fleet_report": f"../{fleet_filename}", "fleet_label": f"{s.display_name} Fleet"}
    fleet_nav: dict[str, str] = {}
    if site_report_href:
        fleet_nav["site_report"] = site_report_href
        node_nav["site_report"] = f"../{site_report_href}"

    # Node report
    node_view = build_generic_node_view(s, hostname, bundle, nav=node_nav, **kw)
    node_tpl = env.get_template("generic_node_report.html.j2")
    content = node_tpl.render(generic_node_view=node_view, **common_vars)
    host_dir = output_path / hostname
    host_dir.mkdir(exist_ok=True)
    write_report(host_dir, "health_report.html", content, common_vars["report_stamp"])
    click.echo(f"Node report: {host_dir}/health_report.html")

    # Fleet report (single host)
    fleet_view = build_generic_fleet_view(s, {hostname: bundle}, nav=fleet_nav, **kw)
    fleet_tpl = env.get_template("generic_fleet_report.html.j2")
    content = fleet_tpl.render(generic_fleet_view=fleet_view, **common_vars)
    write_report(output_path, fleet_filename, content, common_vars["report_stamp"])
    click.echo(f"Fleet report: {output_path}/{fleet_filename}")
    click.echo("Done!")


# ---------------------------------------------------------------------------
# stig command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state."
)
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def stig(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate STIG compliance reports (per-host and fleet overview)."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)
    # Generate CKLB first so STIG HTML can hydrate description/check/fix content from it.
    ctx = click.get_current_context()
    ctx.invoke(cklb, input_file=input_file, output_dir=str(output_path / "cklb"), skeleton_dir=None)
    _render_stig(
        hosts_data,
        output_path,
        common_vars,
        cklb_dir=output_path / "cklb",
    )
    click.echo(f"Done! STIG reports generated in {output_dir}")


# ---------------------------------------------------------------------------
# cklb command
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state."
)
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for CKLB files.")
@click.option("--skeleton-dir", type=click.Path(exists=True), help="Directory containing CKLB skeleton files.")
def cklb(input_file: str, output_dir: str, skeleton_dir: str | None) -> None:
    """Generate CKLB artifacts for STIG results."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    s_dir = Path(skeleton_dir) if skeleton_dir else Path(__file__).parent / "cklb_skeletons"
    hosts_data = load_hosts_data(input_file)

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            target_type = str(payload.get("target_type", ""))
            skeleton_file = default_registry().stig_skeleton_for_target(target_type)
            if not skeleton_file:
                continue

            sk_path = s_dir / skeleton_file
            if not sk_path.exists():
                click.echo(f"Warning: Skeleton not found for {target_type} at {sk_path}")
                continue

            ip_addr = str(payload.get("ip_address") or bundle.get("ip_address") or "")

            dest = output_path / f"{hostname}_{target_type}.cklb"
            generate_cklb(hostname, payload.get("full_audit", []), sk_path, dest, ip_address=ip_addr)
            click.echo(f"Generated CKLB: {dest}")


# ---------------------------------------------------------------------------
# stig-apply command
# ---------------------------------------------------------------------------


@main.command("stig-apply")
@click.argument("artifact", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--inventory", default="inventory/production/hosts.yaml", show_default=True, help="Ansible inventory path."
)
@click.option("--limit", required=True, help="Ansible --limit (e.g. vcenter1).")
@click.option("--target-type", default="", help="Override target type (esxi/vm/vcsa/photon/ubuntu).")
@click.option(
    "--target-host",
    default="",
    help="Override target host used for target-scoped vars (auto-inferred from artifact by default).",
)
@click.option("--esxi-host", default="", help="ESXi hostname override (legacy alias for --target-host).")
@click.option(
    "--skip-snapshot", is_flag=True, help="Suppress the informational note that ESXi snapshots are not applicable."
)
@click.option("--post-audit", is_flag=True, help="Reserved: run the ESXi audit after each rule (not yet implemented).")
@click.option(
    "--extra-vars", "-e", "extra_vars", multiple=True, help="Additional ansible extra-vars (may be repeated)."
)
@click.option("--dry-run", is_flag=True, help="Print the generated playbook without executing it.")
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
    """Apply STIG remediation interactively from a raw STIG YAML artifact.

    - ESXi: per-rule interactive apply.
    - VM/VCSA/Photon/Ubuntu: interactive confirmation + target playbook apply.
    """
    from ._stig_apply import (
        SUPPORTED_TARGET_TYPES,
        detect_target_type,
        infer_target_host,
        load_stig_artifact,
        run_generic_interactive_apply,
        run_interactive_apply,
    )

    raw = load_stig_artifact(artifact)
    detected_target_type = detect_target_type(raw, artifact, override=target_type)
    if not detected_target_type:
        raise click.ClickException(
            "Could not determine target type from artifact. Provide --target-type (esxi/vm/vcsa/photon/ubuntu)."
        )

    normalized_target = detected_target_type.lower()
    if normalized_target not in SUPPORTED_TARGET_TYPES:
        raise click.ClickException(
            f"Unsupported target type '{normalized_target}'. Supported: esxi, vm, vcsa, photon, ubuntu."
        )

    effective_target_host = target_host or esxi_host or infer_target_host(raw)

    if normalized_target == "esxi":
        if not effective_target_host:
            raise click.ClickException(
                "ESXi apply requires a target host. Provide --target-host (or legacy --esxi-host)."
            )
        run_interactive_apply(
            artifact=artifact,
            inventory=inventory,
            limit=limit,
            esxi_host=effective_target_host,
            skip_snapshot=skip_snapshot,
            post_audit=post_audit,
            extra_vars=extra_vars,
            dry_run=dry_run,
        )
        return

    run_generic_interactive_apply(
        artifact=artifact,
        inventory=inventory,
        limit=limit,
        target_type=normalized_target,
        target_host=effective_target_host,
        extra_vars=extra_vars,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()
