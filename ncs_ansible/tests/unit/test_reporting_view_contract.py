from __future__ import annotations

import unittest
from pathlib import Path

from ncs_reporter.schema_loader import load_schema_from_file
from ncs_reporter.view_models.generic import build_generic_fleet_view

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


def _vcenter_bundle(hostname: str) -> dict:
    return {
        "vmware_raw_vcenter": {
            "metadata": {"host": hostname, "timestamp": "2026-03-01T00:00:00Z"},
            "data": {
                "appliance_health_info": {
                    "appliance": {
                        "summary": {
                            "product": "vCenter Server",
                            "version": "8.0.2",
                            "build_number": "23319199",
                            "uptime": 172800,
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
    }


def _windows_bundle(hostname: str) -> dict:
    return {
        "windows_raw_audit": {
            "metadata": {"host": hostname, "timestamp": "2026-03-01T00:00:00Z"},
            "data": {
                "ccm_service": {"state": "Running"},
                "configmgr_apps": {},
                "installed_apps": [],
                "update_results": [],
            },
        }
    }


class ReportingViewContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = {
            "linux": load_schema_from_file(SCHEMAS_DIR / "linux.yaml"),
            "vmware": load_schema_from_file(SCHEMAS_DIR / "vcenter.yaml"),
            "windows": load_schema_from_file(SCHEMAS_DIR / "windows.yaml"),
        }

    def _assert_fleet_contract(self, view: dict) -> None:
        self.assertIsInstance(view, dict)
        self.assertIsInstance(view.get("meta"), dict)
        self.assertIsInstance(view.get("hosts"), list)
        self.assertIsInstance(view.get("active_alerts"), list)
        self.assertIsInstance(view.get("fleet_columns"), list)
        self.assertIn("crit_count", view)
        self.assertIn("warn_count", view)
        self.assertIn("report_stamp", view["meta"])

    def test_generic_fleet_views_share_core_contract(self) -> None:
        linux_view = build_generic_fleet_view(
            self.schemas["linux"],
            {"hosts": {"linux-01": _linux_bundle("linux-01")}},
            report_stamp="20260301",
        )
        vmware_view = build_generic_fleet_view(
            self.schemas["vmware"],
            {"hosts": {"vc-01": _vcenter_bundle("vc-01")}},
            report_stamp="20260301",
        )
        windows_view = build_generic_fleet_view(
            self.schemas["windows"],
            {"hosts": {"win-01": _windows_bundle("win-01")}},
            report_stamp="20260301",
        )

        for view in (linux_view, vmware_view, windows_view):
            self._assert_fleet_contract(view)

        self.assertEqual(linux_view["meta"]["platform"], "linux")
        self.assertEqual(vmware_view["meta"]["platform"], "vmware")
        self.assertEqual(windows_view["meta"]["platform"], "windows")
        self.assertEqual(linux_view["meta"]["total_hosts"], 1)
        self.assertEqual(vmware_view["meta"]["total_hosts"], 1)
        self.assertEqual(windows_view["meta"]["total_hosts"], 1)


if __name__ == "__main__":
    unittest.main()
