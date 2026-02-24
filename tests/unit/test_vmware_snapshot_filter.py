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
    / "filter"
    / "snapshot.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("vmware_snapshot_filter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class SnapshotFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_enrich_snapshots_decodes_name_and_adds_owner(self):
        snapshots = [{"vm_name": "vm-01", "name": "snap%20one", "size_gb": "12.5"}]

        result = self.module.enrich_snapshots(snapshots, {"vm-01": "owner@example.com"})

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["snapshot_name"], "snap one")
        self.assertEqual(result[0]["owner_email"], "owner@example.com")
        self.assertEqual(result[0]["size_gb"], 12.5)

    def test_enrich_snapshots_applies_safe_defaults(self):
        result = self.module.enrich_snapshots([{}])

        self.assertEqual(result[0]["vm_name"], "unknown")
        self.assertEqual(result[0]["snapshot_name"], "unnamed")
        self.assertEqual(result[0]["owner_email"], "")
        self.assertEqual(result[0]["size_gb"], 0.0)


if __name__ == "__main__":
    unittest.main()
