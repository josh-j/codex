#!/usr/bin/env python3
"""Generate example reports using the production aggregation pipeline.

Writes raw_*.yaml files exactly as ncs_collector would, then runs the same
load_all_reports → normalize_host_bundle → _render_platform → site pipeline
that ``ncs-reporter all`` uses.  The raw files are the inputs; nothing is
passed in-memory to the renderer.

Output:
  tests/ncs_example_reports/
  ├── site_health_report.html
  ├── stig_fleet_report.html                            ← NEW
  └── platform/
      ├── ubuntu/              ← raw input dir (ncs_collector writes here)
      │   ├── web-prod-01/raw_discovery.yaml
      │   ├── web-prod-01/raw_stig_ubuntu.yaml          ← NEW raw input
      │   └── web-prod-02/raw_discovery.yaml
      ├── vmware/              ← raw input dir
      │   ├── vcenter-prod/raw_vcenter.yaml
      │   └── vcenter-prod/raw_stig_esxi.yaml           ← NEW raw input
      ├── windows/             ← raw input dir
      │   ├── win-srv-01/raw_audit.yaml
      │   └── win-srv-01/raw_stig_windows.yaml          ← NEW raw input
      ├── ubuntu/              ← HTML output dir (same dir for linux)
      │   ├── linux_fleet_report.html
      │   ├── web-prod-01/health_report.html
      │   └── web-prod-01/web-prod-01_stig_ubuntu.html  ← NEW
      ├── vcenter/             ← HTML output dir (renamed from vmware)
      │   ├── vcenter_fleet_report.html
      │   ├── vcenter-prod/health_report.html
      │   └── vcenter-prod/vcenter-prod_stig_esxi.html  ← NEW
      └── windows/             ← HTML output dir (same dir for windows)
          ├── windows_fleet_report.html
          ├── win-srv-01/health_report.html
          └── win-srv-01/win-srv-01_stig_windows.html   ← NEW
"""

import sys
from pathlib import Path

import yaml

# ncs_reporter package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
# tests/ directory — for fixtures package
sys.path.insert(0, str(Path(__file__).parent))

from fixtures.example_data import (
    make_linux_bundle,
    make_vcenter_bundle,
    make_vcenter_site_bundle,
    make_windows_bundle,
    ALL_VCENTER_SITES,
    make_stig_esxi_bundle,
    make_stig_vm_bundle,
    make_stig_ubuntu_bundle,
    make_stig_windows_bundle,
)
from ncs_reporter._report_context import generate_timestamps, get_jinja_env, vm_kwargs
from ncs_reporter.aggregation import load_all_reports, normalize_host_bundle
from ncs_reporter.cli import _render_platform, _render_stig
from ncs_reporter.view_models.site import build_site_dashboard_view

OUT_ROOT = Path(__file__).parent / "ncs_example_reports"
PLATFORM_ROOT = OUT_ROOT / "platform"

# Matches the platform table in cli.all_cmd:
#   input_dir  — where ncs_collector writes raw_*.yaml files
#   report_dir — where ncs-reporter renders HTML reports
_PLATFORMS = [
    {"input_dir": "linux/ubuntu", "report_dir": "linux/ubuntu", "platform": "linux", "render": True},
    {"input_dir": "vmware/vcenter", "report_dir": "vmware/vcenter", "platform": "vmware", "render": True},
    {"input_dir": "vmware/esxi", "report_dir": "vmware/esxi", "platform": "vmware", "render": False},
    {"input_dir": "vmware/vm", "report_dir": "vmware/vm", "platform": "vmware", "render": False},
    {"input_dir": "windows", "report_dir": "windows", "platform": "windows", "render": True},
]

_PLATFORM_BY_KEY_PREFIX: dict[str, str] = {
    "ubuntu_": "linux/ubuntu",
    "vmware_": "vmware/vm",
    "windows_": "windows",
}


