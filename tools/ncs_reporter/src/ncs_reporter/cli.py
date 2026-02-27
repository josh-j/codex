import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import click
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
from .csv_definitions import get_definitions, resolve_data_path
from .csv_export import export_csv as export_csv_fn
from .view_models.linux import build_linux_fleet_view, build_linux_node_view
from .view_models.site import build_site_dashboard_view
from .view_models.stig import build_stig_fleet_view, build_stig_host_view
from .view_models.vmware import build_vmware_fleet_view, build_vmware_node_view
from .view_models.windows import build_windows_fleet_view, build_windows_node_view

logger = logging.getLogger("ncs_reporter")


def status_badge_meta(status: Any, preserve_label: bool = False) -> dict[str, str]:
    """Normalize a status/severity string into badge presentation metadata."""
    raw = str(status or "unknown").strip()
    upper = raw.upper()

    ok_values = {"OK", "HEALTHY", "GREEN", "PASS", "RUNNING"}
    fail_values = {"CRITICAL", "RED", "FAILED", "FAIL", "STOPPED"}

    if upper in ok_values:
        css_class = "status-ok"
        label = upper if preserve_label else "OK"
    elif upper in fail_values:
        css_class = "status-fail"
        label = upper if preserve_label else "CRITICAL"
    else:
        css_class = "status-warn"
        label = upper if preserve_label and upper else "WARN"

    return {"css_class": css_class, "label": label}


# ---------------------------------------------------------------------------
# Generic platform renderer
# ---------------------------------------------------------------------------

_PLATFORM_CONFIG: dict[str, dict[str, Any]] = {
    "linux": {
        "node_builder": build_linux_node_view,
        "fleet_builder": build_linux_fleet_view,
        "node_template": "ubuntu_host_health_report.html.j2",
        "fleet_template": "ubuntu_health_report.html.j2",
        "fleet_report_name": "ubuntu_health_report",
        "node_ctx_key": "linux_node_view",
        "fleet_ctx_key": "linux_fleet_view",
        "node_builder_style": "positional",  # (hostname, bundle, **kw)
    },
    "vmware": {
        "node_builder": build_vmware_node_view,
        "fleet_builder": build_vmware_fleet_view,
        "node_template": "vcenter_health_report.html.j2",
        "fleet_template": "vmware_health_report.html.j2",
        "fleet_report_name": "vmware_health_report",
        "node_ctx_key": "vmware_node_view",
        "fleet_ctx_key": "vmware_fleet_view",
        "node_builder_style": "positional",
    },
    "windows": {
        "node_builder": build_windows_node_view,
        "fleet_builder": build_windows_fleet_view,
        "node_template": "windows_host_health_report.html.j2",
        "fleet_template": "windows_health_report.html.j2",
        "fleet_report_name": "windows_health_report",
        "node_ctx_key": "windows_node_view",
        "fleet_ctx_key": "windows_fleet_view",
        "node_builder_style": "keyword",  # (bundle, hostname=..., **kw)
    },
}


def _render_platform(
    platform: str,
    hosts_data: dict[str, Any],
    output_path: Path,
    common_vars: dict[str, str],
    *,
    export_csv: bool = False,
) -> None:
    """Render node + fleet reports for a given platform."""
    cfg = _PLATFORM_CONFIG[platform]
    env = get_jinja_env()
    stamp = common_vars["report_stamp"]
    kw = vm_kwargs(common_vars)

    node_tpl = env.get_template(cfg["node_template"])
    csv_defs = get_definitions("windows") if (export_csv and platform == "windows") else []

    for hostname, bundle in hosts_data.items():
        if cfg["node_builder_style"] == "keyword":
            node_view = cfg["node_builder"](bundle, hostname=hostname, **kw)
        else:
            node_view = cfg["node_builder"](hostname, bundle, **kw)

        host_dir = output_path / hostname
        host_dir.mkdir(exist_ok=True)
        content = node_tpl.render(**{cfg["node_ctx_key"]: node_view}, **common_vars)
        write_report(host_dir, "health_report.html", content, stamp)

        # Windows-specific CSV export per host
        for defn in csv_defs:
            rows = resolve_data_path(bundle, defn["data_path"])
            if not rows:
                continue
            rows = [{**r, "server": hostname} for r in rows]
            csv_path = host_dir / f"{defn['report_name']}_{hostname}.csv"
            export_csv_fn(rows, defn["headers"], csv_path, sort_by=defn.get("sort_by"))

    fleet_view = cfg["fleet_builder"](hosts_data, **kw)
    fleet_tpl = env.get_template(cfg["fleet_template"])
    content = fleet_tpl.render(**{cfg["fleet_ctx_key"]: fleet_view}, **common_vars)
    write_report(output_path, f"{cfg['fleet_report_name']}.html", content, stamp)


# ---------------------------------------------------------------------------
# STIG renderer (shared between `stig` and `all` commands)
# ---------------------------------------------------------------------------

