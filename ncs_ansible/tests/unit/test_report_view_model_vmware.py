import pathlib
import sys
import unittest

_NCS_SRC = str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src")
if _NCS_SRC not in sys.path:
    sys.path.insert(0, _NCS_SRC)

from ncs_reporter.view_models.vmware import build_vmware_fleet_view, build_vmware_node_view  # noqa: E402


class VmwareReportViewModelTests(unittest.TestCase):
    def test_builds_fleet_totals_and_rows_from_mixed_shapes(self):
        hosts = {
            "summary": {"ignore": True},
            "vc01": {
                "discovery": {
                    "summary": {"clusters": 2, "hosts": 10, "vms": 100},
                    "health": {"appliance": {"info": {"version": "8.0.2"}}},
                },
                "vcenter": {
                    "vcenter_health": {
                        "health": "green",
                        "data": {
                            "utilization": {
                                "cpu_total_mhz": 1000,
                                "cpu_used_mhz": 500,
                                "mem_total_mb": 2000,
                                "mem_used_mb": 1000,
                            }
                        },
                        "alerts": [{"severity": "CRITICAL"}, {"severity": "warn"}],
                    }
                },
            },
            "vc02": {
                "discovery": {
                    "summary": {"clusters": 1, "hosts": 5, "vms": 50},
                    "health": {"appliance": {"info": {"version": "7.0.3"}}},
                },
                "audit": {
                    "alerts": [{"severity": "CAT_II"}],
                    "vcenter_health": {
                        "health": {"overall": "yellow"},
                        "data": {
                            "utilization": {
                                "cpu_total_mhz": 1000,
                                "cpu_used_mhz": 250,
                                "mem_total_mb": 2000,
                                "mem_used_mb": 500,
                            }
                        },
                    },
                },
            },
        }

        view = build_vmware_fleet_view(
            hosts, report_stamp="20260224", report_date="2026-02-24 00:00:00", report_id="RID"
        )

        self.assertEqual(view["fleet"]["asset_count"], 2)
        self.assertEqual(view["fleet"]["totals"]["clusters"], 3)
        self.assertEqual(view["fleet"]["totals"]["hosts"], 15)
        self.assertEqual(view["fleet"]["totals"]["vms"], 150)
        self.assertEqual(view["fleet"]["alerts"]["critical"], 1)
        self.assertEqual(view["fleet"]["alerts"]["warning"], 2)
        self.assertEqual(view["fleet"]["utilization"]["cpu"]["pct"], 37.5)
        self.assertEqual(view["fleet"]["utilization"]["memory"]["pct"], 37.5)
        self.assertEqual(view["meta"]["report_stamp"], "20260224")

        row_names = [row["name"] for row in view["rows"]]
        self.assertEqual(row_names, ["vc01", "vc02"])
        self.assertEqual(view["rows"][0]["status"]["raw"], "OK")
        self.assertEqual(view["rows"][1]["status"]["raw"], "WARNING")

    def test_defaults_missing_fields_safely(self):
        view = build_vmware_fleet_view({"vc03": {"vcenter_health": {}}})

        self.assertEqual(view["fleet"]["asset_count"], 1)
        self.assertEqual(view["fleet"]["alerts"]["total"], 0)
        self.assertEqual(view["fleet"]["utilization"]["cpu"]["pct"], 0.0)
        self.assertEqual(view["rows"][0]["version"], "N/A")
        self.assertEqual(view["rows"][0]["links"]["node_report_latest"], "./vc03/health_report.html")

    def test_builds_node_view_from_bundle(self):
        bundle = {
            "discovery": {
                "summary": {"clusters": 1, "hosts": 2, "vms": 20},
                "inventory": {
                    "clusters": {
                        "list": [
                            {
                                "name": "Cluster-A",
                                "datacenter": "DC1",
                                "utilization": {"cpu_pct": 70.0, "mem_pct": 65.0},
                                "compliance": {"ha_enabled": True, "drs_enabled": False},
                            }
                        ]
                    }
                },
                "health": {
                    "appliance": {
                        "info": {"product": "vCenter Server", "version": "8.0.1", "build": "123"},
                        "health": {"overall": "green", "cpu": "green", "memory": "yellow"},
                        "backup": {"enabled": False},
                        "config": {"ssh_enabled": True},
                    }
                },
            },
            "vcenter": {
                "alerts": [{"severity": "warning", "category": "test", "message": "Something"}],
                "vcenter_health": {
                    "health": "yellow",
                    "data": {
                        "utilization": {
                            "cpu_total_mhz": 1000,
                            "cpu_used_mhz": 700,
                            "mem_total_mb": 2000,
                            "mem_used_mb": 1300,
                        }
                    },
                },
            },
        }
        view = build_vmware_node_view("vc-node", bundle, report_id="RID")
        node = view["node"]

        self.assertEqual(node["name"], "vc-node")
        self.assertEqual(node["status"]["raw"], "WARNING")
        self.assertEqual(node["alerts"]["counts"]["warning"], 1)
        self.assertEqual(node["inventory"]["vms"], 20)
        self.assertEqual(node["utilization"]["cpu_pct"], 70.0)
        self.assertEqual(node["links"]["fleet_dashboard"], "../vmware_health_report.html")
        self.assertEqual(node["clusters"][0]["name"], "Cluster-A")


if __name__ == "__main__":
    unittest.main()
