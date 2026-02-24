import importlib.util
import pathlib
import unittest
from typing import Any

CORE_FILTER_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
)


def _load_module(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, CORE_FILTER_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_stig_export_payload(stig_mod, alerts_mod, rows, target_type, host="host01"):
    normalized = stig_mod.normalize_stig_results(rows, target_type)
    alerts = normalized["alerts"]
    return {
        "audit_type": "stig",
        "audit_failed": False,
        "host": host,
        "target_type": target_type,
        "checked_at": "2026-02-24T00:00:00Z",
        "health": alerts_mod.health_rollup(alerts),
        "summary": dict(normalized["summary"]),
        "alerts": list(alerts),
        "violations": list(normalized["violations"]),
        "full_audit": list(normalized["full_audit"]),
    }


class StigExportContractTests(unittest.TestCase):
    alerts_mod: Any
    stig_mod: Any
    @classmethod
    def setUpClass(cls):
        cls.stig_mod = _load_module("core_stig_filter", "stig.py")
        cls.alerts_mod = _load_module("core_alerts_filter", "alerts.py")

    def assert_stig_export_shape(self, payload):
        self.assertEqual(payload["audit_type"], "stig")
        self.assertIsInstance(payload["audit_failed"], bool)
        self.assertIsInstance(payload["host"], str)
        self.assertIsInstance(payload["target_type"], str)
        self.assertIsInstance(payload["checked_at"], str)
        self.assertIsInstance(payload["health"], str)
        self.assertIn(payload["health"], {"HEALTHY", "WARNING", "CRITICAL"})
        self.assertIsInstance(payload["summary"], dict)
        self.assertIsInstance(payload["alerts"], list)
        self.assertIsInstance(payload["violations"], list)
        self.assertIsInstance(payload["full_audit"], list)

        for key in ("total", "violations", "passed", "critical_count", "warning_count"):
            self.assertIn(key, payload["summary"])
            self.assertIsInstance(payload["summary"][key], int)

    def test_linux_vmware_windows_fixtures_share_export_contract_shape(self):
        linux_rows = [
            {
                "id": "UBTU-1",
                "status": "PASS",
                "title": "Package integrity check",
                "severity": "CAT_II",
                "details": "Compliant",
            },
            {
                "id": "UBTU-2",
                "status": "FAILED",
                "title": "SSH root login disabled",
                "severity": "CAT_I",
                "details": "PermitRootLogin yes",
            },
        ]
        vmware_rows = [
            {
                "id": "VMCH-70-000001",
                "name": "vm-app-01",
                "uuid": "1234",
                "status": "failed",
                "severity": "high",
                "title": "Copy operations must be disabled",
                "checktext": "extraConfig key not set",
            },
            {
                "id": "VMCH-70-000002",
                "name": "vm-app-01",
                "uuid": "1234",
                "status": "pass",
                "severity": "medium",
                "title": "Drag and drop operations must be disabled",
            },
        ]
        windows_rows = [
            {
                "id": "WN-SRV-000001",
                "title": "RDP must require Network Level Authentication (NLA)",
                "severity": "CAT_II",
                "status": "PASS",
                "details": "UserAuthentication=1",
            },
            {
                "id": "WN-SRV-000002",
                "title": "Windows Firewall must be enabled for all profiles",
                "severity": "CAT_I",
                "status": "FAILED",
                "details": "Disabled profiles: Public",
            },
        ]

        payloads = [
            _build_stig_export_payload(self.stig_mod, self.alerts_mod, linux_rows, "ubuntu2404", host="ubuntu01"),
            _build_stig_export_payload(self.stig_mod, self.alerts_mod, vmware_rows, "vm", host="vcenter01"),
            _build_stig_export_payload(
                self.stig_mod,
                self.alerts_mod,
                windows_rows,
                "windows_server_2022",
                host="win01",
            ),
        ]

        for payload in payloads:
            self.assert_stig_export_shape(payload)
            self.assertEqual(payload["summary"]["total"], 2)
            self.assertEqual(payload["summary"]["violations"], 1)
            self.assertEqual(payload["summary"]["passed"], 1)
            self.assertEqual(payload["summary"]["critical_count"], 1)
            self.assertEqual(payload["summary"]["warning_count"], 0)
            self.assertEqual(payload["health"], "CRITICAL")
            self.assertEqual(len(payload["alerts"]), 1)
            self.assertEqual(len(payload["violations"]), 1)
            self.assertEqual(payload["alerts"][0]["detail"]["target_type"], payload["target_type"])

    def test_windows_and_vmware_variant_status_fields_still_match_contract(self):
        vmware_variant = [
            {
                "vuln_id": "V-ESXI-001",
                "rule_title": "SSH banner configured",
                "finding_status": "Open",
                "cat": "CAT_II",
                "finding_details": "Banner missing",
            }
        ]
        windows_variant = [
            {
                "rule_id": "WN-SRV-999999",
                "title": "Sample rule",
                "result": "notafinding",
                "severity_override": "HIGH",
            }
        ]

        vmware_payload = _build_stig_export_payload(self.stig_mod, self.alerts_mod, vmware_variant, "esxi")
        windows_payload = _build_stig_export_payload(self.stig_mod, self.alerts_mod, windows_variant, "windows")

        self.assert_stig_export_shape(vmware_payload)
        self.assert_stig_export_shape(windows_payload)

        self.assertEqual(vmware_payload["summary"]["violations"], 1)
        self.assertEqual(vmware_payload["health"], "WARNING")
        self.assertEqual(windows_payload["summary"]["violations"], 0)
        self.assertEqual(windows_payload["health"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