def _write_raw_yaml(bundle: dict) -> None:
    """Write bundle envelope as raw_{raw_type}.yaml, mirroring ncs_collector output.

    The bundle dict has one key per collection (e.g. ``ubuntu_raw_discovery``);
    the value is the {metadata, data} envelope the callback would have written.
    Path: platform/{platform}/{hostname}/raw_{raw_type}.yaml
    """
    for bundle_key, envelope in bundle.items():
        if not isinstance(envelope, dict):
            continue
        meta = envelope.get("metadata", {})
        raw_type = meta.get("raw_type", "raw")
        host = meta.get("host", "unknown")
        platform = next(
            (v for prefix, v in _PLATFORM_BY_KEY_PREFIX.items() if bundle_key.startswith(prefix)),
            "unknown",
        )
        if raw_type == "stig_esxi":
            platform = "vmware/esxi"
        elif raw_type == "stig_vm":
            platform = "vmware/vm"
        elif raw_type == "vcenter":
            platform = "vmware/vcenter"

        host_dir = PLATFORM_ROOT / platform / host
        host_dir.mkdir(parents=True, exist_ok=True)
        raw_path = host_dir / f"raw_{raw_type}.yaml"
        with open(raw_path, "w", encoding="utf-8") as f:
            yaml.dump(envelope, f, default_flow_style=False, sort_keys=False, indent=2)

        if "stig" in bundle_key:
            import json

            data = envelope.get("data", [])
            stig_xml_rows = []
            for item in data:
                stig_xml_rows.append(
                    {
                        "id": item.get("id"),
                        "rule_id": item.get("id"),
                        "name": host,
                        "status": item.get("status"),
                        "title": item.get("title"),
                        "severity": item.get("severity"),
                        "fixtext": "",
                        "checktext": "",
                    }
                )
            json_path = host_dir / f"xccdf-results_{host}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(stig_xml_rows, f, indent=2)


