import importlib.util
import pathlib
import unittest
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "stig.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_stig_filter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreStigFilterTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_normalize_stig_results_builds_summary_and_alerts(self):
        rows = [
            {
                "id": "V-1",
                "status": "PASS",
                "title": "Rule One",
                "severity": "CAT_II",
                "checktext": "ok",
            },
            {
                "id": "V-2",
                "status": "failed",
                "title": "Rule Two",
                "severity": "CAT_I",
                "checktext": "bad",
            },
            {
                "id": "V-3",
                "status": "FAILED",
                "title": "Rule Three",
                "severity": "MEDIUM",
                "details": "fallback details",
            },
        ]

        out = self.module.normalize_stig_results(rows, "ubuntu2404")

        self.assertEqual(out["summary"]["total"], 3)
        self.assertEqual(out["summary"]["violations"], 2)
        self.assertEqual(out["summary"]["passed"], 1)
        self.assertEqual(out["summary"]["critical_count"], 1)
        self.assertEqual(out["summary"]["warning_count"], 1)
        self.assertEqual(len(out["alerts"]), 2)
        self.assertEqual(out["alerts"][0]["severity"], "CRITICAL")
        self.assertEqual(out["alerts"][1]["severity"], "WARNING")
        self.assertEqual(out["alerts"][0]["detail"]["target_type"], "ubuntu2404")

    def test_normalize_stig_results_normalizes_status_and_handles_missing_fields(self):
        rows = [
            {"status": "FaIlEd", "severity": "weird"},
            "not-a-dict",
            {},
        ]

        out = self.module.normalize_stig_results(rows, "")

        self.assertEqual(len(out["full_audit"]), 2)
        self.assertEqual(out["full_audit"][0]["status"], "failed")
        self.assertEqual(out["full_audit"][1]["status"], "")
        self.assertEqual(out["summary"]["violations"], 1)
        self.assertEqual(out["summary"]["critical_count"], 0)
        self.assertEqual(out["summary"]["warning_count"], 0)
        self.assertEqual(out["alerts"][0]["severity"], "INFO")
        self.assertEqual(out["alerts"][0]["detail"]["rule_id"], "")
        self.assertEqual(out["alerts"][0]["message"], "STIG Violation: Unknown Rule")

    def test_normalize_stig_results_empty_input(self):
        out = self.module.normalize_stig_results(None, "esxi")

        self.assertEqual(out["full_audit"], [])
        self.assertEqual(out["violations"], [])
        self.assertEqual(out["alerts"], [])
        self.assertEqual(
            out["summary"],
            {
                "total": 0,
                "violations": 0,
                "passed": 0,
                "critical_count": 0,
                "warning_count": 0,
            },
        )

    def test_normalize_stig_results_handles_variant_field_names_and_status_aliases(self):
        rows = [
            {
                "rule_id": "V-100",
                "rule_title": "SSH root login disabled",
                "finding_status": "Open",
                "cat": "CAT_I",
                "finding_details": "Observed root login allowed",
            },
            {
                "vuln_id": "V-101",
                "title": "Banner configured",
                "result": "notafinding",
                "severity": "CAT_II",
            },
            {
                "id": "V-102",
                "compliance": "non_compliant",
                "severity_override": "HIGH",
            },
        ]

        out = self.module.normalize_stig_results(rows, "esxi")

        self.assertEqual(out["summary"]["total"], 3)
        self.assertEqual(out["summary"]["violations"], 2)
        self.assertEqual(out["summary"]["critical_count"], 2)
        self.assertEqual(out["summary"]["passed"], 1)
        self.assertEqual(out["alerts"][0]["detail"]["rule_id"], "V-100")
        self.assertEqual(out["alerts"][0]["detail"]["description"], "Observed root login allowed")
        self.assertEqual(out["alerts"][1]["detail"]["rule_id"], "V-102")
        self.assertEqual(out["alerts"][1]["message"], "STIG Violation: V-102")

    def test_stig_eval_basic(self):
        rules = [
            {"id": "R1", "check": True, "pass_msg": "OK"},
            {"id": "R2", "check": False, "fail_msg": "BAD", "severity": "high"},
        ]
        results = self.module.stig_eval(rules)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["status"], "pass")
        self.assertEqual(results[0]["checktext"], "OK")
        self.assertEqual(results[1]["status"], "failed")
        self.assertEqual(results[1]["checktext"], "BAD")
        self.assertEqual(results[1]["severity"], "high")

    def test_get_adv_lookup(self):
        settings = [{"key": "K1", "value": "V1"}, {"key": "K2", "value": "V2"}]
        self.assertEqual(self.module.get_adv(settings, "K1"), "V1")
        self.assertEqual(self.module.get_adv(settings, "K3", "MISSING"), "MISSING")


if __name__ == "__main__":
    unittest.main()
