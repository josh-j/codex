import json
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import yaml
from jinja2 import Environment, FileSystemLoader

from .aggregation import load_all_reports, write_output
from .csv_definitions import get_definitions, resolve_data_path
from .csv_export import export_csv as export_csv_fn
from .view_models.linux import build_linux_fleet_view, build_linux_node_view
from .view_models.vmware import build_vmware_fleet_view, build_vmware_node_view
from .view_models.windows import build_windows_fleet_view, build_windows_node_view
from .view_models.site import build_site_dashboard_view
from .view_models.stig import build_stig_host_view, build_stig_fleet_view

_VIEW_MODEL_KEYS = {"report_stamp", "report_date", "report_id"}


def _vm_kwargs(common_vars: dict) -> dict:
    """Extract only the keys accepted by view-model builder functions."""
    return {k: v for k, v in common_vars.items() if k in _VIEW_MODEL_KEYS}


def status_badge_meta(status: Any, preserve_label: bool = False) -> dict[str, str]:
    """
    Normalize a status/severity string into badge presentation metadata.
    """
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


def get_jinja_env() -> Environment:
    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["status_badge_meta"] = status_badge_meta
    # Add int filter if not present (Jinja2 usually has it)
    return env


@click.group()
def main() -> None:
    """NCS Reporter: Standalone reporting CLI for Codex."""
    pass


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def linux(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Linux fleet and node reports."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        data = yaml.safe_load(f)

    # Aggregated data might be under 'hosts' key or at root
    hosts_data = data.get("hosts", data) if isinstance(data, dict) else {}

    now = datetime.utcnow()
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")

    env = get_jinja_env()
    common_vars = {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }

    # 1. Render Host Reports
    _render_platform_linux(hosts_data, output_path, env, common_vars)

    click.echo(f"Done! Reports generated in {output_dir}")


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def vmware(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate VMware fleet and vCenter reports."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        data = yaml.safe_load(f)

    hosts_data = data.get("hosts", data) if isinstance(data, dict) else {}

    now = datetime.utcnow()
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")

    env = get_jinja_env()
    common_vars = {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }

    # 1. Render Host Reports
    _render_platform_vmware(hosts_data, output_path, env, common_vars)

    click.echo(f"Done! Reports generated in {output_dir}")


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
@click.option("--csv/--no-csv", "export_csv", default=True, help="Generate CSV exports (default: enabled).")
def windows(input_file: str, output_dir: str, report_stamp: str | None, export_csv: bool) -> None:
    """Generate Windows fleet and node reports."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        data = yaml.safe_load(f)

    hosts_data = data.get("hosts", data) if isinstance(data, dict) else {}

    now = datetime.utcnow()
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")

    env = get_jinja_env()
    common_vars = {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }

    _render_platform_windows(hosts_data, output_path, env, common_vars, export_csv=export_csv)

    click.echo(f"Done! Reports generated in {output_dir}")


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to global aggregated YAML state.")
@click.option("--groups", "-g", "groups_file", type=click.Path(exists=True), help="Path to inventory groups JSON/YAML.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def site(input_file: str, groups_file: str | None, output_dir: str, report_stamp: str | None) -> None:
    """Generate Global Site Health dashboard."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        data = yaml.safe_load(f)

    groups_data = {}
    if groups_file:
        with open(groups_file) as f:
            if groups_file.endswith(".json"):
                groups_data = json.load(f)
            else:
                groups_data = yaml.safe_load(f)

    now = datetime.utcnow()
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")

    env = get_jinja_env()
    common_vars = {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }

    click.echo("Rendering Global Site Health dashboard...")
    site_view = build_site_dashboard_view(
        data,
        inventory_groups=groups_data,
        report_stamp=stamp,
        report_date=date_str,
        report_id=rid,
    )
    
    tpl = env.get_template("site_health_report.html.j2")
    content = tpl.render(site_dashboard_view=site_view, **common_vars)
    
    with open(output_path / "site_health_report.html", "w") as f:
        f.write(content)

    click.echo(f"Done! Global dashboard generated in {output_dir}")


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


@main.command()
@click.option("--platform-root", required=True, type=click.Path(exists=True), help="Root directory for platforms (contains ubuntu, vmware, windows dirs).")
@click.option("--reports-root", required=True, type=click.Path(), help="Root directory for generated HTML reports.")
@click.option("--groups", "groups_file", type=click.Path(exists=True), help="Path to inventory groups JSON/YAML.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
@click.option("--csv/--no-csv", "export_csv", default=True, help="Generate CSV exports (default: enabled).")
def all(platform_root: str, reports_root: str, groups_file: str | None, report_stamp: str | None, export_csv: bool) -> None:
    """Run full aggregation and rendering for all platforms and the site dashboard."""
    p_root = Path(platform_root)
    r_root = Path(reports_root)
    
    now = datetime.utcnow()
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")
    
    env = get_jinja_env()
    common_vars = {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }

    platforms = [
        {"name": "ubuntu", "cmd": "linux", "state_file": "linux_fleet_state.yaml"},
        {"name": "vmware", "cmd": "vmware", "state_file": "vmware_fleet_state.yaml"},
        {"name": "windows", "cmd": "windows", "state_file": "windows_fleet_state.yaml"},
    ]

    # 1. Platform Aggregation & Rendering
    for p in platforms:
        p_dir = p_root / p["name"]
        if not p_dir.is_dir():
            continue
            
        state_path = p_dir / p["state_file"]
        click.echo(f"--- Processing Platform: {p['name']} ---")
        
        # Aggregate
        p_data = load_all_reports(str(p_dir))
        if not p_data or not p_data["hosts"]:
            click.echo(f"No data for {p['name']}, skipping.")
            continue
        write_output(p_data, str(state_path))
        
        # Render
        output_dir = r_root / "platform" / p["name"]
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Use existing logic by calling internal functions or just re-implementing briefly
        # For 'linux'
        if p["cmd"] == "linux":
            _render_platform_linux(p_data["hosts"], output_dir, env, common_vars)
        elif p["cmd"] == "vmware":
            _render_platform_vmware(p_data["hosts"], output_dir, env, common_vars)
        elif p["cmd"] == "windows":
            _render_platform_windows(p_data["hosts"], output_dir, env, common_vars, export_csv=export_csv)

    # 2. Global Site Aggregation & Rendering
    click.echo("--- Processing Global Site Dashboard ---")
    all_hosts_state = p_root / "all_hosts_state.yaml"
    global_data = load_all_reports(str(p_root))
    if global_data:
        write_output(global_data, str(all_hosts_state))
        
        groups_data = {}
        if groups_file:
            with open(groups_file) as f:
                groups_data = json.load(f) if groups_file.endswith(".json") else yaml.safe_load(f)
        
        site_view = build_site_dashboard_view(
            global_data, inventory_groups=groups_data, **_vm_kwargs(common_vars)
        )
        tpl = env.get_template("site_health_report.html.j2")
        content = tpl.render(site_dashboard_view=site_view, **common_vars)
        with open(r_root / "site_health_report.html", "w") as f:
            f.write(content)
        
        click.echo(f"Global dashboard generated at {r_root}/site_health_report.html")

        # 3. STIG Fleet Rendering
        click.echo("--- Processing STIG Fleet Reports ---")
        _render_stig(global_data.get("hosts", global_data), r_root, env, common_vars)
        click.echo("STIG fleet reports generated.")


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

    now = datetime.utcnow()
    common_vars = {
        "report_stamp": now.strftime("%Y%m%d"),
        "report_date": now.strftime("%Y-%m-%d %H:%M:%S"),
        "report_id": now.strftime("%Y%m%dT%H%M%SZ"),
        "now_date": now.strftime("%Y-%m-%d"),
        "now_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
    }

    env = get_jinja_env()
    
    vm_kw = _vm_kwargs(common_vars)
    if platform == "linux":
        view = build_linux_node_view(hostname, bundle, **vm_kw)
        tpl = env.get_template("ubuntu_host_health_report.html.j2")
        content = tpl.render(linux_node_view=view, **common_vars)
    elif platform == "vmware":
        view = build_vmware_node_view(hostname, bundle, **vm_kw)
        tpl = env.get_template("vcenter_health_report.html.j2")
        content = tpl.render(vmware_node_view=view, **common_vars)
    elif platform == "windows":
        view = build_windows_node_view(bundle, hostname=hostname, **vm_kw)
        tpl = env.get_template("windows_host_health_report.html.j2")
        content = tpl.render(windows_node_view=view, **common_vars)

    dest = output_path / f"{hostname}_health_report.html"
    with open(dest, "w") as f:
        f.write(content)
    
    click.echo(f"Success: Report generated at {dest}")


def _render_platform_linux(hosts_data: dict[str, Any], output_path: Path, env: Environment, common_vars: dict[str, Any]) -> None:
    report_stamp = common_vars["report_stamp"]
    host_tpl = env.get_template("ubuntu_host_health_report.html.j2")
    for hostname, bundle in hosts_data.items():
        node_view = build_linux_node_view(hostname, bundle, **_vm_kwargs(common_vars))
        host_dir = output_path / hostname
        host_dir.mkdir(exist_ok=True)
        content = host_tpl.render(linux_node_view=node_view, **common_vars)
        with open(host_dir / f"health_report_{report_stamp}.html", "w") as f:
            f.write(content)
        with open(host_dir / "health_report.html", "w") as f:
            f.write(content)

    fleet_view = build_linux_fleet_view(hosts_data, **_vm_kwargs(common_vars))
    fleet_tpl = env.get_template("ubuntu_health_report.html.j2")
    content = fleet_tpl.render(linux_fleet_view=fleet_view, **common_vars)
    with open(output_path / f"ubuntu_health_report_{report_stamp}.html", "w") as f:
        f.write(content)
    with open(output_path / "ubuntu_health_report.html", "w") as f:
        f.write(content)


def _render_platform_vmware(hosts_data: dict[str, Any], output_path: Path, env: Environment, common_vars: dict[str, Any]) -> None:
    report_stamp = common_vars["report_stamp"]
    host_tpl = env.get_template("vcenter_health_report.html.j2")
    for hostname, bundle in hosts_data.items():
        node_view = build_vmware_node_view(hostname, bundle, **_vm_kwargs(common_vars))
        host_dir = output_path / hostname
        host_dir.mkdir(exist_ok=True)
        content = host_tpl.render(vmware_node_view=node_view, **common_vars)
        with open(host_dir / f"health_report_{report_stamp}.html", "w") as f:
            f.write(content)
        with open(host_dir / "health_report.html", "w") as f:
            f.write(content)

    fleet_view = build_vmware_fleet_view(hosts_data, **_vm_kwargs(common_vars))
    fleet_tpl = env.get_template("vmware_health_report.html.j2")
    content = fleet_tpl.render(vmware_fleet_view=fleet_view, **common_vars)
    with open(output_path / f"vmware_health_report_{report_stamp}.html", "w") as f:
        f.write(content)
    with open(output_path / "vmware_health_report.html", "w") as f:
        f.write(content)


def _render_platform_windows(hosts_data: dict[str, Any], output_path: Path, env: Environment, common_vars: dict[str, Any], export_csv: bool = True) -> None:
    report_stamp = common_vars["report_stamp"]
    host_tpl = env.get_template("windows_host_health_report.html.j2")
    csv_defs = get_definitions("windows") if export_csv else []

    for hostname, bundle in hosts_data.items():
        node_view = build_windows_node_view(bundle, hostname=hostname, **_vm_kwargs(common_vars))
        host_dir = output_path / hostname
        host_dir.mkdir(exist_ok=True)
        content = host_tpl.render(windows_node_view=node_view, **common_vars)
        with open(host_dir / f"health_report_{report_stamp}.html", "w") as f:
            f.write(content)
        with open(host_dir / "health_report.html", "w") as f:
            f.write(content)

        for defn in csv_defs:
            rows = resolve_data_path(bundle, defn["data_path"])
            if not rows:
                continue
            # Inject hostname as "Server" into each row
            rows = [{**r, "server": hostname} for r in rows]
            csv_path = host_dir / f"{defn['report_name']}_{hostname}.csv"
            export_csv_fn(rows, defn["headers"], csv_path, sort_by=defn.get("sort_by"))

    fleet_view = build_windows_fleet_view(hosts_data, **_vm_kwargs(common_vars))
    fleet_tpl = env.get_template("windows_health_report.html.j2")
    content = fleet_tpl.render(windows_fleet_view=fleet_view, **common_vars)
    with open(output_path / f"windows_health_report_{report_stamp}.html", "w") as f:
        f.write(content)
    with open(output_path / "windows_health_report.html", "w") as f:
        f.write(content)


def _render_stig(hosts_data: dict[str, Any], output_path: Path, env: Environment, common_vars: dict[str, Any]) -> None:
    """Render per-host STIG reports and fleet overview."""
    report_stamp = common_vars["report_stamp"]
    host_tpl = env.get_template("stig_host_report.html.j2")
    vm_kw = _vm_kwargs(common_vars)
    all_hosts_data: dict[str, Any] = {}

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            host_view = build_stig_host_view(hostname, audit_type, payload, **vm_kw)
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

            # Track for fleet view
            all_hosts_data.setdefault(hostname, {})[audit_type] = payload

    if all_hosts_data:
        fleet_view = build_stig_fleet_view(all_hosts_data, **vm_kw)
        fleet_tpl = env.get_template("stig_fleet_report.html.j2")
        content = fleet_tpl.render(stig_fleet_view=fleet_view, **common_vars)
        with open(output_path / f"stig_fleet_report_{report_stamp}.html", "w") as f:
            f.write(content)
        with open(output_path / "stig_fleet_report.html", "w") as f:
            f.write(content)


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True), help="Path to aggregated YAML state.")
@click.option("--output-dir", "-o", required=True, type=click.Path(), help="Output directory for HTML reports.")
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD). Defaults to today.")
def stig(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate STIG compliance reports (per-host and fleet overview)."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        data = yaml.safe_load(f)

    hosts_data = data.get("hosts", data) if isinstance(data, dict) else {}

    now = datetime.utcnow()
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")

    env = get_jinja_env()
    common_vars = {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }

    _render_stig(hosts_data, output_path, env, common_vars)

    click.echo(f"Done! STIG reports generated in {output_dir}")


if __name__ == "__main__":
    main()
