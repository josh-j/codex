import importlib.util
import pathlib
import unittest
from typing import Any

FILTER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "paths.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_paths_filter", FILTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CorePathFilterTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_resolve_ncs_path_defaults(self):
        config = {"report_directory": "/reports"}
        path = self.module.resolve_ncs_path(config, "ubuntu", "host01")
        self.assertEqual(path, "/reports/platform/ubuntu/host01/system.yaml")

    def test_resolve_ncs_path_fleet(self):
        config = {"report_directory": "/reports"}
        path = self.module.resolve_ncs_path(config, "fleet", audit_type="linux")
        self.assertEqual(path, "/reports/fleet/linux_fleet_state.yaml")

    def test_resolve_ncs_path_artifacts(self):
        config = {"report_directory": "/reports"}
        path = self.module.resolve_ncs_path(config, "artifacts", "host01", "discovery")
        # Should be absolute path ending in .artifacts/host01/discovery.yaml
        self.assertTrue(path.endswith(".artifacts/host01/discovery.yaml"))
        self.assertTrue(path.startswith("/"))

    def test_resolve_ncs_path_html_report(self):
        config = {"report_directory": "/reports"}
        path = self.module.resolve_ncs_path(config, "vmware", extension="html")
        self.assertEqual(path, "/reports/platform/vmware/vmware_health_report.html")


if __name__ == "__main__":
    unittest.main()
