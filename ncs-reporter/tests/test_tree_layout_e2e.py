"""End-to-end: ``ncs-reporter all`` emits the hierarchical inventory tree.

Exercises the full CLI with a synthetic fleet and asserts the generated
directory shape matches the single naming rule (``<node>/<slug>.html``,
``raw.yaml``, ``<slug>.stig.html`` etc.), independent of the legacy
``platform/<report_dir>/…`` output.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import main


class TestTreeLayoutE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.platform_root = self.root / "platform"
        self.reports_root = self.root / "reports"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_bundle(self, rel: str, data: dict) -> None:
        path = self.platform_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data))

    def test_vsphere_tree_emitted_at_expected_paths(self) -> None:
        self._write_bundle("vmware/vcsa/vc-lab/raw_vcsa.yaml", {
            "metadata": {"host": "vc-lab", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "appliance_version": "7.0.3",
                "appliance_build": "12345",
                "appliance_health_overall": "green",
                "appliance_health_cpu": "green",
                "appliance_health_memory": "green",
                "appliance_health_database": "green",
                "appliance_health_storage": "green",
                "ssh_enabled": 0.0, "shell_enabled": 0.0, "ntp_mode": "NTP",
                "appliance_uptime_seconds": 86400, "backup_schedule_count": 1,
                "alarm_count": 0, "active_alarms": [],
                "extension_count": 0, "content_library_count": 0, "tag_category_count": 0,
                "datacenter_count": 1, "cluster_count": 1, "esxi_host_count": 1,
                "datastore_count": 0, "dvswitch_count": 0, "resource_pool_count": 0, "license_count": 0,
                "clusters": {
                    "CL-Prod": {
                        "name": "CL-Prod",
                        "datacenter": "DC-East",
                        "ha_enabled": True, "drs_enabled": True,
                        "host_count": 1,
                        "cpu_usage_pct": 10.0, "mem_usage_pct": 20.0,
                    },
                },
                "datastores": [
                    {"name": "ds-1", "datacenter": "DC-East",
                     "capacity_gb": 100, "free_gb": 50, "used_pct": 50},
                ],
                "dvswitches": [],
            },
        })

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root", str(self.platform_root),
                "--reports-root", str(self.reports_root),
                "--report-stamp", "20260226",
            ],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, result.output)

        # Every tier must produce <dir>/<slug>.html — no hardcoded filenames.
        expected = [
            Path("vsphere/vsphere.html"),
            Path("vsphere/vc-lab/vc-lab.html"),
            Path("vsphere/vc-lab/dc-east/dc-east.html"),
            Path("vsphere/vc-lab/dc-east/cl-prod/cl-prod.html"),
        ]
        for rel in expected:
            self.assertTrue(
                (self.reports_root / rel).exists(),
                f"missing tree node html: {rel}",
            )

        # Deep breadcrumb: cluster page references its ancestors' reports.
        cluster_html = (self.reports_root / "vsphere/vc-lab/dc-east/cl-prod/cl-prod.html").read_text()
        self.assertIn("CL-Prod", cluster_html)
        self.assertIn("breadcrumb-current", cluster_html)
        # Relative link up 3 levels to vsphere.html
        self.assertIn("../../../vsphere.html", cluster_html)

    def test_reporter_reads_tree_raw_paths(self) -> None:
        """Bundles written only under reports_root/<inventory>/… are picked up."""
        # Simulate what the new collector writes: no legacy platform/… files at all,
        # only tree-layout raw.yaml files already materialized under reports_root.
        (self.reports_root / "ubuntu" / "web-01").mkdir(parents=True)
        (self.reports_root / "ubuntu" / "web-01" / "raw.yaml").write_text(yaml.safe_dump({
            "metadata": {"host": "web-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "hostname": "web-01",
                "distribution": "Ubuntu", "distribution_version": "24.04",
                "kernel": "6.8.0", "uptime_seconds": 86400,
                "memory_total_mb": 16384, "memory_free_mb": 8192,
                "swap_total_mb": 0, "swap_free_mb": 0,
                "mounts": [{"mount": "/", "device": "/dev/sda1", "fstype": "ext4",
                            "size_total": 100 * 1024**3, "size_available": 50 * 1024**3}],
                "failed_services": {"stdout_lines": []},
                "shadow_raw": {"stdout_lines": []},
                "sshd_raw": {"stdout_lines": []},
                "world_writable": {"stdout_lines": []},
                "reboot_stat": {"stat": {"exists": False}},
                "apt_simulate": {"stdout_lines": ["0 upgraded"]},
                "file_stats": {"results": []},
                "epoch_seconds": 1740610800,
            },
        }))

        # Touch an empty platform_root so the CLI has something to scan.
        self.platform_root.mkdir(parents=True)

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root", str(self.platform_root),
                "--reports-root", str(self.reports_root),
                "--report-stamp", "20260226",
            ],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, result.output)

        # The tree reader should have found the bundle and rendered the host page.
        self.assertTrue((self.reports_root / "ubuntu" / "web-01" / "web-01.html").exists())

    def test_flat_inventory_emits_product_then_host(self) -> None:
        self._write_bundle("linux/ubuntu/web-01/raw_ubuntu.yaml", {
            "metadata": {"host": "web-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {
                "hostname": "web-01",
                "distribution": "Ubuntu", "distribution_version": "24.04",
                "kernel": "6.8.0", "uptime_seconds": 86400,
                "memory_total_mb": 16384, "memory_free_mb": 8192,
                "swap_total_mb": 0, "swap_free_mb": 0,
                "mounts": [{"mount": "/", "device": "/dev/sda1", "fstype": "ext4",
                            "size_total": 100 * 1024**3, "size_available": 50 * 1024**3}],
                "failed_services": {"stdout_lines": []},
                "shadow_raw": {"stdout_lines": []},
                "sshd_raw": {"stdout_lines": []},
                "world_writable": {"stdout_lines": []},
                "reboot_stat": {"stat": {"exists": False}},
                "apt_simulate": {"stdout_lines": ["0 upgraded"]},
                "file_stats": {"results": []},
                "epoch_seconds": 1740610800,
            },
        })
        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root", str(self.platform_root),
                "--reports-root", str(self.reports_root),
                "--report-stamp", "20260226",
            ],
            catch_exceptions=False,
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.reports_root / "ubuntu/ubuntu.html").exists())
        self.assertTrue((self.reports_root / "ubuntu/web-01/web-01.html").exists())


if __name__ == "__main__":
    unittest.main()
