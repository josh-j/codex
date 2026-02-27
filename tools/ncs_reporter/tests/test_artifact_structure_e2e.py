"""E2E tests verifying artifact directory structure and hostname collision isolation.

Two platforms can have a host named identically (e.g. "server-01" as both a Linux
node and a VMware vCenter). This test verifies:

  1. Data files from each platform are kept in separate platform directories and
     never overwrite each other.
  2. Generated reports are scoped under reports/platform/<platform>/<hostname>/
     so same-named hosts on different platforms produce distinct output files.
  3. The exact expected directory tree is created — site, fleet, node, STIG,
     CKLB, and stamped copies — with no gaps or cross-platform collisions.
"""

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import main

STAMP = "20260226"


def _linux_raw(host: str) -> dict:
    # Disk at 90% used (10% free) — crosses the 80% warning threshold so this
    # host generates an alert that surfaces in the site report's Global Alert Queue.
    size_total = 107374182400
    size_available = int(size_total * 0.10)
    return {
        "metadata": {"host": host, "timestamp": "2026-02-26T23:00:00Z"},
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
                        "size_total": size_total,
                        "size_available": size_available,
                    }
                ],
                "date_time": {"epoch": "1740610800"},
            }
        },
    }


def _vmware_raw(host: str) -> dict:
    return {
        "metadata": {"host": host, "timestamp": "2026-02-26T23:00:00Z"},
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
                        "overall": "green",
                        "cpu": "green",
                        "memory": "green",
                        "database": "green",
                        "storage": "green",
                        "swap": "green",
                    },
                    "access": {"ssh": False},
                    "backup": {"enabled": True, "status": "SUCCEEDED"},
                }
            },
            "datacenters_info": {"value": [{"name": "DC1", "datacenter": "datacenter-1"}]},
            "clusters_info": {"results": []},
            "datastores_info": {"datastores": []},
            "vms_info": {"virtual_machines": []},
            "snapshots_info": {"snapshots": []},
            "alarms_info": {"alarms": []},
        },
    }


def _esxi_stig_raw(host: str, status: str = "failed") -> dict:
    return {
        "metadata": {
            "host": host,
            "audit_type": "stig_esxi",
            "timestamp": "2026-02-26T23:00:00Z",
            "engine": "ncs_collector_callback",
        },
        "data": [
            {
                "id": "V-256379",
                "status": status,
                "severity": "medium",
                "title": "stigrule_256379_account_lock_failures",
                "checktext": f"Security.AccountLockFailures must be 3. Status: {status}",
            }
        ],
        "target_type": "esxi",
    }


