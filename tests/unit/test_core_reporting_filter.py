import pathlib
import sys
import unittest

_NCS_SRC = str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src")
if _NCS_SRC not in sys.path:
    sys.path.insert(0, _NCS_SRC)

TEMPLATES_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src" / "ncs_reporter" / "templates"
)

from ncs_reporter.view_models.common import default_report_skip_keys  # noqa: E402


class CoreReportingFilterTests(unittest.TestCase):
    def test_shared_report_css_exists_in_templates(self):
        css_path = TEMPLATES_DIR / "report_shared.css"
        self.assertTrue(css_path.exists(), f"report_shared.css not found at {css_path}")
        css = css_path.read_text(encoding="utf-8")
        self.assertGreater(len(css), 0, "report_shared.css is empty")

    def test_report_skip_keys_contains_canonical_entries(self):
        keys = default_report_skip_keys()
        self.assertIn("Summary", keys)
        self.assertIn("Split", keys)
        self.assertIn("platform", keys)
        self.assertIn("history", keys)
        self.assertIn("linux_fleet_state.yaml", keys)
        self.assertIn("vmware_fleet_state.yaml", keys)


if __name__ == "__main__":
    unittest.main()
