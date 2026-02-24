import importlib.util
import pathlib
import unittest
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "plugins"
    / "filter"
    / "discovery.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("vmware_discovery_filter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VmwareDiscoveryFilterTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_build_discovery_export_payload_sets_audit_type_and_counts(self):
        ctx = {
            "audit_type": "vcenter_health",
            "inventory": {
                "clusters": {"list": [{"name": "c1"}, {"name": "c2"}]},
                "hosts": {"list": [{"name": "h1"}]},
                "vms": {"list": [{"name": "vm1"}, {"name": "vm2"}, {"name": "vm3"}]},
            },
        }

        out = self.module.build_discovery_export_payload(ctx)

        self.assertIsNot(out, ctx)
        self.assertEqual(out["audit_type"], "discovery")
        self.assertEqual(out["summary"]["clusters"], 2)
        self.assertEqual(out["summary"]["hosts"], 1)
        self.assertEqual(out["summary"]["vms"], 3)
        self.assertEqual(ctx["audit_type"], "vcenter_health")


if __name__ == "__main__":
    unittest.main()
