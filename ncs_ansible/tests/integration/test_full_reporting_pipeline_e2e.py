"""Integration test: full ncs-reporter `all` generation from ncs_ansible config.

This validates end-to-end report generation for:
- platform reports (linux/vmware/windows)
- STIG reports (esxi/vm/ubuntu/windows)
- CKLB artifacts (esxi/vm)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import main

from _paths import SCHEMAS_DIR


def _linux_raw(host: str) -> dict:
    return {
        "metadata": {"host": host, "timestamp": "2026-03-01T00:00:00Z"},
        "data": {
            "ansible_facts": {
                "ansible_distribution": "Ubuntu",
                "ansible_distribution_version": "24.04",
                "ansible_kernel": "6.8.0",
                "mounts": [
                    {
                        "mount": "/",
                        "device": "/dev/sda1",
                        "fstype": "ext4",
                        "size_total": 100 * 1024 * 1024 * 1024,
                        "size_available": 40 * 1024 * 1024 * 1024,
                    }
                ],
                "date_time": {"epoch": "1740787200"},
            }
        },
    }


def _vcenter_raw(host: str) -> dict:
    return {
        "metadata": {"host": host, "timestamp": "2026-03-01T00:00:00Z"},
        "data": {
            "appliance_health_info": {
                "appliance": {
                    "summary": {
                        "product": "vCenter Server",
                        "version": "8.0.2",
                        "build_number": "23319199",
                        "uptime": 864000,
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


def _windows_raw(host: str) -> dict:
    return {
        "metadata": {"host": host, "timestamp": "2026-03-01T00:00:00Z"},
        "data": {
            "os_info": {"caption": "Microsoft Windows Server 2022 Standard", "version": "10.0.20348"},
            "ccm_service": {"state": "Running", "start_mode": "Auto"},
            "updates": {"installed_count": 10, "failed_count": 0, "pending_count": 1},
            "applications": [],
        },
    }


def _stig_raw(host: str, audit_type: str, target_type: str) -> dict:
    return {
        "metadata": {
            "host": host,
            "audit_type": audit_type,
            "timestamp": "2026-03-01T00:00:00Z",
            "engine": "ncs_collector_callback",
        },
        "data": [
            {
                "id": "V-256379",
                "status": "failed",
                "severity": "medium",
                "title": "stigrule_256379_account_lock_failures",
                "checktext": "Sample finding.",
            }
        ],
        "target_type": target_type,
    }


class TestFullReportingPipelineE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.platform_root = root / "platform"
        self.reports_root = root / "reports"

        linux_host = "linux-01"
        vcenter_host = "vc-01"
        windows_host = "win-01"
        esxi_host = "esxi-01"
        vm_host = "vm-01"

        linux_dir = self.platform_root / "linux" / "ubuntu" / linux_host
        linux_dir.mkdir(parents=True)
        (linux_dir / "raw_discovery.yaml").write_text(yaml.dump(_linux_raw(linux_host)))
        (linux_dir / "raw_stig_ubuntu.yaml").write_text(yaml.dump(_stig_raw(linux_host, "stig_ubuntu", "ubuntu")))

        vcenter_dir = self.platform_root / "vmware" / "vcenter" / vcenter_host
        vcenter_dir.mkdir(parents=True)
        (vcenter_dir / "raw_vcenter.yaml").write_text(yaml.dump(_vcenter_raw(vcenter_host)))

        esxi_dir = self.platform_root / "vmware" / esxi_host
        esxi_dir.mkdir(parents=True)
        (esxi_dir / "raw_stig_esxi.yaml").write_text(yaml.dump(_stig_raw(esxi_host, "stig_esxi", "esxi")))

        vm_dir = self.platform_root / "vmware" / vm_host
        vm_dir.mkdir(parents=True)
        (vm_dir / "raw_stig_vm.yaml").write_text(yaml.dump(_stig_raw(vm_host, "stig_vm", "vm")))

        windows_dir = self.platform_root / "windows" / windows_host
        windows_dir.mkdir(parents=True)
        (windows_dir / "raw_audit.yaml").write_text(yaml.dump(_windows_raw(windows_host)))
        (windows_dir / "raw_stig_windows.yaml").write_text(
            yaml.dump(_stig_raw(windows_host, "stig_windows", "windows"))
        )

        groups = {
            "all": [linux_host, vcenter_host, windows_host, esxi_host, vm_host],
            "ubuntu_servers": [linux_host],
            "vcenters": [vcenter_host],
            "windows_servers": [windows_host],
            "esxi_hosts": [esxi_host],
            "vms": [vm_host],
        }
        self.groups_path = self.platform_root / "inventory_groups.json"
        self.groups_path.write_text(json.dumps(groups))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_generates_reports_stig_and_cklb_for_all_platforms(self) -> None:
        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(self.groups_path),
                "--config-dir",
                str(SCHEMAS_DIR),
                "--report-stamp",
                "20260301",
            ],
        )
        self.assertEqual(result.exit_code, 0, f"CLI failed:\n{result.output}")

        # Site + fleet reports
        self.assertTrue((self.reports_root / "site_health_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "linux" / "ubuntu" / "linux_fleet_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "vmware" / "vcenter" / "vcenter_fleet_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "windows" / "windows_fleet_report.html").exists())

        # Node reports
        self.assertTrue((self.reports_root / "platform" / "linux" / "ubuntu" / "linux-01" / "health_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "vmware" / "vcenter" / "vc-01" / "health_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "windows" / "win-01" / "health_report.html").exists())

        # STIG reports
        self.assertTrue((self.reports_root / "stig_fleet_report.html").exists())
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / "esxi" / "esxi-01" / "esxi-01_stig_esxi.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / "vm" / "vm-01" / "vm-01_stig_vm.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "linux" / "ubuntu" / "linux-01" / "linux-01_stig_ubuntu.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "windows" / "win-01" / "win-01_stig_windows.html").exists()
        )

        # CKLB artifacts (supported target types only)
        esxi_cklb = self.reports_root / "cklb" / "esxi-01_esxi.cklb"
        vm_cklb = self.reports_root / "cklb" / "vm-01_vm.cklb"
        self.assertTrue(esxi_cklb.exists())
        self.assertTrue(vm_cklb.exists())
        self.assertEqual(json.loads(esxi_cklb.read_text())["target_data"]["host_name"], "esxi-01")
        self.assertEqual(json.loads(vm_cklb.read_text())["target_data"]["host_name"], "vm-01")

        # Aggregated state outputs
        self.assertTrue((self.platform_root / "linux" / "ubuntu" / "linux_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "vmware" / "vcenter" / "vmware_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "windows" / "windows_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "all_hosts_state.yaml").exists())
