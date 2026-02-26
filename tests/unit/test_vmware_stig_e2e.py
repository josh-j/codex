"""End-to-end tests: callback artifact -> normalization -> export payload.

Uses realistic VMware STIG rule IDs from actual task files to prove the full
data pipeline works for both ESXi and VM targets.
"""

import importlib.util
import pathlib
import unittest
from typing import Any

# ---------------------------------------------------------------------------
# Load the stig filter module (same pattern as test_core_stig_filter.py)
# ---------------------------------------------------------------------------

STIG_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "stig.py"
)


def _load_stig_module() -> Any:
    spec = importlib.util.spec_from_file_location("core_stig_filter", STIG_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Realistic callback artifacts (matching _dump_json output structure)
# ---------------------------------------------------------------------------

ESXI_CALLBACK_ARTIFACT: list[dict[str, Any]] = [
    # 3 pass
    {"id": "V-256376", "rule_id": "V-256376", "name": "esxi-01", "status": "pass",
     "title": "stigrule_256376_dcui_access", "severity": "medium", "fixtext": "", "checktext": ""},
    {"id": "V-256378", "rule_id": "V-256378", "name": "esxi-01", "status": "pass",
     "title": "stigrule_256378_syslog", "severity": "medium", "fixtext": "", "checktext": ""},
    {"id": "V-256379", "rule_id": "V-256379", "name": "esxi-01", "status": "pass",
     "title": "stigrule_256379_account_lock_failures", "severity": "medium", "fixtext": "", "checktext": ""},
    # 2 failed
    {"id": "V-256397", "rule_id": "V-256397", "name": "esxi-01", "status": "failed",
     "title": "stigrule_256397_password_complexity", "severity": "high", "fixtext": "", "checktext": ""},
    {"id": "V-256398", "rule_id": "V-256398", "name": "esxi-01", "status": "failed",
     "title": "stigrule_256398_password_history", "severity": "medium", "fixtext": "", "checktext": ""},
    # 1 na
    {"id": "V-256399", "rule_id": "V-256399", "name": "esxi-01", "status": "na",
     "title": "stigrule_256399_mob_disabled", "severity": "medium", "fixtext": "", "checktext": ""},
    # 1 fixed (remediation mode)
    {"id": "V-256429", "rule_id": "V-256429", "name": "esxi-01", "status": "fixed",
     "title": "stigrule_256429_tls", "severity": "high", "fixtext": "", "checktext": ""},
]

VM_CALLBACK_ARTIFACT: list[dict[str, Any]] = [
    # 2 pass
    {"id": "V-256450", "rule_id": "V-256450", "name": "vm-web-01", "status": "pass",
     "title": "stigrule_256450_copy_disable", "severity": "low", "fixtext": "", "checktext": ""},
    {"id": "V-256451", "rule_id": "V-256451", "name": "vm-web-01", "status": "pass",
     "title": "stigrule_256451_dnd_disable", "severity": "low", "fixtext": "", "checktext": ""},
    # 2 failed
    {"id": "V-256452", "rule_id": "V-256452", "name": "vm-web-01", "status": "failed",
     "title": "stigrule_256452_paste_disable", "severity": "medium", "fixtext": "", "checktext": ""},
    {"id": "V-256453", "rule_id": "V-256453", "name": "vm-web-01", "status": "failed",
     "title": "stigrule_256453_disk_shrink_disable", "severity": "high", "fixtext": "", "checktext": ""},
]


# ===========================================================================
# Test classes
# ===========================================================================


class TestESXiNormalization(unittest.TestCase):
    """Correct counts after normalizing ESXi callback artifact."""

    mod: Any
    result: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_stig_module()
        cls.result = cls.mod.normalize_stig_results(ESXI_CALLBACK_ARTIFACT, "esxi")

    def test_total_count(self) -> None:
        self.assertEqual(self.result["summary"]["total"], 7)

    def test_violation_count(self) -> None:
        # "failed" -> open (2), "na" is not a violation, "fixed" -> pass
        self.assertEqual(self.result["summary"]["violations"], 2)

    def test_passed_count(self) -> None:
        # 3 pass + 1 fixed->pass + 1 na has status "na" (not "pass")
        self.assertEqual(self.result["summary"]["passed"], 4)

    def test_critical_alert_for_high_severity(self) -> None:
        # V-256397 is high severity + failed -> CRITICAL alert
        self.assertEqual(self.result["summary"]["critical_count"], 1)

    def test_warning_alert_for_medium_severity(self) -> None:
        # V-256398 is medium severity + failed -> WARNING alert
        self.assertEqual(self.result["summary"]["warning_count"], 1)

    def test_target_type_propagated(self) -> None:
        for alert in self.result["alerts"]:
            self.assertEqual(alert["detail"]["target_type"], "esxi")

    def test_na_not_counted_as_violation(self) -> None:
        na_rows = [r for r in self.result["full_audit"] if r["status"] == "na"]
        self.assertEqual(len(na_rows), 1)
        violation_ids = {v["rule_id"] for v in self.result["violations"]}
        self.assertNotIn("V-256399", violation_ids)


class TestVMNormalization(unittest.TestCase):
    """Correct counts for VM callback artifact."""

    mod: Any
    result: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_stig_module()
        cls.result = cls.mod.normalize_stig_results(VM_CALLBACK_ARTIFACT, "vm")

    def test_total_count(self) -> None:
        self.assertEqual(self.result["summary"]["total"], 4)

    def test_violation_count(self) -> None:
        self.assertEqual(self.result["summary"]["violations"], 2)

    def test_passed_count(self) -> None:
        self.assertEqual(self.result["summary"]["passed"], 2)

    def test_high_severity_produces_critical(self) -> None:
        # V-256453 is high + failed -> CRITICAL
        critical = [a for a in self.result["alerts"] if a["severity"] == "CRITICAL"]
        self.assertEqual(len(critical), 1)
        self.assertIn("256453", critical[0]["detail"]["rule_id"])


class TestExportPayloadContract(unittest.TestCase):
    """Both ESXi and VM payloads match the standard export shape."""

    mod: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_stig_module()

    def _check_shape(self, result: dict[str, Any]) -> None:
        self.assertIn("full_audit", result)
        self.assertIn("violations", result)
        self.assertIn("alerts", result)
        self.assertIn("summary", result)

        summary = result["summary"]
        for key in ("total", "violations", "passed", "critical_count", "warning_count"):
            self.assertIn(key, summary)
            self.assertIsInstance(summary[key], int)

        for row in result["full_audit"]:
            self.assertIsInstance(row, dict)
            self.assertIn("status", row)
            self.assertIn("rule_id", row)
            self.assertIn("title", row)
            self.assertIn("severity", row)

        for alert in result["alerts"]:
            self.assertIn("severity", alert)
            self.assertIn("category", alert)
            self.assertIn("message", alert)
            self.assertIn("detail", alert)

    def test_esxi_shape(self) -> None:
        result = self.mod.normalize_stig_results(ESXI_CALLBACK_ARTIFACT, "esxi")
        self._check_shape(result)

    def test_vm_shape(self) -> None:
        result = self.mod.normalize_stig_results(VM_CALLBACK_ARTIFACT, "vm")
        self._check_shape(result)

    def test_esxi_health_critical_when_high_violations(self) -> None:
        result = self.mod.normalize_stig_results(ESXI_CALLBACK_ARTIFACT, "esxi")
        self.assertGreater(result["summary"]["critical_count"], 0)

    def test_vm_health_critical_when_high_violations(self) -> None:
        result = self.mod.normalize_stig_results(VM_CALLBACK_ARTIFACT, "vm")
        self.assertGreater(result["summary"]["critical_count"], 0)


class TestAuditVsRemediation(unittest.TestCase):
    """'fixed' status remapped correctly depending on mode."""

    mod: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_stig_module()

    def test_fixed_normalizes_to_pass_in_hardening_mode(self) -> None:
        """In hardening/remediation mode, 'fixed' means remediated -> pass."""
        rows: list[dict[str, Any]] = [
            {"id": "V-256429", "status": "fixed", "severity": "high", "title": "TLS"},
        ]
        result = self.mod.normalize_stig_results(rows, "esxi")
        self.assertEqual(result["summary"]["passed"], 1)
        self.assertEqual(result["summary"]["violations"], 0)

    def test_fixed_remapped_to_failed_in_audit_mode(self) -> None:
        """Simulates read_callback_artifact.yaml behavior: remap 'fixed' to 'failed'
        when reviewing in audit context (since it was non-compliant before fix)."""
        rows: list[dict[str, Any]] = [
            {"id": "V-256429", "status": "failed", "severity": "high", "title": "TLS"},
        ]
        result = self.mod.normalize_stig_results(rows, "esxi")
        self.assertEqual(result["summary"]["violations"], 1)
        self.assertEqual(result["summary"]["critical_count"], 1)

    def test_mixed_mode_counts(self) -> None:
        """Mix of fixed and failed -- fixed normalizes to pass, failed stays open."""
        rows: list[dict[str, Any]] = [
            {"id": "V-256429", "status": "fixed", "severity": "high", "title": "TLS"},
            {"id": "V-256397", "status": "failed", "severity": "high", "title": "PW"},
        ]
        result = self.mod.normalize_stig_results(rows, "esxi")
        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["passed"], 1)
        self.assertEqual(result["summary"]["violations"], 1)