def _render_stig(hosts_data: dict[str, Any], output_path: Path, common_vars: dict[str, str]) -> None:
    """Render per-host STIG reports and fleet overview."""
    env = get_jinja_env()
    stamp = common_vars["report_stamp"]
    kw = vm_kwargs(common_vars)
    host_tpl = env.get_template("stig_host_report.html.j2")
    all_hosts_data: dict[str, Any] = {}

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            host_view = build_stig_host_view(hostname, audit_type, payload, **kw)
            target = host_view["target"]
            platform = target.get("platform", "unknown")
            target_type = target.get("target_type", "unknown")

            if platform == "vmware":
                platform_dir = "platform/vmware"
            elif platform == "windows":
                platform_dir = "platform/windows"
            else:
                platform_dir = "platform/ubuntu"

            host_dir = output_path / platform_dir / hostname
            host_dir.mkdir(parents=True, exist_ok=True)

            content = host_tpl.render(stig_host_view=host_view, **common_vars)
            dest_name = f"{hostname}_stig_{target_type}.html"
            with open(host_dir / dest_name, "w") as f:
                f.write(content)

            all_hosts_data.setdefault(hostname, {})[audit_type] = payload

    if all_hosts_data:
        fleet_view = build_stig_fleet_view(all_hosts_data, **kw)
        fleet_tpl = env.get_template("stig_fleet_report.html.j2")
        content = fleet_tpl.render(stig_fleet_view=fleet_view, **common_vars)
        write_report(output_path, "stig_fleet_report.html", content, stamp)


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
# Platform commands (linux, vmware, windows)
# ---------------------------------------------------------------------------

