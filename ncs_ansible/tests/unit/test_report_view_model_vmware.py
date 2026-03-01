from __future__ import annotations

import unittest
from pathlib import Path

from ncs_reporter.schema_loader import load_schema_from_file
from ncs_reporter.view_models.generic import build_generic_fleet_view, build_generic_node_view

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "files" / "ncs_reporter_configs"


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


class VmwareReportViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = load_schema_from_file(SCHEMAS_DIR / "vcenter.yaml")

    def test_builds_vmware_fleet_view(self) -> None:
        aggregated = {"hosts": {"vc-01": _vcenter_bundle("vc-01"), "vc-02": _vcenter_bundle("vc-02")}}
        view = build_generic_fleet_view(self.schema, aggregated, report_stamp="20260301")

        self.assertEqual(view["meta"]["platform"], "vmware")
        self.assertEqual(view["meta"]["total_hosts"], 2)
        self.assertEqual(len(view["hosts"]), 2)
        self.assertEqual([h["hostname"] for h in view["hosts"]], ["vc-01", "vc-02"])
        self.assertEqual(view["hosts"][0]["fields"]["appliance_version"], "8.0.2")

    def test_builds_vmware_node_view(self) -> None:
        view = build_generic_node_view(self.schema, "vc-01", _vcenter_bundle("vc-01"), report_id="RID")

        self.assertEqual(view["meta"]["host"], "vc-01")
        self.assertEqual(view["meta"]["platform"], "vmware")
        self.assertEqual(view["meta"]["display_name"], "VMware vCenter")
        self.assertEqual(view["meta"]["report_id"], "RID")
        self.assertEqual(view["fields"]["appliance_version"], "8.0.2")
        self.assertIn("widgets", view)


if __name__ == "__main__":
    unittest.main()
