import importlib.util
import pathlib
import unittest

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "linux"
    / "plugins"
    / "filter"
    / "audit.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("linux_audit_filter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class LinuxAuditFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_compute_audit_rollups(self):
        out = self.module.compute_audit_rollups(
            [
                {"severity": "WARNING", "category": "capacity"},
                {"severity": "CRITICAL", "category": "availability"},
                {"severity": "INFO", "category": "maintenance"},
            ]
        )
        self.assertEqual(out["health"], "CRITICAL")
        self.assertEqual(out["summary"]["total"], 3)
        self.assertEqual(out["summary"]["critical_count"], 1)
        self.assertEqual(out["summary"]["warning_count"], 1)
        self.assertEqual(out["summary"]["info_count"], 1)

    def test_build_system_audit_export_payload(self):
        ctx = {"system": {"hostname": "u1"}}
        alerts = [{"severity": "WARNING"}]
        summary = {"total": 1}
        out = self.module.build_system_audit_export_payload(ctx, alerts, "WARNING", summary)
        self.assertEqual(out["audit_type"], "system")
        self.assertFalse(out["audit_failed"])
        self.assertEqual(out["health"], "WARNING")
        self.assertEqual(out["alerts"], alerts)
        self.assertEqual(out["summary"], summary)
        self.assertEqual(out["check_metadata"]["engine"], "ansible-ncs-linux")
        self.assertIn("timestamp", out["check_metadata"])
        self.assertEqual(ctx, {"system": {"hostname": "u1"}})


if __name__ == "__main__":
    unittest.main()