def _platform_command(platform: str, input_file: str, output_dir: str, report_stamp: str | None, export_csv: bool = False) -> None:
    """Shared implementation for single-platform report commands."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)
    _render_platform(platform, hosts_data, output_path, common_vars, export_csv=export_csv)
    click.echo(f"Done! Reports generated in {output_dir}")


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def linux(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Linux fleet and node reports."""
    _platform_command("linux", input_file, output_dir, report_stamp)


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def vmware(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate VMware fleet and vCenter reports."""
    _platform_command("vmware", input_file, output_dir, report_stamp)


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
@click.option("--csv/--no-csv", "export_csv", default=True, help="Generate CSV exports (default: enabled).")
def windows(input_file: str, output_dir: str, report_stamp: str | None, export_csv: bool) -> None:
    """Generate Windows fleet and node reports."""
    _platform_command("windows", input_file, output_dir, report_stamp, export_csv=export_csv)


# ---------------------------------------------------------------------------
# site command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to global aggregated YAML state.")
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
@click.option("--report-dir", required=True, type=click.Path(exists=True), help="Directory containing host YAML reports.")
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
@click.option("--csv/--no-csv", "export_csv", default=True, help="Generate CSV exports (default: enabled).")
def all_cmd(platform_root: str, reports_root: str, groups_file: str | None, report_stamp: str | None, export_csv: bool) -> None:
    """Run full aggregation and rendering for all platforms and the site dashboard."""
    p_root = Path(platform_root)
    r_root = Path(reports_root)
    common_vars = generate_timestamps(report_stamp)

    platforms = [
        {"name": "ubuntu", "platform": "linux", "state_file": "linux_fleet_state.yaml"},
        {"name": "vmware", "platform": "vmware", "state_file": "vmware_fleet_state.yaml"},
        {"name": "windows", "platform": "windows", "state_file": "windows_fleet_state.yaml"},
    ]

    # 1. Platform Aggregation (sequential — I/O bound directory walk)
    render_tasks: list[dict[str, Any]] = []
    for p in platforms:
        p_dir = p_root / p["name"]
        if not p_dir.is_dir():
            continue

        state_path = p_dir / p["state_file"]
        click.echo(f"--- Processing Platform: {p['name']} ---")

        p_data = load_all_reports(str(p_dir), host_normalizer=normalize_host_bundle)
        if not p_data or not p_data["hosts"]:
            click.echo(f"No data for {p['name']}, skipping.")
            continue
        write_output(p_data, str(state_path))

        output_dir = r_root / "platform" / p["name"]
        output_dir.mkdir(parents=True, exist_ok=True)
        render_tasks.append({
            "platform": p["platform"],
            "hosts_data": p_data["hosts"],
            "output_path": output_dir,
            "export_csv": export_csv and p["platform"] == "windows",
        })

    # 2. Parallel platform rendering
    if render_tasks:
        with ThreadPoolExecutor(max_workers=min(len(render_tasks), 3)) as pool:
            futures = {
                pool.submit(
                    _render_platform,
                    t["platform"],
                    t["hosts_data"],
                    t["output_path"],
                    common_vars,
                    export_csv=t["export_csv"],
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
        if groups_file:
            with open(groups_file) as f:
                groups_data = json.load(f) if groups_file.endswith(".json") else yaml.safe_load(f)

        site_view = build_site_dashboard_view(global_data, inventory_groups=groups_data, **vm_kwargs(common_vars))
        env = get_jinja_env()
        tpl = env.get_template("site_health_report.html.j2")
        content = tpl.render(site_dashboard_view=site_view, **common_vars)
        with open(r_root / "site_health_report.html", "w") as f:
            f.write(content)

        click.echo(f"Global dashboard generated at {r_root}/site_health_report.html")

        # 4. STIG Fleet Rendering
        click.echo("--- Processing STIG Fleet Reports ---")
        _render_stig(global_data.get("hosts", global_data), r_root, common_vars)

        # 5. CKLB Export
        click.echo("--- Generating CKLB Artifacts ---")
        ctx = click.get_current_context()
        ctx.invoke(cklb, input_file=str(all_hosts_state), output_dir=str(r_root / "cklb"))

        click.echo("STIG fleet reports and CKLB artifacts generated.")


# ---------------------------------------------------------------------------
# node command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--platform", "-p", required=True, type=click.Choice(["linux", "vmware", "windows"]), help="Target platform type.")
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to raw audit/discovery YAML file.")
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

    cfg = _PLATFORM_CONFIG[platform]
    if cfg["node_builder_style"] == "keyword":
        view = cfg["node_builder"](bundle, hostname=hostname, **kw)
    else:
        view = cfg["node_builder"](hostname, bundle, **kw)

    tpl = env.get_template(cfg["node_template"])
    content = tpl.render(**{cfg["node_ctx_key"]: view}, **common_vars)

    dest = output_path / f"{hostname}_health_report.html"
    with open(dest, "w") as f:
        f.write(content)

    click.echo(f"Success: Report generated at {dest}")


# ---------------------------------------------------------------------------
# stig command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def stig(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate STIG compliance reports (per-host and fleet overview)."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)
    _render_stig(hosts_data, output_path, common_vars)
    click.echo(f"Done! STIG reports generated in {output_dir}")


# ---------------------------------------------------------------------------
# cklb command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for CKLB files.")
@click.option("--skeleton-dir", type=click.Path(exists=True), help="Directory containing CKLB skeleton files.")
def cklb(input_file: str, output_dir: str, skeleton_dir: str | None) -> None:
    """Generate CKLB artifacts for STIG results."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    s_dir = Path(skeleton_dir) if skeleton_dir else Path(__file__).parent / "cklb_skeletons"
    hosts_data = load_hosts_data(input_file)

    skeleton_map = {
        "esxi": "cklb_skeleton_vsphere7_esxi_V1R4.json",
        "vm": "cklb_skeleton_vsphere7_vms_V1R4.json",
    }

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            target_type = str(payload.get("target_type", ""))
            skeleton_file = skeleton_map.get(target_type)
            if not skeleton_file:
                continue

            sk_path = s_dir / skeleton_file
            if not sk_path.exists():
                click.echo(f"Warning: Skeleton not found for {target_type} at {sk_path}")
                continue

            dest = output_path / f"{hostname}_{target_type}.cklb"
            generate_cklb(hostname, payload.get("full_audit", []), sk_path, dest)
            click.echo(f"Generated CKLB: {dest}")


# ---------------------------------------------------------------------------
# stig-apply command
# ---------------------------------------------------------------------------

@main.command("stig-apply")
@click.argument("artifact", type=click.Path(exists=True, path_type=Path))
@click.option("--inventory", default="inventory/production/hosts.yaml", show_default=True, help="Ansible inventory path.")
@click.option("--limit", required=True, help="Ansible --limit (e.g. vcenter1).")
@click.option("--esxi-host", required=True, help="ESXi hostname to target (sets esxi_stig_target_hosts).")
@click.option("--skip-snapshot", is_flag=True, help="Suppress the informational note that ESXi snapshots are not applicable.")
@click.option("--post-audit", is_flag=True, help="Reserved: run the ESXi audit after each rule (not yet implemented).")
@click.option("--extra-vars", "-e", "extra_vars", multiple=True, help="Additional ansible extra-vars (may be repeated).")
@click.option("--dry-run", is_flag=True, help="Print the generated playbook without executing it.")
def stig_apply(
    artifact: Path,
    inventory: str,
    limit: str,
    esxi_host: str,
    skip_snapshot: bool,
    post_audit: bool,
    extra_vars: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Apply ESXi STIG rules interactively, one at a time.

    ARTIFACT is the path to a raw_stig_esxi.yaml audit artifact.  A single
    Ansible playbook is generated with ``pause`` tasks so the vCenter connection
    stays warm across rules, keeping per-rule time to ~2-5 s.
    """
    from ._stig_apply import run_interactive_apply

    run_interactive_apply(
        artifact=artifact,
        inventory=inventory,
        limit=limit,
        esxi_host=esxi_host,
        skip_snapshot=skip_snapshot,
        post_audit=post_audit,
        extra_vars=extra_vars,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()
