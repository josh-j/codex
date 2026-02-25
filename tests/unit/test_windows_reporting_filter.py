import pathlib
import sys
import unittest

_NCS_SRC = str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src")
if _NCS_SRC not in sys.path:
    sys.path.insert(0, _NCS_SRC)

from ncs_reporter.view_models.windows import build_windows_fleet_view, build_windows_node_view  # noqa: E402


class WindowsReportingFilterTests(unittest.TestCase):
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
        fleet = build_windows_fleet_view(aggregated, report_stamp="20260224")
        self.assertEqual(fleet["fleet"]["hosts"], 1)
        self.assertEqual(fleet["fleet"]["alerts"]["warning"], 1)
        self.assertEqual(fleet["rows"][0]["status"]["raw"], "WARNING")

        node = build_windows_node_view(aggregated["hosts"]["win01"], hostname="win01")
        self.assertEqual(node["node"]["name"], "win01")
        self.assertEqual(node["node"]["summary"]["updates"]["failed_count"], 1)


if __name__ == "__main__":
    unittest.main()
