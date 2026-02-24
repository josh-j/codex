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


class StigReportViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

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
        view = self.module.build_stig_host_view(
            "ubuntu01", "stig_ubuntu", payload, report_id="RID"
        )

        self.assertEqual(view["target"]["platform"], "linux")
        self.assertEqual(view["target"]["target_type"], "ubuntu")
        self.assertEqual(view["summary"]["findings"]["total"], 2)
        self.assertEqual(view["summary"]["findings"]["critical"], 1)
        self.assertEqual(view["summary"]["findings"]["warning"], 1)
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
        view = self.module.build_stig_host_view("esx01", "stig_esxi", payload)

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
            }
        }
        view = self.module.build_stig_fleet_view(aggregated, report_stamp="20260224")

        self.assertEqual(view["fleet"]["totals"]["hosts"], 2)
        self.assertEqual(view["fleet"]["totals"]["findings_open"], 2)
        self.assertEqual(view["fleet"]["totals"]["critical"], 1)
        self.assertEqual(view["fleet"]["totals"]["warning"], 2)
        self.assertEqual(view["fleet"]["by_platform"]["linux"]["hosts"], 1)
        self.assertEqual(view["fleet"]["by_platform"]["vmware"]["hosts"], 1)
        self.assertEqual(len(view["rows"]), 2)
        self.assertTrue(any(r["platform"] == "linux" for r in view["rows"]))
        self.assertTrue(any(r["platform"] == "vmware" for r in view["rows"]))
        self.assertGreaterEqual(len(view["findings_index"]["top_findings"]), 1)


if __name__ == "__main__":
    unittest.main()

