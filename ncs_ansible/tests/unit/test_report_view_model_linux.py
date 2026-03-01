from __future__ import annotations

import unittest
from pathlib import Path

from ncs_reporter.schema_loader import load_schema_from_file
from ncs_reporter.view_models.generic import build_generic_fleet_view, build_generic_node_view

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "files" / "ncs_reporter_configs"


def _linux_bundle(hostname: str) -> dict:
    return {
        "ubuntu_raw_discovery": {
            "metadata": {"host": hostname, "timestamp": "2026-03-01T00:00:00Z"},
            "data": {
                "ansible_facts": {
                    "hostname": hostname,
                    "default_ipv4": {"address": "10.0.0.10"},
                    "kernel": "6.8.0",
                    "os_family": "Debian",
                    "distribution": "Ubuntu",
                    "distribution_version": "24.04",
                    "uptime_seconds": 86400,
                    "loadavg": {"15m": 0.2},
                    "memtotal_mb": 1024,
                    "memfree_mb": 256,
                    "swaptotal_mb": 512,
                    "swapfree_mb": 128,
                    "mounts": [],
                    "getent_passwd": {},
                    "date_time": {"epoch": "1740787200"},
                },
                "failed_services": {"stdout_lines": []},
                "apt_simulate": {"stdout_lines": []},
                "reboot_stat": {"stat": {"exists": False}},
                "shadow_raw": {"stdout_lines": []},
                "sshd_raw": {"stdout_lines": []},
                "world_writable": {"stdout_lines": []},
            },
        }
    }


class LinuxReportViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_schema_from_file(SCHEMAS_DIR / "linux.yaml")

    def test_builds_linux_fleet_view(self) -> None:
        aggregated = {"hosts": {"linux-01": _linux_bundle("linux-01")}}
        view = build_generic_fleet_view(self.schema, aggregated, report_stamp="20260301")

        self.assertEqual(view["meta"]["platform"], "linux")
        self.assertEqual(view["meta"]["total_hosts"], 1)
        self.assertEqual(view["meta"]["report_stamp"], "20260301")
        self.assertEqual(len(view["hosts"]), 1)
        self.assertEqual(view["hosts"][0]["hostname"], "linux-01")
        self.assertIn("fleet_columns", view)
        self.assertIn("active_alerts", view)
        self.assertIn("crit_count", view)
        self.assertIn("warn_count", view)

    def test_builds_linux_node_view(self) -> None:
        bundle = _linux_bundle("linux-01")
        view = build_generic_node_view(self.schema, "linux-01", bundle, report_id="RID")

        self.assertEqual(view["meta"]["host"], "linux-01")
        self.assertEqual(view["meta"]["platform"], "linux")
        self.assertEqual(view["meta"]["report_id"], "RID")
        self.assertIn("health", view)
        self.assertIn("alerts", view)
        self.assertIn("fields", view)
        self.assertIn("widgets", view)


if __name__ == "__main__":
    unittest.main()
