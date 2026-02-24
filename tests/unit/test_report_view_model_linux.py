import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "report_view_models.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("report_view_models", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class LinuxReportViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_builds_linux_fleet_and_node_views(self):
        hosts = {
            "host1": {
                "system": {
                    "health": "WARNING",
                    "distribution": "Ubuntu",
                    "distribution_version": "24.04",
                    "summary": {"critical_count": 1, "warning_count": 2},
                    "alerts": [
                        {"severity": "CRITICAL", "category": "disk", "message": "Disk full"},
                        {"severity": "warn", "category": "updates", "message": "Updates pending"},
                    ],
                    "data": {
                        "system": {
                            "services": {"failed_list": ["foo.service failed"]},
                            "disks": [
                                {
                                    "mount": "/",
                                    "device": "/dev/sda1",
                                    "free_gb": 1,
                                    "total_gb": 100,
                                    "used_pct": 99,
                                }
                            ],
                        }
                    },
                },
                "stig": {
                    "health": "CRITICAL",
                    "alerts": [{"severity": "CRITICAL"}],
                },
            },
            "platform": {"ignore": True},
        }

        fleet = self.module.build_linux_fleet_view(hosts, report_stamp="20260224")
        self.assertEqual(len(fleet["rows"]), 1)
        self.assertEqual(fleet["fleet"]["hosts"], 1)
        self.assertEqual(fleet["fleet"]["alerts"]["critical"], 1)
        self.assertEqual(fleet["fleet"]["alerts"]["warning"], 2)
        self.assertEqual(len(fleet["active_alerts"]), 2)
        self.assertEqual(fleet["stig_rows"][0]["open_findings"], 1)

        node = self.module.build_linux_node_view("host1", hosts["host1"])
        self.assertEqual(node["node"]["name"], "host1")
        self.assertEqual(node["node"]["health"], "WARNING")
        self.assertEqual(len(node["node"]["alerts"]), 2)
        self.assertIn("services", node["node"]["sys_facts"])


if __name__ == "__main__":
    unittest.main()