def main() -> None:
    # ------------------------------------------------------------------
    # 1. Write raw YAML files — mirrors what ncs_collector persists
    # ------------------------------------------------------------------
    bundles = [
        make_linux_bundle("web-prod-01", "10.10.20.45", unhealthy=True),
        make_linux_bundle("web-prod-02", "10.10.20.46", unhealthy=False, variety=True),
        make_vcenter_bundle("vcenter-prod", unhealthy=True),
        *[make_vcenter_site_bundle(s) for s in ALL_VCENTER_SITES],
        make_windows_bundle("win-srv-01", unhealthy=True),
        make_stig_esxi_bundle("vcenter-prod", unhealthy=True),
        make_stig_vm_bundle("web-prod-01", unhealthy=True),
        make_stig_ubuntu_bundle("web-prod-01", unhealthy=True),
        make_stig_windows_bundle("win-srv-01", unhealthy=True),
    ]
    for bundle in bundles:
        _write_raw_yaml(bundle)

    # ------------------------------------------------------------------
    # 2. Aggregate + render — same pipeline as ``ncs-reporter all``
    # ------------------------------------------------------------------
    common_vars = generate_timestamps(None)
    all_hosts: dict = {}
    global_inventory_index: dict[str, str] = {}

    # First pass to build global_inventory_index
    for p in _PLATFORMS:
        p_dir = PLATFORM_ROOT / p["input_dir"]
        if not p_dir.is_dir():
            continue
        p_data = load_all_reports(str(p_dir), host_normalizer=normalize_host_bundle)
        if not p_data or not p_data["hosts"]:
            continue
        all_hosts.update(p_data["hosts"])
        for h in p_data["hosts"]:
            global_inventory_index[h] = p["report_dir"]

    # Second pass to render
    for p in _PLATFORMS:
        if not p.get("render", True):
            continue

        p_dir = PLATFORM_ROOT / p["input_dir"]
        if not p_dir.is_dir():
            continue
        p_hosts = {h: data for h, data in all_hosts.items() if global_inventory_index.get(h) == p["report_dir"]}
        if not p_hosts:
            continue

        output_dir = OUT_ROOT / "platform" / p["report_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        _render_platform(
            p["platform"],
            p_hosts,
            output_dir,
            common_vars,
            site_report_relative="../../../site_health_report.html"
            if "/" in p["report_dir"]
            else "../../site_health_report.html",
            global_inventory_index=global_inventory_index,
        )

    # ------------------------------------------------------------------
    # 3. Site dashboard
    # ------------------------------------------------------------------
    env = get_jinja_env()
    kw = vm_kwargs(common_vars)
    site_view = build_site_dashboard_view(
        {"metadata": {}, "hosts": all_hosts},
        inventory_groups={
            "ubuntu_servers": ["web-prod-01", "web-prod-02"],
            "vcenters": [
                "vcenter-prod",
                "vcenter-us-east.corp.local",
                "vcenter-us-west.corp.local",
                "vcenter-eu-de.corp.local",
                "vcenter-eu-uk.corp.local",
                "vcenter-apac-sg.corp.local",
                "vcenter-apac-au.corp.local",
            ],
            "windows_servers": ["win-srv-01"],
        },
        **kw,
    )
    tpl = env.get_template("site_health_report.html.j2")
    content = tpl.render(site_dashboard_view=site_view, **common_vars)
    (OUT_ROOT / "site_health_report.html").write_text(content)

    # ------------------------------------------------------------------
    # 4. STIG reports — same as all_cmd step 4
    # ------------------------------------------------------------------
    _render_stig(all_hosts, OUT_ROOT, common_vars, global_inventory_index=global_inventory_index)

    # ------------------------------------------------------------------
    # 5. CKLBs via stig_xml callback artifacts
    # ------------------------------------------------------------------
    import json
    from ncs_reporter.normalization.stig import normalize_stig
    from ncs_reporter.cklb_export import generate_cklb

    s_dir = Path(__file__).parent.parent / "src/ncs_reporter/cklb_skeletons"
    skeleton_map = {
        "esxi": "cklb_skeleton_vsphere7_esxi_V1R4.json",
        "vm": "cklb_skeleton_vsphere7_vms_V1R4.json",
    }

    for json_file in PLATFORM_ROOT.glob("**/xccdf-results_*.json"):
        host = json_file.stem.split("_")[-1]

        # Determine platform directory from filename/path hints
        if "ubuntu" in str(json_file):
            t_type = "ubuntu"
            p_dir = "linux/ubuntu"
        elif "windows" in str(json_file):
            t_type = "windows"
            p_dir = "windows"
        elif "esxi" in str(json_file):
            t_type = "esxi"
            p_dir = "vmware/esxi"
        elif "vm" in str(json_file):
            t_type = "vm"
            p_dir = "vmware/vm"
        else:
            # Fallback for generic STIG artifacts
            t_type = ""
            p_dir = "unknown"

        raw_list = json.loads(json_file.read_text())
        model = normalize_stig(raw_list, stig_target_type=t_type)

        # Use the detected/normalized type for CKLB lookup
        final_type = t_type or ""
        # If we couldn't guess from filename, we might have it in alerts metadata now
        if not final_type and model.alerts:
            final_type = model.alerts[0].get("detail", {}).get("target_type", "")

        skel = skeleton_map.get(final_type)
        if skel:
            sk_path = s_dir / skel
            if sk_path.exists():
                # Place in node directory
                out_dir = OUT_ROOT / "platform" / p_dir / host
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"{host}_{t_type}.cklb"
                # Best effort IP extraction for example reports
                ip_addr = model.host_data.get("ip_address") if hasattr(model, "host_data") else ""
                generate_cklb(host, model.full_audit, sk_path, out_path, ip_address=str(ip_addr or ""))

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"Generated reports in {OUT_ROOT}/")
    print(f"  {OUT_ROOT}/site_health_report.html")
    for input_dir in ["linux/ubuntu", "vmware/vcenter", "vmware/esxi", "vmware/vm", "windows"]:
        for raw in sorted((PLATFORM_ROOT / input_dir).glob("*/raw_*.yaml")):
            print(f"  {raw}  [raw]")
        for json_art in sorted((PLATFORM_ROOT / input_dir).glob("*/xccdf-results_*.json")):
            print(f"  {json_art}  [stig_xml]")
    for report_dir in ["linux/ubuntu", "vmware/vcenter", "vmware/esxi", "vmware/vm", "windows"]:
        for html in sorted((OUT_ROOT / "platform" / report_dir).glob("**/health_report.html")):
            print(f"  {html}")


if __name__ == "__main__":
    main()
