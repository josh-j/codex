#!/usr/bin/env python3
"""Generate example reports with the canonical folder structure.

Output:
  tests/ncs_example_reports/
  ├── site_health_report.html
  └── platform/
      ├── ubuntu/
      │   ├── linux_fleet_report.html
      │   └── web-prod-01/health_report.html
      ├── vcenter/
      │   ├── vcenter_fleet_report.html
      │   └── vcenter-prod/health_report.html
      └── windows/
          ├── windows_fleet_report.html
          └── win-srv-01/health_report.html
"""

import sys
from pathlib import Path

# Make sure the package is importable when run from the tests/ directory
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from ncs_reporter._report_context import generate_timestamps, get_jinja_env, vm_kwargs, write_report
from ncs_reporter.normalization.schema_driven import normalize_from_schema
from ncs_reporter.schema_loader import load_schema_from_file
from ncs_reporter.view_models.generic import build_generic_fleet_view, build_generic_node_view
from ncs_reporter.view_models.site import build_site_dashboard_view

SCHEMAS_DIR = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas"
OUT_ROOT = Path(__file__).parent / "ncs_example_reports"

PLATFORMS = [
    {"schema": "linux",   "report_dir": "ubuntu",  "hostname": "web-prod-01"},
    {"schema": "vcenter", "report_dir": "vcenter",  "hostname": "vcenter-prod"},
    {"schema": "windows", "report_dir": "windows",  "hostname": "win-srv-01"},
]

SITE_REPORT_FROM_FLEET = "../../site_health_report.html"  # relative from platform/{dir}/


def main() -> None:
    common_vars = generate_timestamps(None)
    kw = vm_kwargs(common_vars)
    env = get_jinja_env()
    stamp = common_vars["report_stamp"]

    # Collect normalized data for site report
    aggregated_hosts: dict = {}

    for p in PLATFORMS:
        schema = load_schema_from_file(SCHEMAS_DIR / f"{p['schema']}.yaml")
        bundle_path = SCHEMAS_DIR / f"{p['schema']}.example.yaml"
        bundle = yaml.safe_load(bundle_path.read_text())
        hostname = p["hostname"]
        report_dir = OUT_ROOT / "platform" / p["report_dir"]
        report_dir.mkdir(parents=True, exist_ok=True)

        fleet_filename = f"{schema.name}_fleet_report.html"
        node_nav = {
            "fleet_report": f"../{fleet_filename}",
            "fleet_label": f"{schema.display_name} Fleet",
            "site_report": "../../../site_health_report.html",  # platform/{dir}/{host}/ → root
        }
        fleet_nav = {"site_report": SITE_REPORT_FROM_FLEET}

        # Node report
        node_view = build_generic_node_view(schema, hostname, bundle, nav=node_nav, **kw)
        node_tpl = env.get_template("generic_node_report.html.j2")
        content = node_tpl.render(generic_node_view=node_view, **common_vars)
        host_dir = report_dir / hostname
        host_dir.mkdir(exist_ok=True)
        write_report(host_dir, "health_report.html", content, stamp)

        # Fleet report
        fleet_view = build_generic_fleet_view(schema, {hostname: bundle}, nav=fleet_nav, **kw)
        fleet_tpl = env.get_template("generic_fleet_report.html.j2")
        content = fleet_tpl.render(generic_fleet_view=fleet_view, **common_vars)
        write_report(report_dir, fleet_filename, content, stamp)

        # Accumulate for site report
        normalized = normalize_from_schema(schema, bundle)
        aggregated_hosts[hostname] = {f"schema_{schema.name}": normalized}

    # Site report
    site_view = build_site_dashboard_view(
        {"hosts": aggregated_hosts},
        inventory_groups={"ubuntu_servers": ["web-prod-01"], "vcenters": ["vcenter-prod"], "windows_servers": ["win-srv-01"]},
        **kw,
    )
    site_tpl = env.get_template("site_health_report.html.j2")
    content = site_tpl.render(site_dashboard_view=site_view, **common_vars)
    (OUT_ROOT / "site_health_report.html").write_text(content)

    print(f"Generated reports in {OUT_ROOT}/")
    print(f"  {OUT_ROOT}/site_health_report.html")
    for p in PLATFORMS:
        schema_name = p["schema"]
        report_dir = p["report_dir"]
        hostname = p["hostname"]
        print(f"  {OUT_ROOT}/platform/{report_dir}/{schema_name}_fleet_report.html")
        print(f"  {OUT_ROOT}/platform/{report_dir}/{hostname}/health_report.html")


if __name__ == "__main__":
    main()
