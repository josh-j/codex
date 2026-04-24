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
    #
    # Matches the flat payload that discover.yaml's set_fact produces — individual
    # fields are extracted from ansible_facts by the Ansible task, NOT nested.
    size_total = 107374182400
    size_available = int(size_total * 0.10)
    return {
        "metadata": {"host": host, "timestamp": "2026-02-26T23:00:00Z"},
        "data": {
            "hostname": host,
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
                    "size_total": size_total,
                    "size_available": size_available,
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


def _vmware_raw(host: str) -> dict:
    return {
        "metadata": {"host": host, "timestamp": "2026-02-26T23:00:00Z"},
        "data": {
            "appliance_version": "8.0.2",
            "appliance_build": "23319199",
            "appliance_uptime_seconds": 864000,
            "appliance_health_overall": "green",
            "appliance_health_cpu": "green",
            "appliance_health_memory": "green",
            "appliance_health_database": "green",
            "appliance_health_storage": "green",
            "ssh_enabled": True,  # Triggers ssh_enabled alert → host appears in site alert queue
            "shell_enabled": False,
            "ntp_mode": "NTP",
            "backup_schedules": [{"enabled": True, "status": "SUCCEEDED"}],
            "backup_schedule_count": 1,
            "active_alarms": [],
            "alarm_count": 0,
            "vcenter_count": 1,
            "datacenter_count": 1,
            "cluster_count": 0,
            "esxi_host_count": 0,
            "datastore_count": 0,
            "clusters": [],
            "datastores": [],
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
                "name": "stigrule_256379_account_lock_failures",
                "checktext": f"Security.AccountLockFailures must be 3. Status: {status}",
            }
        ],
        "target_type": "esxi",
    }


@unittest.skip("legacy platform/<p>/<schema>_inventory.html + platform/<p>/<host>/<host>.html output no longer generated; see tree layout assertions in test_tree_layout_e2e.py")
class TestArtifactDirectoryStructure(unittest.TestCase):
    """Verify the full output directory tree produced by `ncs-reporter all`."""

    def setUp(self):
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)

        self.platform_root = root / "platform"
        self.reports_root = root / "reports"

        # --- Ubuntu: linux-01 ---
        linux_dir = self.platform_root / "linux" / "ubuntu" / "linux-01"
        linux_dir.mkdir(parents=True)
        (linux_dir / "raw_ubuntu.yaml").write_text(yaml.dump(_linux_raw("linux-01")))

        # --- VMware: vc-01 (with ESXi STIG data) ---
        vmware_dir = self.platform_root / "vmware" / "vcsa" / "vc-01"
        vmware_dir.mkdir(parents=True)
        (vmware_dir / "raw_vcsa.yaml").write_text(yaml.dump(_vmware_raw("vc-01")))
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

    def tearDown(self):
        self.tmp.cleanup()

    def _run_all(self) -> str:
        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--report-stamp",
                STAMP,
            ],
        )
        self.assertEqual(result.exit_code, 0, f"CLI failed:\n{result.output}")
        return result.output

    def test_site_report_created(self):
        self._run_all()
        site = self.reports_root / "site.html"
        self.assertTrue(site.exists(), "site.html must exist at reports root")
        content = site.read_text()
        # linux-01 has a disk at 90% → warning alert → appears in Global Alert Queue
        self.assertIn("linux-01", content)
        # vc-01 has SSH enabled → ssh_enabled alert → appears in Global Alert Queue
        self.assertIn("vc-01", content)

    def test_stamped_fleet_reports_but_site_report_is_not_stamped(self):
        """The `all` command writes the site report via open() directly (no stamp).
        Platform fleet reports go through write_report() and do get stamped copies."""
        self._run_all()
        # Site report: single file, no stamped copy (written directly by all_cmd)
        site = self.reports_root / "site.html"
        stamped_site = self.reports_root / f"site_{STAMP}.html"
        self.assertTrue(site.exists())
        self.assertFalse(stamped_site.exists(), "all_cmd writes site report without stamp")

    def test_platform_fleet_reports_created(self):
        self._run_all()
        self.assertTrue((self.reports_root / "platform" / "linux" / "ubuntu" / "ubuntu_inventory.html").exists())
        self.assertTrue((self.reports_root / "platform" / "vmware" / "vcsa" / "vcsa_inventory.html").exists())

    def test_stamped_fleet_reports_created(self):
        self._run_all()
        self.assertTrue(
            (self.reports_root / "platform" / "linux" / "ubuntu" / f"ubuntu_inventory_{STAMP}.html").exists()
        )
        self.assertTrue(
            (self.reports_root / "platform" / "vmware" / "vcsa" / f"vcsa_inventory_{STAMP}.html").exists()
        )

    def test_node_reports_under_platform_subdirectory(self):
        self._run_all()
        linux_node = self.reports_root / "platform" / "linux" / "ubuntu" / "linux-01" / "linux-01.html"
        vmware_node = self.reports_root / "platform" / "vmware" / "vcsa" / "vc-01" / "vc-01.html"
        self.assertTrue(linux_node.exists(), f"Linux node report not found: {linux_node}")
        self.assertTrue(vmware_node.exists(), f"VMware VCSA node report not found: {vmware_node}")

    def test_stig_inventory_at_reports_root(self):
        self._run_all()
        fleet = self.reports_root / "site.stig.html"
        self.assertTrue(fleet.exists(), "STIG fleet report must be at reports root")

    def test_stig_host_report_under_platform_vmware(self):
        self._run_all()
        host_report = self.reports_root / "platform" / "vmware" / "esxi" / "vc-01" / "vc-01_stig_esxi.html"
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
        self.assertTrue((self.platform_root / "linux" / "ubuntu" / "linux_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "vmware" / "vcsa" / "vmware_fleet_state.yaml").exists())
        self.assertTrue((self.platform_root / "all_hosts_state.yaml").exists())

    def test_no_windows_directories_created_when_no_windows_data(self):
        self._run_all()
        self.assertFalse((self.reports_root / "platform" / "windows").exists())
        self.assertFalse((self.platform_root / "windows").exists())


@unittest.skip("legacy platform/<p>/<schema>_inventory.html + platform/<p>/<host>/<host>.html output no longer generated; see tree layout assertions in test_tree_layout_e2e.py")
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
        linux_dir = self.platform_root / "linux" / "ubuntu" / self.SHARED_HOSTNAME
        linux_dir.mkdir(parents=True)
        (linux_dir / "raw_ubuntu.yaml").write_text(yaml.dump(_linux_raw(self.SHARED_HOSTNAME)))

        vmware_dir = self.platform_root / "vmware" / "vcsa" / self.SHARED_HOSTNAME
        vmware_dir.mkdir(parents=True)
        (vmware_dir / "raw_vcsa.yaml").write_text(yaml.dump(_vmware_raw(self.SHARED_HOSTNAME)))
        (vmware_dir / "raw_stig_esxi.yaml").write_text(yaml.dump(_esxi_stig_raw(self.SHARED_HOSTNAME)))

        groups = {
            "all": [self.SHARED_HOSTNAME],
            "ubuntu_servers": [self.SHARED_HOSTNAME],
            "vcenters": [self.SHARED_HOSTNAME],
            "esxi_hosts": [],
        }
        groups_path = self.platform_root / "inventory_groups.json"
        groups_path.write_text(json.dumps(groups))

    def tearDown(self):
        self.tmp.cleanup()

    def _run_all(self) -> None:
        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--report-stamp",
                STAMP,
            ],
        )
        self.assertEqual(result.exit_code, 0, f"CLI failed:\n{result.output}")

    def test_data_files_in_separate_platform_directories(self):
        """Raw data files under linux/ubuntu/ and vmware/vcsa/ never share a directory."""
        linux_data = self.platform_root / "linux" / "ubuntu" / self.SHARED_HOSTNAME / "raw_ubuntu.yaml"
        vmware_data = self.platform_root / "vmware" / "vcsa" / self.SHARED_HOSTNAME / "raw_vcsa.yaml"
        # Both exist before running — they live in separate paths
        self.assertTrue(linux_data.exists())
        self.assertTrue(vmware_data.exists())
        self.assertNotEqual(linux_data.parent, vmware_data.parent)

    def test_node_reports_do_not_collide(self):
        """Node reports for the same hostname land in separate platform trees."""
        self._run_all()
        linux_report = self.reports_root / "platform" / "linux" / "ubuntu" / self.SHARED_HOSTNAME / f"{self.SHARED_HOSTNAME}.html"
        vmware_report = (
            self.reports_root / "platform" / "vmware" / "vcsa" / self.SHARED_HOSTNAME / f"{self.SHARED_HOSTNAME}.html"
        )
        self.assertTrue(linux_report.exists(), f"Linux node report missing: {linux_report}")
        self.assertTrue(vmware_report.exists(), f"VMware node report missing: {vmware_report}")
        self.assertNotEqual(linux_report, vmware_report)

    def test_node_report_content_is_platform_specific(self):
        """The Linux report contains Linux-specific content; VMware report contains
        VMware-specific content — they are not the same file."""
        self._run_all()
        linux_content = (
            self.reports_root / "platform" / "linux" / "ubuntu" / self.SHARED_HOSTNAME / f"{self.SHARED_HOSTNAME}.html"
        ).read_text()
        vmware_content = (
            self.reports_root / "platform" / "vmware" / "vcsa" / self.SHARED_HOSTNAME / f"{self.SHARED_HOSTNAME}.html"
        ).read_text()
        # The two files must differ — same hostname but different platform data
        self.assertNotEqual(linux_content, vmware_content)
        # Linux report should reference filesystem/disk concepts
        self.assertTrue(
            any(term in linux_content for term in ["Ubuntu", "disk", "mount", "ext4", "/"]),
            "Linux node report should contain Linux-specific content",
        )
        # VMware report should reference vCenter/appliance concepts
        self.assertTrue(
            any(term in vmware_content for term in ["vCenter", "VMware", "datacenter", "Datacenter", "appliance"]),
            "VMware node report should contain VMware-specific content",
        )

    def test_state_files_are_platform_scoped(self):
        """Each platform writes its own state file; same-named hosts in different
        platforms do not clobber each other's state."""
        self._run_all()
        linux_state_path = self.platform_root / "linux" / "ubuntu" / "linux_fleet_state.yaml"
        vmware_state_path = self.platform_root / "vmware" / "vcsa" / "vmware_fleet_state.yaml"
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
        """STIG reports for ESXi land under platform/vmware/esxi/, not platform/linux/ubuntu/."""
        self._run_all()
        stig_report = (
            self.reports_root
            / "platform"
            / "vmware"
            / "esxi"
            / self.SHARED_HOSTNAME
            / f"{self.SHARED_HOSTNAME}_stig_esxi.html"
        )
        wrong_path = (
            self.reports_root
            / "platform"
            / "linux"
            / "ubuntu"
            / self.SHARED_HOSTNAME
            / f"{self.SHARED_HOSTNAME}_stig_esxi.html"
        )
        self.assertTrue(stig_report.exists(), f"STIG report missing at expected path: {stig_report}")
        self.assertFalse(wrong_path.exists(), "STIG report must not appear under linux/ubuntu platform")

    def test_cklb_artifact_uses_hostname_only_no_platform_ambiguity(self):
        """CKLB output is a flat directory — hostname+target_type is unambiguous without nesting."""
        self._run_all()
        cklb_path = self.reports_root / "cklb" / f"{self.SHARED_HOSTNAME}_esxi.cklb"
        self.assertTrue(cklb_path.exists(), f"CKLB not found: {cklb_path}")
        data = json.loads(cklb_path.read_text())
        self.assertEqual(data["target_data"]["host_name"], self.SHARED_HOSTNAME)
