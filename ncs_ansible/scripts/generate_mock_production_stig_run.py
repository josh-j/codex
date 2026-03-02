#!/usr/bin/env python3
"""Generate deterministic mock production STIG artifacts for integration/testing."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ENGINE = "ncs_collector_callback"

TARGET_SKELETON_MAP: dict[str, str] = {
    "esxi": "cklb_skeleton_vsphere7_esxi_V1R4.json",
    "vm": "cklb_skeleton_vsphere7_vms_V1R4.json",
    "vcsa": "cklb_skeleton_vsphere7_vcsa_V1R3.json",
    "vcenter": "cklb_skeleton_vsphere7_vcenter_V1R3.json",
    "vami": "cklb_skeleton_vsphere7_vami_V1R2.json",
    "eam": "cklb_skeleton_vsphere7_vca_eam_V1R2.json",
    "lookup_svc": "cklb_skeleton_vsphere7_vca_lookup_svc_V1R2.json",
    "perfcharts": "cklb_skeleton_vsphere7_vca_perfcharts_V1R1.json",
    "vcsa_photon_os": "cklb_skeleton_vsphere7_vca_photon_os_V1R4.json",
    "postgresql": "cklb_skeleton_vsphere7_vca_postgresql_V1R2.json",
    "rhttpproxy": "cklb_skeleton_vsphere7_vca_rhttpproxy_V1R1.json",
    "sts": "cklb_skeleton_vsphere7_vca_sts_V1R2.json",
    "ui": "cklb_skeleton_vsphere7_vca_ui_V1R2.json",
}

VCSA_COMPONENT_TARGETS = [
    "vami",
    "eam",
    "lookup_svc",
    "perfcharts",
    "vcsa_photon_os",
    "postgresql",
    "rhttpproxy",
    "sts",
    "ui",
]


def _resolve_skeleton_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "ncs_reporter" / "src" / "ncs_reporter" / "cklb_skeletons",
        here.parents[1] / "tools" / "ncs_reporter" / "src" / "ncs_reporter" / "cklb_skeletons",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Unable to locate ncs_reporter cklb_skeletons directory")


def _load_inventory(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Inventory file must be a mapping: {path}")
    return raw


def _build_group_index(inventory: dict[str, Any]) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, Any]]]:
    direct_hosts: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    hostvars: dict[str, dict[str, Any]] = {}

    for group, payload in inventory.items():
        if not isinstance(payload, dict):
            continue

        hosts = payload.get("hosts", {})
        if isinstance(hosts, dict):
            for host, vars_map in hosts.items():
                direct_hosts[group].add(str(host))
                if isinstance(vars_map, dict):
                    hostvars.setdefault(str(host), {}).update(vars_map)
                else:
                    hostvars.setdefault(str(host), {})

        child_map = payload.get("children", {})
        if isinstance(child_map, dict):
            for child_name in child_map.keys():
                children[group].add(str(child_name))

    return direct_hosts, children, hostvars


def _resolve_group_hosts(
    group: str,
    direct_hosts: dict[str, set[str]],
    children: dict[str, set[str]],
) -> set[str]:
    @lru_cache(maxsize=None)
    def _resolve(name: str) -> tuple[str, ...]:
        result: set[str] = set(direct_hosts.get(name, set()))
        for child in children.get(name, set()):
            result.update(_resolve(child))
        return tuple(sorted(result))

    return set(_resolve(group))


def _collect_hosts(
    suffix: str,
    fallback_group: str,
    groups: list[str],
    direct_hosts: dict[str, set[str]],
    children: dict[str, set[str]],
) -> list[str]:
    collected: set[str] = set()

    for group in sorted(groups):
        if group.endswith(suffix):
            collected.update(_resolve_group_hosts(group, direct_hosts, children))

    if not collected:
        collected.update(_resolve_group_hosts(fallback_group, direct_hosts, children))

    return sorted(collected)


def _inventory_groups_json(
    groups: list[str],
    direct_hosts: dict[str, set[str]],
    children: dict[str, set[str]],
) -> dict[str, list[str]]:
    rendered: dict[str, list[str]] = {}
    all_hosts: set[str] = set()

    for group in sorted(groups):
        hosts = sorted(_resolve_group_hosts(group, direct_hosts, children))
        rendered[group] = hosts
        all_hosts.update(hosts)

    rendered["all"] = sorted(all_hosts)
    return rendered


def _status_for(index: int, seed: int) -> str:
    statuses = ("failed", "pass", "na")
    return statuses[(index + seed) % len(statuses)]


def _map_severity(raw: Any) -> str:
    sev = str(raw or "medium").strip().lower()
    if sev in {"cat i", "high", "critical"}:
        return "high"
    if sev in {"cat iii", "low"}:
        return "low"
    return "medium"


def _load_skeleton_rules(skeleton_dir: Path, target_type: str) -> list[dict[str, Any]]:
    file_name = TARGET_SKELETON_MAP.get(target_type)
    if file_name is None:
        # Reuse VCSA skeleton for non-vmware platform targets to keep IDs/titles realistic.
        file_name = TARGET_SKELETON_MAP["vcsa"]

    sk_path = skeleton_dir / file_name
    with open(sk_path, encoding="utf-8") as f:
        skeleton = json.load(f)

    rules: list[dict[str, Any]] = []
    for stig in skeleton.get("stigs", []):
        rules.extend(stig.get("rules", []))

    return rules


def _build_stig_payload(host: str, target_type: str, stamp: str, skeleton_dir: Path, seed: int) -> dict[str, Any]:
    timestamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T00:00:00Z"
    source_rules = _load_skeleton_rules(skeleton_dir, target_type)

    findings: list[dict[str, Any]] = []
    for idx, rule in enumerate(source_rules[:14]):
        finding_id = str(rule.get("group_id") or rule.get("rule_id") or rule.get("rule_version") or f"V-MOCK-{idx}")
        findings.append(
            {
                "id": finding_id,
                "rule_id": str(rule.get("rule_id") or finding_id),
                "rule_version": str(rule.get("rule_version") or ""),
                "status": _status_for(idx, seed),
                "severity": _map_severity(rule.get("severity")),
                "title": str(rule.get("rule_title") or "Mock STIG Rule"),
                "checktext": str(rule.get("check_content") or "Validate configuration setting."),
                "fixtext": str(rule.get("fix_text") or "Apply secure baseline configuration."),
            }
        )

    return {
        "metadata": {
            "host": host,
            "raw_type": f"stig_{target_type}",
            "audit_type": f"stig_{target_type}",
            "timestamp": timestamp,
            "engine": ENGINE,
        },
        "data": findings,
        "target_type": target_type,
    }


def _build_windows_raw(host: str, stamp: str) -> dict[str, Any]:
    timestamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T00:00:00Z"
    return {
        "metadata": {"host": host, "raw_type": "audit", "timestamp": timestamp, "engine": ENGINE},
        "data": {
            "os_info": {"caption": "Microsoft Windows Server 2022 Standard", "version": "10.0.20348"},
            "ccm_service": {"state": "Running", "start_mode": "Auto"},
            "updates": {"installed_count": 32, "failed_count": 0, "pending_count": 1},
            "applications": [],
        },
    }


def _build_linux_discovery_raw(host: str, stamp: str, distro: str) -> dict[str, Any]:
    timestamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T00:00:00Z"
    os_family = "Debian" if distro.lower().startswith("ubuntu") else "VMware Photon"
    return {
        "metadata": {"host": host, "raw_type": "discovery", "timestamp": timestamp, "engine": ENGINE},
        "data": {
            "ansible_facts": {
                "hostname": host,
                "default_ipv4": {"address": "10.10.10.10"},
                "kernel": "6.8.0",
                "os_family": os_family,
                "distribution": distro,
                "distribution_version": "24.04" if distro.lower().startswith("ubuntu") else "5.0",
                "uptime_seconds": 864000,
                "loadavg": {"15m": 0.25},
                "memtotal_mb": 8192,
                "memfree_mb": 3072,
                "swaptotal_mb": 4096,
                "swapfree_mb": 4096,
                "date_time": {"epoch": "1772496000"},
                "mounts": [
                    {
                        "mount": "/",
                        "device": "/dev/sda1",
                        "fstype": "ext4",
                        "size_total": 100 * 1024 * 1024 * 1024,
                        "size_available": 45 * 1024 * 1024 * 1024,
                    }
                ],
            },
            "failed_services": {"stdout_lines": []},
            "apt_simulate": {"stdout_lines": ["0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."]},
            "reboot_stat": {"stat": {"exists": False}},
            "world_writable": {"stdout_lines": []},
            "shadow_raw": {"stdout_lines": []},
            "sshd_raw": {"stdout_lines": ["PermitRootLogin no", "PasswordAuthentication no"]},
        },
    }


def _build_vcenter_raw(host: str, stamp: str) -> dict[str, Any]:
    timestamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T00:00:00Z"
    return {
        "metadata": {"host": host, "raw_type": "vcenter", "timestamp": timestamp, "engine": ENGINE},
        "data": {
            "appliance_health_info": {
                "appliance": {
                    "summary": {
                        "product": "VMware vCenter Server",
                        "version": "8.0.3",
                        "build_number": "24022515",
                        "uptime": 1209600,
                        "health": {
                            "overall": "green",
                            "cpu": "green",
                            "memory": "green",
                            "database": "green",
                            "storage": "green",
                        },
                    },
                    "access": {"ssh": False, "shell": {"enabled": False}},
                    "time": {"time_sync": {"mode": "NTP"}},
                }
            },
            "appliance_backup_info": {"schedules": []},
            "datacenters_info": {"datacenter_info": [{"name": "DC1", "datacenter": "dc-1"}]},
            "clusters_info": {"results": [{"item": "DC1", "clusters": {}}]},
            "datastores_info": {"datastores": []},
            "vms_info": {"virtual_machines": []},
            "snapshots_info": {"snapshots": []},
            "alarms_info": {"alarms": []},
            "config": {"infrastructure_vm_patterns": []},
        },
    }


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def _derive_vm_hosts(vcenters: list[str], hostvars: dict[str, dict[str, Any]]) -> list[str]:
    vm_hosts: list[str] = []
    sites = sorted({str(hostvars.get(vc, {}).get("site", "")).strip() for vc in vcenters if hostvars.get(vc, {}).get("site")})
    if not sites:
        sites = ["site1"]

    for site in sites:
        vm_hosts.append(f"vm-app-01.{site}.local")
        vm_hosts.append(f"vm-db-01.{site}.local")

    return sorted(set(vm_hosts))


def generate(inventory_path: Path, out_root: Path, stamp: str) -> dict[str, Any]:
    inventory = _load_inventory(inventory_path)
    direct_hosts, children, hostvars = _build_group_index(inventory)
    groups = sorted(list({*direct_hosts.keys(), *children.keys(), *inventory.keys()}))

    vcenters = _collect_hosts("_vcenters", "vcenters", groups, direct_hosts, children)
    esxi_hosts = _collect_hosts("_esxi_hosts", "esxi_hosts", groups, direct_hosts, children)
    ubuntu_hosts = _collect_hosts("_ubuntu_servers", "ubuntu_servers", groups, direct_hosts, children)
    windows_hosts = _collect_hosts("_windows_servers", "windows_servers", groups, direct_hosts, children)
    photon_hosts = _collect_hosts("_photon_servers", "photon_servers", groups, direct_hosts, children)
    vm_hosts = _collect_hosts("_vms", "vms", groups, direct_hosts, children)

    if not vm_hosts:
        vm_hosts = _derive_vm_hosts(vcenters, hostvars)

    if not photon_hosts:
        photon_hosts = ["photon-svc-01"]

    if not vcenters:
        vcenters = ["vcsa-01.local"]

    if not esxi_hosts:
        esxi_hosts = ["esxi-01.local"]

    if not ubuntu_hosts:
        ubuntu_hosts = ["ubuntu-svc-01"]

    if not windows_hosts:
        windows_hosts = ["win-srv-01.local"]

    platform_root = out_root / "platform"
    skeleton_dir = _resolve_skeleton_dir()

    for idx, host in enumerate(vcenters):
        host_dir = platform_root / "vmware" / "vcenter" / "vcsa" / host
        _write_yaml(host_dir / "raw_vcenter.yaml", _build_vcenter_raw(host, stamp))
        _write_yaml(host_dir / "raw_stig_vcsa.yaml", _build_stig_payload(host, "vcsa", stamp, skeleton_dir, idx))
        for comp_idx, target in enumerate(VCSA_COMPONENT_TARGETS, start=1):
            _write_yaml(
                host_dir / f"raw_stig_{target}.yaml",
                _build_stig_payload(host, target, stamp, skeleton_dir, idx + comp_idx),
            )

    for idx, host in enumerate(esxi_hosts):
        host_dir = platform_root / "vmware" / "esxi" / host
        _write_yaml(host_dir / "raw_stig_esxi.yaml", _build_stig_payload(host, "esxi", stamp, skeleton_dir, idx + 10))

    for idx, host in enumerate(vm_hosts):
        host_dir = platform_root / "vmware" / "vm" / host
        _write_yaml(host_dir / "raw_stig_vm.yaml", _build_stig_payload(host, "vm", stamp, skeleton_dir, idx + 20))

    for idx, host in enumerate(windows_hosts):
        host_dir = platform_root / "windows" / host
        _write_yaml(host_dir / "raw_audit.yaml", _build_windows_raw(host, stamp))
        _write_yaml(
            host_dir / "raw_stig_windows.yaml",
            _build_stig_payload(host, "windows", stamp, skeleton_dir, idx + 30),
        )

    for idx, host in enumerate(ubuntu_hosts):
        host_dir = platform_root / "linux" / "ubuntu" / host
        _write_yaml(host_dir / "raw_discovery.yaml", _build_linux_discovery_raw(host, stamp, "Ubuntu"))
        _write_yaml(
            host_dir / "raw_stig_ubuntu.yaml",
            _build_stig_payload(host, "ubuntu", stamp, skeleton_dir, idx + 40),
        )

    for idx, host in enumerate(photon_hosts):
        host_dir = platform_root / "linux" / "photon" / host
        _write_yaml(host_dir / "raw_discovery.yaml", _build_linux_discovery_raw(host, stamp, "Photon OS"))
        _write_yaml(
            host_dir / "raw_stig_photon.yaml",
            _build_stig_payload(host, "photon", stamp, skeleton_dir, idx + 50),
        )

    groups_json = _inventory_groups_json(groups, direct_hosts, children)
    groups_json["vms"] = sorted(vm_hosts)
    groups_json["all"] = sorted(set(groups_json.get("all", [])) | set(vm_hosts))

    out_groups = platform_root / "inventory_groups.json"
    out_groups.parent.mkdir(parents=True, exist_ok=True)
    with open(out_groups, "w", encoding="utf-8") as f:
        json.dump(groups_json, f, indent=2, sort_keys=True)

    summary = {
        "out_root": str(out_root),
        "vcenters": vcenters,
        "esxi_hosts": esxi_hosts,
        "vm_hosts": vm_hosts,
        "windows_hosts": windows_hosts,
        "ubuntu_hosts": ubuntu_hosts,
        "photon_hosts": photon_hosts,
        "inventory_groups_json": str(out_groups),
    }
    return summary


def _default_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic mock production STIG artifacts.")
    parser.add_argument("--inventory", default="inventory/production/hosts.yaml", help="Inventory YAML path.")
    parser.add_argument(
        "--out-root",
        default="tests/reports/mock_production_run",
        help="Output root for generated mock run.",
    )
    parser.add_argument("--stamp", default=_default_stamp(), help="Report date stamp in YYYYMMDD.")
    args = parser.parse_args()

    inventory = Path(args.inventory)
    out_root = Path(args.out_root)
    stamp = str(args.stamp)

    if len(stamp) != 8 or not stamp.isdigit():
        raise ValueError("--stamp must be YYYYMMDD")

    summary = generate(inventory, out_root, stamp)
    print("Mock production STIG run generated:")
    for key, value in summary.items():
        if isinstance(value, list):
            print(f" - {key}: {len(value)} -> {', '.join(value)}")
        else:
            print(f" - {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
