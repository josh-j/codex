import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


REPORT_TEMPLATES = [
    ROOT / "playbooks/templates/site_health_report.html.j2",
    ROOT / "collections/ansible_collections/internal/vmware/roles/summary/templates/vmware_health_report.html.j2",
    ROOT / "collections/ansible_collections/internal/vmware/roles/summary/templates/vcenter_health_report.html.j2",
    ROOT / "collections/ansible_collections/internal/linux/roles/ubuntu_summary/templates/ubuntu_health_report.html.j2",
    ROOT / "collections/ansible_collections/internal/linux/roles/ubuntu_summary/templates/ubuntu_host_health_report.html.j2",
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
            (
                ROOT
                / "collections/ansible_collections/internal/core/roles/reporting/templates/report_shared.css"
            ).exists()
        )

    def test_report_templates_do_not_reference_legacy_css(self):
        for path in REPORT_TEMPLATES:
            text = path.read_text(encoding="utf-8")
            for css_name in FORBIDDEN_CSS_NAMES:
                self.assertNotIn(css_name, text, f"{path} still references {css_name}")

    def test_report_templates_reference_core_shared_css_filter(self):
        for path in REPORT_TEMPLATES:
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "internal.core.shared_report_css",
                text,
                f"{path} does not reference internal.core.shared_report_css",
            )


if __name__ == "__main__":
    unittest.main()
