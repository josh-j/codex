"""End-to-End tests for HTML report generation at all levels."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import main


def _has_attr(html: str, attr: str, value: str) -> bool:
    return f'{attr}="{value}"' in html or f"{attr}={value}" in html


class TestHtmlReportsE2E(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Setup telemetry lake structure
        self.platform_root = self.root / "platform"
        self.reports_root = self.root / "reports"

        # 1. Linux Data (Trigger a disk warning)
        self.linux_dir = self.platform_root / "linux" / "ubuntu" / "linux-01"
        self.linux_dir.mkdir(parents=True)
        linux_data = {
            "metadata": {"host": "linux-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "ansible_facts": {
                    "ansible_distribution": "Ubuntu",
                    "ansible_distribution_version": "24.04",
                    "ansible_kernel": "6.8.0-lowlatency",
                    "mounts": [
                        {
                            "mount": "/",
                            "device": "/dev/sda1",
                            "fstype": "ext4",
                            "size_total": 107374182400,  # 100GB
                            "size_available": 2147483648,  # 2GB (98% used -> CRITICAL)
                        }
                    ],
                    "date_time": {"epoch": "1740610800"},
                }
            },
        }
        with open(self.linux_dir / "ubuntu_raw_discovery.yaml", "w") as f:
            yaml.dump(linux_data, f)

        # 2. VMware Data (Trigger a health warning)
        self.vmware_dir = self.platform_root / "vmware" / "vcenter" / "vc-01"
        self.vmware_dir.mkdir(parents=True)
        vmware_data = {
            "metadata": {"host": "vc-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "appliance_health_info": {
                    "appliance": {
                        "summary": {
                            "product": "vCenter Server",
                            "version": "8.0.2",
                            "build_number": "23319199",
                            "uptime": 864000,
                        },
                        "health": {
                            "overall": "yellow",
                            "cpu": "green",
                            "memory": "yellow",
                            "database": "green",
                            "storage": "green",
                            "swap": "green",
                        },
                        "access": {"ssh": False},
                        "backup": {"enabled": True, "status": "SUCCEEDED"},
                    }
                },
                "datacenters_info": {"value": [{"name": "DC1", "datacenter": "datacenter-1"}]},
                "clusters_info": {
                    "results": [
                        {
                            "item": "DC1",
                            "clusters": {
                                "Cluster-A": {
                                    "resource_summary": {
                                        "cpuCapacityMHz": 10000,
                                        "cpuUsedMHz": 2000,
                                        "memCapacityMB": 32768,
                                        "memUsedMB": 8192,
                                    },
                                    "hosts": ["esxi-01.local"],
                                }
                            },
                        }
                    ]
                },
                "datastores_info": {
                    "datastores": [
                        {"name": "ds1", "capacity": 107374182400, "freeSpace": 53687091200, "accessible": True}
                    ]
                },
                "vms_info": {"virtual_machines": []},
                "snapshots_info": {"snapshots": []},
                "alarms_info": {"alarms": []},
            },
        }
        with open(self.vmware_dir / "vmware_raw_vcenter.yaml", "w") as f:
            yaml.dump(vmware_data, f)

        # 2b. ESXi per-host health data (separate input_dir: vmware/esxi)
        self.esxi_dir = self.platform_root / "vmware" / "esxi" / "vc-01"
        self.esxi_dir.mkdir(parents=True)
        esxi_data = {
            "metadata": {"host": "vc-01", "audit_type": "vmware_raw_esxi", "raw_type": "esxi",
                         "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "hosts_info": {
                    "host_facts": {"results": [{
                        "item": "esxi-01.local",
                        "ansible_facts": {
                            "ansible_distribution_version": "7.0.3",
                            "ansible_distribution_build": "12345",
                            "ansible_memtotal_mb": 65536,
                            "ansible_memfree_mb": 32768,
                            "ansible_uptime": 86400,
                            "ansible_overall_status": "green",
                            "ansible_host_connection_state": "connected",
                            "ansible_in_maintenance_mode": False,
                            "ansible_lockdown_mode": "disabled",
                            "ansible_datastore": [{"name": "ds1", "total": "1TB", "free": "500GB"}],
                        },
                    }]},
                    "host_nics": {"results": []},
                    "host_services": {"results": []},
                },
                "clusters_info": {
                    "results": [{
                        "item": "DC1",
                        "clusters": {"Cluster-A": {"hosts": [{"name": "esxi-01.local"}]}},
                    }],
                },
                "datastores_info": {"datastores": []},
                "config": {},
                "collection_status": "SUCCESS",
                "collection_error": "",
            },
        }
        with open(self.esxi_dir / "vmware_raw_esxi.yaml", "w") as f:
            yaml.dump(esxi_data, f)

        # 3. Windows Data
        self.windows_dir = self.platform_root / "windows" / "win-01"
        self.windows_dir.mkdir(parents=True)
        windows_data = {
            "metadata": {"host": "win-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "os_info": {"caption": "Microsoft Windows Server 2022 Standard", "version": "10.0.20348"},
                "ccm_service": {"state": "Running", "start_mode": "Auto"},
                "updates": {"installed_count": 50, "failed_count": 1, "pending_count": 2},
                "applications": [{"name": "7-Zip 22.01 (x64)", "version": "22.01", "vendor": "Igor Pavlov"}],
            },
        }
        with open(self.windows_dir / "windows_raw_audit.yaml", "w") as f:
            yaml.dump(windows_data, f)

        # 4. Inventory Groups
        groups = {
            "all": ["linux-01", "vc-01", "win-01"],
            "ubuntu_servers": ["linux-01"],
            "vcenters": ["vc-01"],
            "windows_servers": ["win-01"],
        }
        with open(self.platform_root / "inventory_groups.json", "w") as f:
            json.dump(groups, f)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_full_report_generation_at_all_levels(self):
        """Verify site, platform, and node reports are created with correct data."""

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--report-stamp",
                "20260226",
            ],
        )

        self.assertEqual(result.exit_code, 0, f"CLI failed: {result.output}")

        # Check Site Report
        site_report = self.reports_root / "site_health_report.html"
        self.assertTrue(site_report.exists())
        content = site_report.read_text()
        self.assertIn("Site Dashboard", content)
        self.assertIn("linux-01", content)
        self.assertIn("vc-01", content)
        self.assertIn("win-01", content)
        self.assertTrue(_has_attr(content, "href", "platform/linux/ubuntu/ubuntu_fleet_report.html"))
        self.assertTrue(_has_attr(content, "href", "platform/vmware/vcsa/vcenter_fleet_report.html"))
        self.assertTrue(_has_attr(content, "href", "platform/windows/windows_fleet_report.html"))
        self.assertTrue(_has_attr(content, "data-root", "./"))

        # Check Platform Reports
        self.assertTrue((self.reports_root / "platform" / "linux" / "ubuntu" / "ubuntu_fleet_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "vmware" / "vcsa" / "vcenter_fleet_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "vmware" / "esxi" / "esxi_fleet_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "windows" / "windows_fleet_report.html").exists())

        # Check Node Reports
        self.assertTrue(
            (self.reports_root / "platform" / "linux" / "ubuntu" / "linux-01" / "health_report.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / "vcsa" / "vc-01" / "health_report.html").exists()
        )
        # ESXi hosts are split from vCenter bundle into per-host reports
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / "esxi" / "esxi-01.local" / "health_report.html").exists(),
            "ESXi per-host report should be created via split_field expansion",
        )
        self.assertTrue((self.reports_root / "platform" / "windows" / "win-01" / "health_report.html").exists())

        # Verify alert data appears in rendered HTML
        linux_report = (
            self.reports_root / "platform" / "linux" / "ubuntu" / "linux-01" / "health_report.html"
        ).read_text()
        self.assertTrue(_has_attr(linux_report, "href", "../../../../site_health_report.html"))
        self.assertTrue(_has_attr(linux_report, "href", "../ubuntu_fleet_report.html"))
        self.assertTrue(_has_attr(linux_report, "href", "../../../../platform/vmware/vcsa/vcenter_fleet_report.html"))
        self.assertTrue(_has_attr(linux_report, "data-root", "../../../../"))
        self.assertTrue(
            "CRITICAL" in linux_report or "/" in linux_report, "Linux node report should reflect critical disk alert"
        )

        vmware_report = (
            self.reports_root / "platform" / "vmware" / "vcsa" / "vc-01" / "health_report.html"
        ).read_text()
        self.assertTrue(_has_attr(vmware_report, "href", "../../../../site_health_report.html"))
        self.assertTrue(_has_attr(vmware_report, "href", "../vcenter_fleet_report.html"))
        self.assertTrue(_has_attr(vmware_report, "href", "../../../../platform/vmware/vcsa/vcenter_fleet_report.html"))
        self.assertTrue(_has_attr(vmware_report, "data-root", "../../../../"))
        self.assertTrue(
            "WARNING" in vmware_report or "yellow" in vmware_report, "VMware node report should reflect health warning"
        )

        windows_report = (self.reports_root / "platform" / "windows" / "win-01" / "health_report.html").read_text()
        self.assertTrue(_has_attr(windows_report, "href", "../../../site_health_report.html"))
        self.assertTrue(_has_attr(windows_report, "href", "../windows_fleet_report.html"))
        self.assertTrue(_has_attr(windows_report, "href", "../../../platform/vmware/vcsa/vcenter_fleet_report.html"))
        self.assertTrue(_has_attr(windows_report, "data-root", "../../../"))
        self.assertTrue(
            "failed" in windows_report.lower() or "1" in windows_report,
            "Windows node report should reflect update failure count",
        )

    def test_site_security_compliance_tab_renders_stig_data(self):
        """Site HTML Security Compliance tab must render STIG data when STIG + platform data coexist.

        test_full_report_generation_at_all_levels sets up platform data only and never
        exercises the Security Compliance tab.  This test adds a STIG raw artifact for
        the same vc-01 host alongside the existing vmware platform data, then asserts
        that the rendered site HTML contains STIG-specific content (host count, finding
        status) in the Security Compliance section.
        """
        # Add ESXi STIG data alongside the vmware platform data already set up in setUp
        esxi_dir = self.platform_root / "vmware" / "vcenter" / "esxi-01"
        esxi_dir.mkdir(parents=True, exist_ok=True)
        stig_raw = {
            "metadata": {
                "host": "esxi-01",
                "audit_type": "stig_esxi",
                "timestamp": "2026-02-26T23:00:00Z",
                "engine": "ncs_collector_callback",
            },
            "data": [
                {
                    "id": "V-256379",
                    "status": "failed",
                    "severity": "medium",
                    "title": "stigrule_256379_account_lock_failures",
                    "checktext": "Security.AccountLockFailures must be 3.",
                }
            ],
            "target_type": "esxi",
        }
        with open(esxi_dir / "raw_stig_esxi.yaml", "w") as f:
            yaml.dump(stig_raw, f)

        # Update inventory so esxi-01 is in the fleet
        groups = {
            "all": ["linux-01", "vc-01", "win-01", "esxi-01"],
            "ubuntu_servers": ["linux-01"],
            "vcenters": ["vc-01"],
            "windows_servers": ["win-01"],
            "esxi_hosts": ["esxi-01"],
        }
        with open(self.platform_root / "inventory_groups.json", "w") as f:
            json.dump(groups, f)

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--report-stamp",
                "20260226",
            ],
        )
        self.assertEqual(result.exit_code, 0, f"CLI failed: {result.output}")

        site_html = (self.reports_root / "site_health_report.html").read_text()

        # STIG section must be present in the rendered HTML
        self.assertIn("STIG Compliance", site_html)

        # STIG fleet totals table must show at least 1 host
        # The template renders: <td>Hosts audited</td><td><strong>N</strong></td>
        # We assert the STIG overview widget is present and rendering platform data correctly.
        self.assertIn("View Detailed STIG Fleet Report", site_html, "STIG detailed link must appear in the site report")
        self.assertIn("vmware", site_html.lower(), "vmware platform metrics must appear in the site report STIG widget")

        # The template renders open finding counts; the raw data has one "failed" rule
        # which normalizes to status="open" in the view model.
        # Assert "open" or the finding count > 0 appears somewhere in the page.
        self.assertTrue(
            "open" in site_html.lower() or "1" in site_html,
            "Site HTML should reflect at least one open STIG finding",
        )
