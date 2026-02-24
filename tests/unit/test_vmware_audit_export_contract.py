import unittest


def build_sample_audit_export_payload():
    """Contract fixture mirroring the expected top-level shape from audit/tasks/export.yaml."""
    return {
        "audit_type": "vcenter_health",
        "alerts": [],
        "vcenter_health": {
            "health": {"overall": "green"},
            "summary": {"critical_count": 0, "warning_count": 0},
            "alerts": [],
            "audit_failed": False,
            "data": {},
        },
        "check_metadata": {
            "engine": "ansible-ncs-vmware",
            "timestamp": "2026-02-24T00:00:00Z",
            "thresholds": {
                "cpu_crit": 90,
                "mem_crit": 90,
                "storage_crit": 10,
            },
        },
    }


class AuditExportContractTests(unittest.TestCase):
    def test_top_level_shape(self):
        payload = build_sample_audit_export_payload()

        self.assertEqual(payload["audit_type"], "vcenter_health")
        self.assertIsInstance(payload["alerts"], list)
        self.assertIsInstance(payload["vcenter_health"], dict)
        self.assertIsInstance(payload["check_metadata"], dict)

    def test_nested_shape(self):
        payload = build_sample_audit_export_payload()
        vh = payload["vcenter_health"]

        self.assertIsInstance(vh["health"], dict)
        self.assertIsInstance(vh["summary"], dict)
        self.assertIsInstance(vh["alerts"], list)
        self.assertIs(vh["audit_failed"], False)
        self.assertIsInstance(vh["data"], dict)
        self.assertIsInstance(payload["check_metadata"]["thresholds"], dict)


if __name__ == "__main__":
    unittest.main()
