import unittest

from ncs_reporter.view_models.site import build_site_dashboard_view  # noqa: E402


class SiteReportViewModelTests(unittest.TestCase):
    def test_builds_site_dashboard_view(self):
        aggregated = {
            "hosts": {
                "host1": {
                    "schema_linux": {
                        "alerts": [{"severity": "CRITICAL", "message": "disk", "category": "disk"}],
                        "health": "CRITICAL",
                    },
                    "stig_ubuntu": {
                        "health": "WARNING",
                        "alerts": [{"severity": "WARNING", "detail": {"rule_id": "V-1"}, "message": "finding"}],
                    },
                },
                "vc01": {
                    "schema_vcenter": {
                        "health": "green",
                        "alerts": [{"severity": "WARNING", "message": "cpu", "category": "capacity"}],
                        "fields": {
                            "datacenter_count": 1,
                            "cluster_count": 1,
                            "esxi_host_count": 2,
                            "vm_count": 10,
                            "datastore_count": 3,
                            "snapshot_count": 0,
                            "alarm_count": 0,
                        },
                    },
                },
                "win01": {
                    "schema_windows": {
                        "health": "WARNING",
                        "alerts": [],
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
