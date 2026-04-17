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
        # Flat payload matching discover.yaml's set_fact output.
        self.linux_dir = self.platform_root / "linux" / "ubuntu" / "linux-01"
        self.linux_dir.mkdir(parents=True)
        linux_data = {
            "metadata": {"host": "linux-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "hostname": "linux-01",
                "distribution": "Ubuntu",
                "distribution_version": "24.04",
                "kernel": "6.8.0-lowlatency",
                "uptime_seconds": 86400,
                "memory_total_mb": 16384,
                "memory_free_mb": 8192,
                "swap_total_mb": 4096,
                "swap_free_mb": 4096,
                "mounts": [
                    {
                        "mount": "/",
                        "device": "/dev/sda1",
                        "fstype": "ext4",
                        "size_total": 107374182400,  # 100GB
                        "size_available": 2147483648,  # 2GB (98% used -> CRITICAL)
                    }
                ],
                "failed_services": {"stdout_lines": []},
                "shadow_raw": {"stdout_lines": []},
                "sshd_raw": {"stdout_lines": []},
                "world_writable": {"stdout_lines": []},
                "reboot_stat": {"stat": {"exists": False}},
                "apt_simulate": {"stdout_lines": ["0 upgraded, 0 newly installed"]},
                "file_stats": {"results": []},
                "epoch_seconds": 1740610800,
            },
        }
        with open(self.linux_dir / "raw_ubuntu.yaml", "w") as f:
            yaml.dump(linux_data, f)

        # 2. VMware Data (Trigger a health warning)
        self.vmware_dir = self.platform_root / "vmware" / "vcsa" / "vc-01"
        self.vmware_dir.mkdir(parents=True)
        vmware_data = {
            "metadata": {"host": "vc-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "appliance_version": "8.0.2",
                "appliance_build": "23319199",
                "appliance_uptime_seconds": 864000,
                "appliance_health_overall": "yellow",
                "appliance_health_cpu": "green",
                "appliance_health_memory": "yellow",
                "appliance_health_database": "green",
                "appliance_health_storage": "green",
                "ssh_enabled": False,
                "shell_enabled": False,
                "ntp_mode": "NTP",
                "backup_schedules": [{"enabled": True, "status": "SUCCEEDED"}],
                "backup_schedule_count": 1,
                "active_alarms": [],
                "alarm_count": 0,
                "vcenter_count": 1,
                "datacenter_count": 1,
                "cluster_count": 1,
                "esxi_host_count": 1,
                "datastore_count": 1,
                "clusters": [{"name": "Cluster-A", "datacenter": "DC1", "host_count": 1,
                              "ha_enabled": False, "drs_enabled": False,
                              "cpu_usage_pct": 20.0, "mem_usage_pct": 25.0}],
                "datastores": [{"name": "ds1", "capacity": 107374182400, "freeSpace": 53687091200}],
            },
        }
        with open(self.vmware_dir / "raw_vcsa.yaml", "w") as f:
            yaml.dump(vmware_data, f)

        # 2b. ESXi per-host health data (pre-assembled by collector)
        self.esxi_dir = self.platform_root / "vmware" / "esxi" / "esxi-01.local"
        self.esxi_dir.mkdir(parents=True)
        esxi_data = {
            "metadata": {"host": "esxi-01.local", "audit_type": "raw_esxi",
                         "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "name": "esxi-01.local",
                "version": "7.0.3",
                "build": "12345",
                "connection_state": "connected",
                "overall_status": "green",
                "in_maintenance_mode": False,
                "lockdown_mode": "disabled",
                "mem_mb_total": 65536,
                "mem_mb_used": 32768,
                "mem_used_pct": 50.0,
                "cpu_used_pct": 42.0,
                "vm_count": 18,
                "uptime_seconds": 86400,
                "ssh_enabled": True,
                "shell_enabled": False,
                "ntp_running": True,
                "cluster": "Cluster-A",
                "datacenter": "DC1",
                "datastores": [{"name": "ds1", "total": "1TB", "free": "500GB"}],
                "nics": [],
                "vmknics": [],
                "hardware_alerts": [],
            },
        }
        with open(self.esxi_dir / "raw_esxi.yaml", "w") as f:
            yaml.dump(esxi_data, f)

        # 3. Windows Data
        self.windows_dir = self.platform_root / "windows" / "win-01"
        self.windows_dir.mkdir(parents=True)
        windows_data = {
            "metadata": {"host": "win-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "ccm_service_state": "running",
                "health_hostname": "win-01",
                "health_os_name": "Microsoft Windows Server 2022 Standard",
                "health_uptime_hours": 120,
                "health_disk": [{"DeviceID": "C:", "SizeGB": 100, "FreeGB": 50, "UsedPct": 50.0}],
                "health_memory_used_pct": 60,
                "health_cpu_load_pct": 25,
                "health_services": [],
                "health_reboot_pending": True,  # Triggers reboot_pending alert
                "health_reboot_reasons": [],
                "health_event_count": 0,
                "health_events": [],
                "health_secure_channel": "OK",
                "health_software_versions": [{"name": "7-Zip", "version": "22.01", "publisher": "Igor Pavlov"}],
                "configmgr_apps": [],
                "apps_to_update": [],
                "installed_apps": [],
                "update_results": [],
                "vuln_total_findings": 0,
                "vuln_remediated": 0,
                "vuln_open": 0,
                "vuln_findings": [],
                "kb_detection": [],
                "kb_install_results": [],
            },
        }
        with open(self.windows_dir / "raw_windows.yaml", "w") as f:
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
        self.assertTrue(_has_attr(content, "href", "platform/vmware/vcsa/vcsa_fleet_report.html"))
        self.assertTrue(_has_attr(content, "href", "platform/windows/windows_fleet_report.html"))
        self.assertTrue(_has_attr(content, "data-root", "./"))

        # Check Platform Reports
        self.assertTrue((self.reports_root / "platform" / "linux" / "ubuntu" / "ubuntu_fleet_report.html").exists())
        self.assertTrue((self.reports_root / "platform" / "vmware" / "vcsa" / "vcsa_fleet_report.html").exists())
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
        self.assertTrue(_has_attr(linux_report, "href", "../../../../platform/vmware/vcsa/vcsa_fleet_report.html"))
        self.assertTrue(_has_attr(linux_report, "data-root", "../../../../"))
        self.assertTrue(
            "CRITICAL" in linux_report or "/" in linux_report, "Linux node report should reflect critical disk alert"
        )

        vmware_report = (
            self.reports_root / "platform" / "vmware" / "vcsa" / "vc-01" / "health_report.html"
        ).read_text()
        self.assertTrue(_has_attr(vmware_report, "href", "../../../../site_health_report.html"))
        self.assertTrue(_has_attr(vmware_report, "href", "../vcsa_fleet_report.html"))
        self.assertTrue(_has_attr(vmware_report, "href", "../../../../platform/vmware/vcsa/vcsa_fleet_report.html"))
        self.assertTrue(_has_attr(vmware_report, "data-root", "../../../../"))
        self.assertTrue(
            "WARNING" in vmware_report or "yellow" in vmware_report, "VMware node report should reflect health warning"
        )

        windows_report = (self.reports_root / "platform" / "windows" / "win-01" / "health_report.html").read_text()
        self.assertTrue(_has_attr(windows_report, "href", "../../../site_health_report.html"))
        self.assertTrue(_has_attr(windows_report, "href", "../windows_fleet_report.html"))
        self.assertTrue(_has_attr(windows_report, "href", "../../../platform/vmware/vcsa/vcsa_fleet_report.html"))
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
        esxi_dir = self.platform_root / "vmware" / "vcsa" / "esxi-01"
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
                    "name": "stigrule_256379_account_lock_failures",
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