class TestMultiHostMerge(unittest.TestCase):
    """Two ESXi host artifacts normalize independently with correct counts."""

    mod: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_stig_module()

    def test_independent_normalization(self) -> None:
        host1_rows: list[dict[str, Any]] = [
            {"id": "V-256376", "status": "pass", "severity": "medium", "title": "R1"},
            {"id": "V-256397", "status": "failed", "severity": "high", "title": "R2"},
        ]
        host2_rows: list[dict[str, Any]] = [
            {"id": "V-256376", "status": "failed", "severity": "medium", "title": "R1"},
            {"id": "V-256397", "status": "pass", "severity": "high", "title": "R2"},
        ]

        r1 = self.mod.normalize_stig_results(host1_rows, "esxi")
        r2 = self.mod.normalize_stig_results(host2_rows, "esxi")

        self.assertEqual(r1["summary"]["passed"], 1)
        self.assertEqual(r1["summary"]["violations"], 1)
        self.assertEqual(r1["summary"]["critical_count"], 1)

        self.assertEqual(r2["summary"]["passed"], 1)
        self.assertEqual(r2["summary"]["violations"], 1)
        self.assertEqual(r2["summary"]["warning_count"], 1)
        self.assertEqual(r2["summary"]["critical_count"], 0)


if __name__ == "__main__":
    unittest.main()
