import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "plugins"
    / "module_utils"
    / "report_aggregation_adapter.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("vmware_report_aggregation_adapter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class VmwareReportAggregationAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_normalizes_legacy_inventory_payload(self):
        payload = {
            "inventory": {"clusters": {"list": [{"name": "A"}]}},
            "alerts": [{"severity": "WARNING"}],
            "summary": {"clusters": 1},
            "health": "WARNING",
            "vcenter_health": {
                "data": {"utilization": {"cpu_pct": 50}},
                "health": "green",
            },
        }

        audit_type, out = self.module.normalize_aggregated_report("vc01", "vcenter", payload)
        self.assertEqual(audit_type, "vcenter")
        self.assertEqual(out["audit_type"], "vcenter")
        self.assertIn("discovery", out)
        self.assertEqual(out["discovery"]["clusters"]["list"][0]["name"], "A")
        self.assertEqual(out["alerts"][0]["severity"], "WARNING")
        self.assertEqual(out["vcenter_health"]["alerts"][0]["severity"], "WARNING")
        self.assertEqual(out["vcenter_health"]["health"], "green")
        self.assertEqual(out["vcenter_health"]["data"]["utilization"]["cpu_pct"], 50)

    def test_normalizes_legacy_vmware_ctx_payload(self):
        payload = {
            "vmware_ctx": {"inventory": {"ignored": True}},
            "alerts": "not-a-list",
            "vcenter_health": "not-a-dict",
            "health": "OK",
        }

        _, out = self.module.normalize_aggregated_report("vc01", "discovery", payload)
        self.assertEqual(out["discovery"], {"inventory": {"ignored": True}})
        self.assertEqual(out["alerts"], [])
        self.assertEqual(out["vcenter_health"]["alerts"], [])
        self.assertEqual(out["vcenter_health"]["data"], {})
        self.assertEqual(out["vcenter_health"]["health"], "OK")

    def test_leaves_non_legacy_shapes_unchanged(self):
        payload = {"discovery": {"summary": {}}, "vcenter_health": {"health": "green"}}
        _, out = self.module.normalize_aggregated_report("vc01", "vcenter", payload)
        self.assertEqual(out, payload)

    def test_ignores_non_vmware_audit_types(self):
        payload = {"inventory": {"foo": "bar"}}
        audit_type, out = self.module.normalize_aggregated_report("host1", "system", payload)
        self.assertEqual(audit_type, "system")
        self.assertEqual(out, payload)


if __name__ == "__main__":
    unittest.main()
