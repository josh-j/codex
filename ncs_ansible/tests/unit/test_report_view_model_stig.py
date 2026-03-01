import unittest

from ncs_reporter.view_models.stig import build_stig_fleet_view, build_stig_host_view  # noqa: E402


class StigReportViewModelTests(unittest.TestCase):
    def test_build_stig_host_view_from_alert_payload(self):
        payload = {
            "health": "CRITICAL",
            "alerts": [
                {
                    "severity": "CAT_I",
                    "category": "security_compliance",
                    "message": "STIG Violation: Root login disabled",
                    "detail": {"rule_id": "V-100", "original_severity": "CAT_I"},
                    "status": "failed",
                },
                {
                    "severity": "CAT_II",
                    "message": "STIG Violation: Banner set",
                    "detail": {"rule_id": "V-101", "original_severity": "CAT_II"},
                    "status": "pass",
                },
            ],
        }
        view = build_stig_host_view("ubuntu01", "stig_ubuntu", payload, report_id="RID")

        self.assertEqual(view["target"]["platform"], "linux")
        self.assertEqual(view["target"]["target_type"], "ubuntu")
        self.assertEqual(view["summary"]["findings"]["total"], 2)
        self.assertEqual(view["summary"]["findings"]["critical"], 1)
        self.assertEqual(view["summary"]["findings"]["warning"], 0)
        self.assertEqual(view["summary"]["by_status"]["open"], 1)
        self.assertEqual(view["summary"]["by_status"]["pass"], 1)
        self.assertEqual(view["findings"][0]["rule_id"], "V-100")

    def test_build_stig_host_view_from_full_audit_rows(self):
        payload = {
            "health": "WARNING",
            "full_audit": [
                {"id": "V-200", "status": "FAILED", "severity": "CAT_I", "title": "SSH root login"},
                {"id": "V-201", "status": "PASS", "severity": "CAT_II", "title": "Banner"},
                {"id": "V-202", "status": "not_applicable", "severity": "CAT_III", "title": "N/A Rule"},
            ],
        }
        view = build_stig_host_view("esx01", "stig_esxi", payload)

        self.assertEqual(view["target"]["platform"], "vmware")
        self.assertEqual(view["target"]["target_type"], "esxi")
        self.assertEqual(view["summary"]["findings"]["critical"], 1)
        self.assertEqual(view["summary"]["by_status"]["open"], 1)
        self.assertEqual(view["summary"]["by_status"]["pass"], 1)
        self.assertEqual(view["summary"]["by_status"]["na"], 1)

    def test_build_stig_fleet_view_rolls_up_mixed_platforms(self):
        aggregated = {
            "hosts": {
                "ubuntu01": {
                    "stig_ubuntu": {
                        "health": "WARNING",
                        "alerts": [
                            {
                                "severity": "CAT_II",
                                "message": "STIG Violation: Banner",
                                "detail": {"rule_id": "V-101", "original_severity": "CAT_II"},
                                "status": "failed",
                            }
                        ],
                    }
                },
                "esx01": {
                    "stig_esxi": {
                        "health": "CRITICAL",
                        "full_audit": [
                            {"id": "V-200", "status": "FAILED", "severity": "CAT_I", "title": "SSH root login"},
                            {"id": "V-201", "status": "PASS", "severity": "CAT_II", "title": "Banner"},
                        ],
                    }
                },
                "win01": {
                    "stig": {
                        "target_type": "windows_server_2022",
                        "health": "WARNING",
                        "full_audit": [
                            {
                                "id": "WN-1",
                                "status": "FAILED",
                                "severity": "CAT_II",
                                "title": "RDP NLA",
                            }
                        ],
                    }
                },
            }
        }
        view = build_stig_fleet_view(aggregated, report_stamp="20260224")

        self.assertEqual(view["fleet"]["totals"]["hosts"], 3)
        self.assertEqual(view["fleet"]["totals"]["findings_open"], 3)
        self.assertEqual(view["fleet"]["totals"]["critical"], 1)
        self.assertEqual(view["fleet"]["totals"]["warning"], 2)
        self.assertEqual(view["fleet"]["by_platform"]["linux"]["hosts"], 1)
        self.assertEqual(view["fleet"]["by_platform"]["vmware"]["hosts"], 1)
        self.assertEqual(view["fleet"]["by_platform"]["windows"]["hosts"], 1)
        self.assertEqual(len(view["rows"]), 3)
        self.assertTrue(any(r["platform"] == "linux" for r in view["rows"]))
        self.assertTrue(any(r["platform"] == "vmware" for r in view["rows"]))
        self.assertTrue(any(r["platform"] == "windows" for r in view["rows"]))
        row = next(r for r in view["rows"] if r["platform"] == "linux")
        self.assertEqual(row["status"]["raw"], "WARNING")
        self.assertIn("node_report_latest", row["links"])
        win_row = next(r for r in view["rows"] if r["platform"] == "windows")
        self.assertIn("platform/windows/", win_row["links"]["node_report_latest"])
        self.assertGreaterEqual(len(view["findings_index"]["top_findings"]), 1)


if __name__ == "__main__":
    unittest.main()
