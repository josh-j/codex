import importlib.util
import pathlib
import unittest
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "windows"
    / "plugins"
    / "filter"
    / "audit.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("windows_audit_filter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WindowsAuditFilterTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_ccmexec_and_app_merge_and_metrics(self):
        base = {"services": {}, "applications": {"configmgr_apps": [{"Name": "A"}], "installed_apps": []}}
        out = self.module.set_ccmexec_running(base, True)
        out = self.module.merge_applications(out, {"installed_apps": [{"Name": "X"}, {"Name": "Y"}]})
        out = self.module.compute_application_metrics(out)

        self.assertTrue(out["services"]["ccmexec_running"])
        self.assertEqual(out["applications"]["metrics"]["configmgr_count"], 1)
        self.assertEqual(out["applications"]["metrics"]["installed_count"], 2)
        self.assertNotIn("ccmexec_running", base.get("services", {}))

    def test_set_update_results_and_empty_states(self):
        ctx = {"applications": {"apps_to_update": [{"Name": "A"}]}, "updates": {"logs": ["x"]}}
        out = self.module.set_update_results(ctx, [{"item": "A"}])
        self.assertEqual(len(out["updates"]["results"]), 1)

        empty_apps = self.module.set_empty_applications({"applications": {"configmgr_apps": [{"x": 1}]}})
        self.assertEqual(empty_apps["applications"]["metrics"]["configmgr_count"], 0)

        empty_update = self.module.set_empty_configmgr_update_state(ctx)
        self.assertEqual(empty_update["applications"]["apps_to_update"], [])
        self.assertEqual(empty_update["updates"]["results"], [])
        self.assertEqual(empty_update["updates"]["logs"], [])

    def test_build_namespace_structures(self):
        apps = self.module.build_app_inventory_structure(5, True, r"C:\Temp\Scripts", r"C:\Reports", True)
        self.assertEqual(apps["config"]["startup_delay"], 5)
        self.assertTrue(apps["config"]["skip_startup_delay"])
        self.assertEqual(apps["applications"]["configmgr_apps"], [])

        cfg = self.module.build_configmgr_update_structure(
            1,
            False,
            r"C:\Temp\Scripts",
            r"C:\Temp\Logs",
            ["Foo*"],
            True,
            False,
            "Immediate",
            "Normal",
            True,
            True,
        )
        self.assertTrue(cfg["config"]["force_update"])
        self.assertEqual(cfg["config"]["excluded_apps"], ["Foo*"])
        self.assertEqual(cfg["updates"]["results"], [])

    def test_build_windows_audit_export_payload(self):
        ctx = {
            "services": {"ccmexec_running": True},
            "applications": {
                "configmgr_apps": [{"Name": "A"}],
                "installed_apps": [{"Name": "X"}],
                "apps_to_update": [{"Name": "A"}],
                "total_apps": 5,
            },
            "updates": {"results": [{"failed": False}, {"failed": True}]},
        }
        out = self.module.build_windows_audit_export_payload(ctx, audit_failed=False)
        self.assertEqual(out["audit_type"], "windows_audit")
        self.assertFalse(out["audit_failed"])
        self.assertEqual(out["health"], "WARNING")
        self.assertEqual(out["summary"]["applications"]["total_apps"], 5)
        self.assertEqual(out["summary"]["updates"]["failed_count"], 1)
        self.assertEqual(out["check_metadata"]["engine"], "ansible-ncs-windows")
        self.assertIn("timestamp", out["check_metadata"])
        self.assertIn("windows_ctx", out)


if __name__ == "__main__":
    unittest.main()
