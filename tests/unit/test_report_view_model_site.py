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


class SiteReportViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_builds_site_dashboard_view(self):
        aggregated = {
            "hosts": {
                "host1": {
                    "system": {
                        "alerts": [{"severity": "CRITICAL", "message": "disk", "category": "disk"}],
                        "health": "CRITICAL",
                    },
                    "stig_ubuntu": {
                        "health": "WARNING",
                        "alerts": [{"severity": "WARNING", "detail": {"rule_id": "V-1"}, "message": "finding"}],
                    },
                },
                "vc01": {
                    "discovery": {
                        "inventory": {
                            "clusters": {"list": [{"name": "ClusterA", "utilization": {"cpu_pct": 50, "mem_pct": 60}}]}
                        }
                    },
                    "vcenter": {
                        "vcenter_health": {"health": "green", "alerts": [{"severity": "WARNING"}]},
                    },
                },
            }
        }
        view = self.module.build_site_dashboard_view(
            aggregated,
            {"ubuntu_servers": ["host1"], "vcenters": ["vc01"]},
            report_id="RID",
        )
        self.assertEqual(view["totals"]["critical"], 1)
        self.assertEqual(view["totals"]["warning"], 1)
        self.assertEqual(view["platforms"]["linux"]["asset_count"], 1)
        self.assertEqual(view["platforms"]["vmware"]["asset_count"], 1)
        self.assertEqual(len(view["security"]["stig_entries"]), 1)
        self.assertEqual(len(view["compute"]["nodes"]), 1)


if __name__ == "__main__":
    unittest.main()
