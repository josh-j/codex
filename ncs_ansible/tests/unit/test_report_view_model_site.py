import pathlib
import sys
import unittest

_NCS_SRC = str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src")
if _NCS_SRC not in sys.path:
    sys.path.insert(0, _NCS_SRC)

from ncs_reporter.view_models.site import build_site_dashboard_view  # noqa: E402


class SiteReportViewModelTests(unittest.TestCase):
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
                "win01": {
                    "windows_audit": {
                        "health": "WARNING",
                        "summary": {"services": {"ccmexec_running": False}},
                    }
                },
            }
        }
        view = build_site_dashboard_view(
            aggregated,
            {"ubuntu_servers": ["host1"], "vcenters": ["vc01"], "windows_servers": ["win01"]},
            report_id="RID",
        )
        self.assertEqual(view["totals"]["critical"], 1)
        self.assertEqual(view["totals"]["warning"], 2)
        self.assertEqual(view["platforms"]["linux"]["asset_count"], 1)
        self.assertEqual(view["platforms"]["vmware"]["asset_count"], 1)
        self.assertEqual(view["platforms"]["windows"]["asset_count"], 1)
        self.assertEqual(view["platforms"]["linux"]["status"]["raw"], "CRITICAL")
        self.assertEqual(view["platforms"]["vmware"]["status"]["raw"], "WARNING")
        self.assertEqual(view["platforms"]["windows"]["status"]["raw"], "WARNING")
        self.assertIn("fleet_dashboard", view["platforms"]["linux"]["links"])
        self.assertIn("fleet_dashboard", view["platforms"]["vmware"]["links"])
        self.assertIn("fleet_dashboard", view["platforms"]["windows"]["links"])
        self.assertIn("stig_fleet", view["security"])
        self.assertEqual(len(view["security"]["stig_fleet"]["rows"]), 1)
        self.assertEqual(len(view["security"]["stig_fleet"]["rows"][0]["findings"]), 1)
        self.assertEqual(view["security"]["stig_fleet"]["rows"][0]["status"]["raw"], "WARNING")
        self.assertEqual(len(view["compute"]["nodes"]), 1)
        self.assertEqual(view["compute"]["nodes"][0]["status"]["raw"], "OK")
        self.assertIn("fleet_dashboard", view["compute"]["nodes"][0]["links"])


if __name__ == "__main__":
    unittest.main()