class TestArtifactDirectoryStructure(unittest.TestCase):
    """Verify the full output directory tree produced by `ncs-reporter all`."""

    def setUp(self):
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.platform_root = root / "platform"
        self.reports_root = root / "reports"

        # --- Ubuntu: linux-01 ---
        linux_dir = self.platform_root / "ubuntu" / "linux-01"
        linux_dir.mkdir(parents=True)
        (linux_dir / "raw_discovery.yaml").write_text(yaml.dump(_linux_raw("linux-01")))

        # --- VMware: vc-01 (with ESXi STIG data) ---
        vmware_dir = self.platform_root / "vmware" / "vc-01"
        vmware_dir.mkdir(parents=True)
        (vmware_dir / "raw_vcenter.yaml").write_text(yaml.dump(_vmware_raw("vc-01")))
        (vmware_dir / "raw_stig_esxi.yaml").write_text(yaml.dump(_esxi_stig_raw("vc-01")))

        # --- Inventory groups ---
        groups = {
            "all": ["linux-01", "vc-01"],
            "ubuntu_servers": ["linux-01"],
            "vcenters": ["vc-01"],
            "esxi_hosts": [],
        }
        groups_path = self.platform_root / "inventory_groups.json"
        groups_path.write_text(json.dumps(groups))
        self.groups_path = groups_path

    def tearDown(self):
        self.tmp.cleanup()

    def _run_all(self) -> str:
        result = self.runner.invoke(main, [
            "all",
            "--platform-root", str(self.platform_root),
            "--reports-root", str(self.reports_root),
            "--groups", str(self.groups_path),
            "--report-stamp", STAMP,
        ])
        self.assertEqual(result.exit_code, 0, f"CLI failed:\n{result.output}")
        return result.output

    def test_site_report_created(self):
        self._run_all()
        site = self.reports_root / "site_health_report.html"
        self.assertTrue(site.exists(), "site_health_report.html must exist at reports root")
        content = site.read_text()
        # linux-01 has a disk at 90% → warning alert → appears in Global Alert Queue
        self.assertIn("linux-01", content)
        # vc-01 has STIG data → appears in STIG compliance section
        self.assertIn("vc-01", content)

    def test_stamped_fleet_reports_but_site_report_is_not_stamped(self):
        """The `all` command writes the site report via open() directly (no stamp).
        Platform fleet reports go through write_report() and do get stamped copies."""
        self._run_all()
        # Site report: single file, no stamped copy (written directly by all_cmd)
        site = self.reports_root / "site_health_report.html"
        stamped_site = self.reports_root / f"site_health_report_{STAMP}.html"
        self.assertTrue(site.exists())
        self.assertFalse(stamped_site.exists(), "all_cmd writes site report without stamp")

    def test_platform_fleet_reports_created(self):
        self._run_all()
        self.assertTrue(
            (self.reports_root / "platform" / "ubuntu" / "ubuntu_health_report.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / "vmware_health_report.html").exists()
        )

    def test_stamped_fleet_reports_created(self):
        self._run_all()
        self.assertTrue(
            (self.reports_root / "platform" / "ubuntu" / f"ubuntu_health_report_{STAMP}.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / f"vmware_health_report_{STAMP}.html").exists()
        )

    def test_node_reports_under_platform_subdirectory(self):
        self._run_all()
        linux_node = self.reports_root / "platform" / "ubuntu" / "linux-01" / "health_report.html"
        vmware_node = self.reports_root / "platform" / "vmware" / "vc-01" / "health_report.html"
        self.assertTrue(linux_node.exists(), f"Linux node report not found: {linux_node}")
        self.assertTrue(vmware_node.exists(), f"VMware node report not found: {vmware_node}")

    def test_stig_fleet_report_at_reports_root(self):
        self._run_all()
        fleet = self.reports_root / "stig_fleet_report.html"
        self.assertTrue(fleet.exists(), "STIG fleet report must be at reports root")

    def test_stig_host_report_under_platform_vmware(self):
        self._run_all()
        host_report = self.reports_root / "platform" / "vmware" / "vc-01" / "vc-01_stig_esxi.html"
        self.assertTrue(host_report.exists(), f"STIG host report not found: {host_report}")
        content = host_report.read_text()
        self.assertIn("vc-01", content)

    def test_cklb_artifact_under_cklb_directory(self):
        self._run_all()
        cklb = self.reports_root / "cklb" / "vc-01_esxi.cklb"
        self.assertTrue(cklb.exists(), f"CKLB artifact not found: {cklb}")
        data = json.loads(cklb.read_text())
        self.assertEqual(data["target_data"]["host_name"], "vc-01")

    def test_platform_state_files_created(self):
        self._run_all()
        self.assertTrue((self.platform_root / "ubuntu" / "linux_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "vmware" / "vmware_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "all_hosts_state.yaml").exists())

    def test_no_windows_directories_created_when_no_windows_data(self):
        self._run_all()
        self.assertFalse((self.reports_root / "platform" / "windows").exists())
        self.assertFalse((self.platform_root / "windows").exists())


class TestHostnameCollisionIsolation(unittest.TestCase):
    """Verify that a Linux host and a VMware host sharing the same hostname
    produce fully isolated artifacts — no file overwrites, no data leakage."""

    SHARED_HOSTNAME = "server-01"

    def setUp(self):
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.platform_root = root / "platform"
        self.reports_root = root / "reports"

        # Same hostname on both Ubuntu and VMware
        linux_dir = self.platform_root / "ubuntu" / self.SHARED_HOSTNAME
        linux_dir.mkdir(parents=True)
        (linux_dir / "raw_discovery.yaml").write_text(
            yaml.dump(_linux_raw(self.SHARED_HOSTNAME))
        )

        vmware_dir = self.platform_root / "vmware" / self.SHARED_HOSTNAME
        vmware_dir.mkdir(parents=True)
        (vmware_dir / "raw_vcenter.yaml").write_text(
            yaml.dump(_vmware_raw(self.SHARED_HOSTNAME))
        )
        (vmware_dir / "raw_stig_esxi.yaml").write_text(
            yaml.dump(_esxi_stig_raw(self.SHARED_HOSTNAME))
        )

        groups = {
            "all": [self.SHARED_HOSTNAME],
            "ubuntu_servers": [self.SHARED_HOSTNAME],
            "vcenters": [self.SHARED_HOSTNAME],
            "esxi_hosts": [],
        }
        groups_path = self.platform_root / "inventory_groups.json"
        groups_path.write_text(json.dumps(groups))
        self.groups_path = groups_path

    def tearDown(self):
        self.tmp.cleanup()

    def _run_all(self) -> None:
        result = self.runner.invoke(main, [
            "all",
            "--platform-root", str(self.platform_root),
            "--reports-root", str(self.reports_root),
            "--groups", str(self.groups_path),
            "--report-stamp", STAMP,
        ])
        self.assertEqual(result.exit_code, 0, f"CLI failed:\n{result.output}")

    def test_data_files_in_separate_platform_directories(self):
        """Raw data files under ubuntu/ and vmware/ never share a directory."""
        linux_data = self.platform_root / "ubuntu" / self.SHARED_HOSTNAME / "raw_discovery.yaml"
        vmware_data = self.platform_root / "vmware" / self.SHARED_HOSTNAME / "raw_vcenter.yaml"
        # Both exist before running — they live in separate paths
        self.assertTrue(linux_data.exists())
        self.assertTrue(vmware_data.exists())
        self.assertNotEqual(linux_data.parent, vmware_data.parent)

    def test_node_reports_do_not_collide(self):
        """Node reports for the same hostname land in separate platform trees."""
        self._run_all()
        linux_report = (
            self.reports_root / "platform" / "ubuntu" / self.SHARED_HOSTNAME / "health_report.html"
        )
        vmware_report = (
            self.reports_root / "platform" / "vmware" / self.SHARED_HOSTNAME / "health_report.html"
        )
        self.assertTrue(linux_report.exists(), f"Linux node report missing: {linux_report}")
        self.assertTrue(vmware_report.exists(), f"VMware node report missing: {vmware_report}")
        self.assertNotEqual(linux_report, vmware_report)

    def test_node_report_content_is_platform_specific(self):
        """The Linux report contains Linux-specific content; VMware report contains
        VMware-specific content — they are not the same file."""
        self._run_all()
        linux_content = (
            self.reports_root / "platform" / "ubuntu" / self.SHARED_HOSTNAME / "health_report.html"
        ).read_text()
        vmware_content = (
            self.reports_root / "platform" / "vmware" / self.SHARED_HOSTNAME / "health_report.html"
        ).read_text()
        # The two files must differ — same hostname but different platform data
        self.assertNotEqual(linux_content, vmware_content)
        # Linux report should reference filesystem/disk concepts
        self.assertTrue(
            any(term in linux_content for term in ["Ubuntu", "disk", "mount", "ext4", "/"]),
            "Linux node report should contain Linux-specific content"
        )
        # VMware report should reference vCenter/appliance concepts
        self.assertTrue(
            any(term in vmware_content for term in ["vCenter", "VMware", "datacenter", "Datacenter", "appliance"]),
            "VMware node report should contain VMware-specific content"
        )

    def test_state_files_are_platform_scoped(self):
        """Each platform writes its own state file; same-named hosts in different
        platforms do not clobber each other's state."""
        self._run_all()
        linux_state_path = self.platform_root / "ubuntu" / "linux_fleet_state.yaml"
        vmware_state_path = self.platform_root / "vmware" / "vmware_fleet_state.yaml"
        self.assertTrue(linux_state_path.exists())
        self.assertTrue(vmware_state_path.exists())

        with open(linux_state_path) as f:
            linux_state = yaml.safe_load(f)
        with open(vmware_state_path) as f:
            vmware_state = yaml.safe_load(f)

        # Both contain the shared hostname
        self.assertIn(self.SHARED_HOSTNAME, linux_state["hosts"])
        self.assertIn(self.SHARED_HOSTNAME, vmware_state["hosts"])

        # But their content is different — one has Linux keys, one has VMware keys
        linux_host = linux_state["hosts"][self.SHARED_HOSTNAME]
        vmware_host = vmware_state["hosts"][self.SHARED_HOSTNAME]
        self.assertNotEqual(linux_host, vmware_host)

    def test_stig_host_report_scoped_to_vmware_platform(self):
        """STIG reports for ESXi land under platform/vmware/, not platform/ubuntu/."""
        self._run_all()
        stig_report = (
            self.reports_root
            / "platform" / "vmware"
            / self.SHARED_HOSTNAME
            / f"{self.SHARED_HOSTNAME}_stig_esxi.html"
        )
        wrong_path = (
            self.reports_root
            / "platform" / "ubuntu"
            / self.SHARED_HOSTNAME
            / f"{self.SHARED_HOSTNAME}_stig_esxi.html"
        )
        self.assertTrue(stig_report.exists(), f"STIG report missing at expected path: {stig_report}")
        self.assertFalse(wrong_path.exists(), "STIG report must not appear under ubuntu platform")

    def test_cklb_artifact_uses_hostname_only_no_platform_ambiguity(self):
        """CKLB is keyed by hostname+target_type, not platform, so it is unambiguous."""
        self._run_all()
        cklb_path = self.reports_root / "cklb" / f"{self.SHARED_HOSTNAME}_esxi.cklb"
        self.assertTrue(cklb_path.exists(), f"CKLB not found: {cklb_path}")
        data = json.loads(cklb_path.read_text())
        self.assertEqual(data["target_data"]["host_name"], self.SHARED_HOSTNAME)
