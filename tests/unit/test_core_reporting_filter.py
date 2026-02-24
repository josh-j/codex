import importlib.util
import os
import pathlib
import tempfile
import unittest

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "reporting.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_reporting_filter", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class CoreReportingFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def setUp(self):
        # Reset module cache between tests
        self.module._SHARED_CSS_CACHE = None
        self.module._SHARED_CSS_MTIME_NS = None
        self.module._SHARED_CSS_RESOLVED_PATH = None
        os.environ.pop("NCS_SHARED_REPORT_CSS_PATH", None)

    def test_shared_report_css_uses_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            css_path = pathlib.Path(tmp) / "custom.css"
            css_path.write_text("body { color: red; }\n", encoding="utf-8")
            os.environ["NCS_SHARED_REPORT_CSS_PATH"] = str(css_path)

            css = self.module.shared_report_css("")

            self.assertIn("color: red", css)

    def test_shared_report_css_missing_path_has_clear_error(self):
        os.environ["NCS_SHARED_REPORT_CSS_PATH"] = "/definitely/missing/report_shared.css"
        original_default = self.module._DEFAULT_SHARED_CSS_PATH
        self.module._DEFAULT_SHARED_CSS_PATH = pathlib.Path("/also/missing/report_shared.css")
        try:
            with self.assertRaises(RuntimeError) as ctx:
                self.module.shared_report_css("")
            self.assertIn("could not locate report_shared.css", str(ctx.exception))
            self.assertIn("Searched:", str(ctx.exception))
        finally:
            self.module._DEFAULT_SHARED_CSS_PATH = original_default

    def test_report_skip_keys_contains_canonical_entries(self):
        keys = self.module.report_skip_keys("")
        self.assertIn("Summary", keys)
        self.assertIn("Split", keys)
        self.assertIn("platform", keys)
        self.assertIn("history", keys)
        self.assertIn("linux_fleet_state.yaml", keys)
        self.assertIn("vmware_fleet_state.yaml", keys)


if __name__ == "__main__":
    unittest.main()
