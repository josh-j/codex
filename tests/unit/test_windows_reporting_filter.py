import importlib.util
import pathlib
import unittest

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "windows"
    / "plugins"
    / "filter"
    / "reporting.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("windows_reporting_filter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class WindowsReportingFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_windows_fleet_and_node_views(self):
        aggregated = {
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
        fleet = self.module.windows_fleet_view(aggregated, report_stamp="20260224")
        self.assertEqual(fleet["fleet"]["hosts"], 1)
        self.assertEqual(fleet["fleet"]["alerts"]["warning"], 1)
        self.assertEqual(fleet["rows"][0]["status"]["raw"], "WARNING")

        node = self.module.windows_node_view(aggregated["hosts"]["win01"], hostname="win01")
        self.assertEqual(node["node"]["name"], "win01")
        self.assertEqual(node["node"]["summary"]["updates"]["failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
