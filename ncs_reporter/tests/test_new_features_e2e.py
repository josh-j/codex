"""End-to-End tests for new reporting features (Search, Sort, Widgets, Print)."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import main


class TestNewFeaturesE2E(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Setup telemetry lake structure
        self.platform_root = self.root / "platform"
        self.reports_root = self.root / "reports"

        # 1. Custom Schema with new features
        self.schema_dir = self.root / "schemas"
        self.schema_dir.mkdir(parents=True)

        advanced_schema = {
            "name": "adv_test",
            "platform": "test",  # changed from linux to test
            "display_name": "Advanced Test",
            "detection": {"keys_any": ["raw_adv"]},
            "fields": {
                "usage": {"path": "raw_adv.data.usage", "type": "percentage"},
                "note": {"path": "raw_adv.data.note", "type": "str"},
            },
            "widgets": [
                {"id": "p1", "title": "Usage", "type": "progress_bar", "field": "usage", "layout": {"width": "half"}},
                {"id": "m1", "title": "Info", "type": "markdown", "content": "Hello **World**"},
            ],
            "fleet_columns": [{"label": "Usage", "field": "usage"}],
        }
        with open(self.schema_dir / "adv_test.yaml", "w") as f:
            yaml.dump(advanced_schema, f)

        # 2. Host data matching custom schema
        # Directory must be <platform_root>/<platform_name>/<hostname>
        self.host_dir = self.platform_root / "test" / "host-01"
        self.host_dir.mkdir(parents=True)
        # raw_adv.yaml -> keyed as 'raw_adv' in the bundle
        host_data = {
            "metadata": {"host": "host-01", "timestamp": "2026-02-26T23:00:00Z"},
            "data": {"usage": 75.5, "note": "all good"},
        }
        with open(self.host_dir / "raw_adv.yaml", "w") as f:
            yaml.dump(host_data, f)

        # 3. Inventory Groups
        groups = {"all": ["host-01"], "adv_servers": ["host-01"]}
        with open(self.platform_root / "inventory_groups.json", "w") as f:
            json.dump(groups, f)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_new_features_integration(self):
        """Verify global search index, sorting markers, and new widgets are in the output."""

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(self.platform_root / "inventory_groups.json"),
                "--extra-config-dir",
                str(self.schema_dir),
            ],
        )

        self.assertEqual(result.exit_code, 0, f"CLI failed: {result.output}")

        # 1. Verify Global Search Index
        search_index_js = self.reports_root / "search_index.js"
        self.assertTrue(search_index_js.exists(), "search_index.js should be generated")
        index_content = search_index_js.read_text()
        self.assertIn("host-01", index_content)
        self.assertIn("window.NCS_SEARCH_INDEX =", index_content)

        # 2. Verify Search Bar in HTML
        site_report = (self.reports_root / "site_health_report.html").read_text()
        self.assertIn('class="nav-search"', site_report)
        self.assertIn('data-root="./"', site_report)
        self.assertIn('class="search-results', site_report)

        # 3. Verify Sortable Headers
        self.assertIn('class="sortable"', site_report, "Tables should have sortable headers")

        # 4. Verify Print Link
        self.assertIn("Print report", site_report, "TOC should contain print action")

        # 5. Verify New Widgets in Node Report
        node_report = (self.reports_root / "platform" / "test" / "host-01" / "health_report.html").read_text()

        # Progress Bar (check for percentage — minifier may remove spaces)
        self.assertIn("75.5%", node_report)
        self.assertTrue(
            'style="width: 75.5%' in node_report or 'width:75.5%' in node_report,
            "Progress bar width style must be present in minified or unminified form",
        )

        # Markdown
        self.assertIn("Hello **World**", node_report)

        # Layout (flex-basis check — minifier may simplify style values)
        self.assertTrue(
            "flex: 1 1 calc(50% - 7px)" in node_report or "flex:calc(50% - 7px)" in node_report,
            "Half-width layout flex style must be present in minified or unminified form",
        )

        # data-root calculation for nested node report (minifier may strip quotes)
        self.assertTrue(
            'data-root="../../../"' in node_report or 'data-root=../../../>' in node_report,
            "data-root attribute must reference site root (3 levels up)",
        )
