import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "tools" / "ncs_reporter" / "src" / "ncs_reporter" / "templates"

REPORT_TEMPLATES = [
    TEMPLATES_DIR / "site_health_report.html.j2",
    TEMPLATES_DIR / "vmware_health_report.html.j2",
    TEMPLATES_DIR / "vcenter_health_report.html.j2",
    TEMPLATES_DIR / "ubuntu_health_report.html.j2",
    TEMPLATES_DIR / "ubuntu_host_health_report.html.j2",
    ROOT / "collections/ansible_collections/internal/core/roles/stig/templates/stig_report.html.j2",
]

FORBIDDEN_CSS_NAMES = (
    "report_styles.css",
    "vmware_report_styles.css",
    "ubuntu_report_styles.css",
)


class ReportCssSingleSourceTests(unittest.TestCase):
    def test_shared_stylesheet_exists(self):
        self.assertTrue(
            (TEMPLATES_DIR / "report_shared.css").exists()
        )

    def test_report_templates_do_not_reference_legacy_css(self):
        for path in REPORT_TEMPLATES:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            for css_name in FORBIDDEN_CSS_NAMES:
                self.assertNotIn(css_name, text, f"{path} still references {css_name}")

    def test_ncs_reporter_templates_include_shared_css(self):
        for path in REPORT_TEMPLATES:
            if not path.exists():
                continue
            if TEMPLATES_DIR not in path.parents:
                continue
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "report_shared.css",
                text,
                f"{path.name} does not include report_shared.css",
            )


if __name__ == "__main__":
    unittest.main()
