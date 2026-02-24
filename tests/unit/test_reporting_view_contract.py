import importlib.util
import pathlib
import unittest
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE_REPORT_VM_PATH = (
    ROOT
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "report_view_models.py"
)
WINDOWS_REPORTING_PATH = (
    ROOT / "collections" / "ansible_collections" / "internal" / "windows" / "plugins" / "filter" / "reporting.py"
)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportingViewContractTests(unittest.TestCase):
    core_vm: Any
    windows: Any
    @classmethod
    def setUpClass(cls):
        cls.core_vm = _load(CORE_REPORT_VM_PATH, "core_report_view_models")
        cls.windows = _load(WINDOWS_REPORTING_PATH, "windows_reporting_filter")

    def assert_fleet_contract(self, view):
        self.assertIsInstance(view, dict)
        self.assertIsInstance(view.get("meta"), dict)
        self.assertIsInstance(view.get("fleet"), dict)
        self.assertIsInstance(view.get("rows"), list)
        self.assertIsInstance(view.get("active_alerts"), list)
        self.assertIn("report_stamp", view["meta"])

    def test_linux_vmware_windows_fleet_views_share_core_contract(self):
        linux_hosts = {
            "host1": {
                "system": {
                    "health": "WARNING",
                    "summary": {"critical_count": 0, "warning_count": 1},
                    "alerts": [{"severity": "WARNING", "category": "updates", "message": "Pending updates"}],
                    "data": {"system": {"services": {"failed_list": []}, "disks": []}},
                }
            }
        }
        vmware_hosts = {
            "vc01": {
                "discovery": {"summary": {"clusters": 1, "hosts": 2, "vms": 10}},
                "audit": {
                    "alerts": [{"severity": "WARNING", "category": "capacity", "message": "High CPU"}],
                    "vcenter_health": {
                        "health": {"overall": "yellow"},
                        "data": {
                            "utilization": {
                                "cpu_total_mhz": 1000,
                                "cpu_used_mhz": 750,
                                "mem_total_mb": 2000,
                                "mem_used_mb": 1000,
                            }
                        },
                    },
                },
            }
        }
        windows_hosts = {
            "hosts": {
                "win01": {
                    "windows_audit": {
                        "health": "WARNING",
                        "summary": {
                            "applications": {"configmgr_count": 1, "installed_count": 2, "apps_to_update_count": 1},
                            "updates": {"failed_count": 1},
                            "services": {"ccmexec_running": True},
                        },
                        "alerts": [{"severity": "WARNING", "message": "Update failed"}],
                    }
                }
            }
        }

        linux_view = self.core_vm.build_linux_fleet_view(linux_hosts, report_stamp="20260224")
        vmware_view = self.core_vm.build_vmware_fleet_view(vmware_hosts, report_stamp="20260224")
        windows_view = self.windows.windows_fleet_view(windows_hosts, report_stamp="20260224")

        for view in (linux_view, vmware_view, windows_view):
            self.assert_fleet_contract(view)

        self.assertEqual(linux_view["fleet"]["hosts"], 1)
        self.assertEqual(vmware_view["fleet"]["alerts"]["warning"], 1)
        self.assertEqual(windows_view["rows"][0]["status"]["raw"], "WARNING")


if __name__ == "__main__":
    unittest.main()
