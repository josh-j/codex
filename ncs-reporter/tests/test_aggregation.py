import os
import tempfile
import unittest
from pathlib import Path

import yaml

from ncs_reporter.aggregation import (
    deep_merge,
    load_all_reports,
    normalize_host_bundle,
    read_report,
    write_output,
)
from ncs_reporter.schema_loader import discover_schemas


class DeepMergeTests(unittest.TestCase):
    def test_merges_nested_dicts(self):
        target = {"a": {"b": 1, "c": 2}}
        source = {"a": {"d": 3}}
        result = deep_merge(target, source)
        self.assertEqual(result["a"], {"b": 1, "c": 2, "d": 3})

    def test_combines_lists_without_duplicates(self):
        target = {"items": [1, 2, 3]}
        source = {"items": [3, 4, 5]}
        result = deep_merge(target, source)
        self.assertEqual(result["items"], [1, 2, 3, 4, 5])

    def test_overwrites_scalars(self):
        target = {"name": "old", "count": 1}
        source = {"name": "new", "count": 2}
        result = deep_merge(target, source)
        self.assertEqual(result["name"], "new")
        self.assertEqual(result["count"], 2)

    def test_adds_new_keys(self):
        target = {"a": 1}
        source = {"b": 2}
        result = deep_merge(target, source)
        self.assertEqual(result, {"a": 1, "b": 2})

    def test_returns_mutated_target(self):
        target = {"a": 1}
        result = deep_merge(target, {"b": 2})
        self.assertIs(result, target)


class ReadReportTests(unittest.TestCase):
    def test_reads_valid_report(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"data": {"audit_type": "discovery", "alerts": []}, "metadata": {"ts": "now"}}, f)
            path = f.name
        try:
            raw, merged, audit_type = read_report(path)
            assert merged is not None
            assert audit_type is not None
            self.assertEqual(audit_type, "discovery")
            # merged is now the full raw document — data is NOT unwrapped
            self.assertIn("data", merged)
            self.assertIn("alerts", merged["data"])
            self.assertIn("metadata", merged)
        finally:
            os.remove(path)

    def test_reads_flat_report_without_data_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"audit_type": "health", "status": "OK"}, f)
            path = f.name
        try:
            raw, merged, audit_type = read_report(path)
            assert merged is not None
            assert audit_type is not None
            self.assertEqual(audit_type, "health")
            self.assertEqual(merged["status"], "OK")
        finally:
            os.remove(path)

    def test_returns_none_for_non_dict(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("just a string\n")
            path = f.name
        try:
            raw, merged, audit_type = read_report(path)
            self.assertIsNone(raw)
        finally:
            os.remove(path)

    def test_audit_type_fallback_to_filename(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, prefix="vcenter_health_") as f:
            yaml.dump({"data": {"status": "ok"}}, f)
            path = f.name
        try:
            _raw, _merged, audit_type = read_report(path)
            assert audit_type is not None
            self.assertIn("vcenter_health", audit_type)
        finally:
            os.remove(path)

    def test_merges_top_level_health_summary_alerts(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {
                    "data": {"audit_type": "test"},
                    "health": "OK",
                    "summary": {"total": 1},
                    "alerts": [{"sev": "WARNING"}],
                },
                f,
            )
            path = f.name
        try:
            _raw, merged, _audit_type = read_report(path)
            assert merged is not None
            self.assertEqual(merged["health"], "OK")
            self.assertEqual(merged["summary"]["total"], 1)
            self.assertEqual(len(merged["alerts"]), 1)
        finally:
            os.remove(path)


class LoadAllReportsTests(unittest.TestCase):
    def _create_report_tree(self, base_dir, structure):
        """Create a directory structure with YAML reports.

        structure: {hostname: {filename: content}}
        """
        for hostname, files in structure.items():
            host_dir = os.path.join(base_dir, hostname)
            os.makedirs(host_dir, exist_ok=True)
            for filename, content in files.items():
                with open(os.path.join(host_dir, filename), "w") as f:
                    yaml.dump(content, f)

    def test_aggregates_host_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Fleet stats are populated from normalized outputs (summary at top level),
            # not from raw files (summary inside data). Use normalized-style fixtures.
            self._create_report_tree(
                tmpdir,
                {
                    "host1": {
                        "discovery.yaml": {
                            "audit_type": "discovery",
                            "summary": {"critical_count": 1, "warning_count": 2},
                        }
                    },
                    "host2": {
                        "audit.yaml": {
                            "audit_type": "audit",
                            "summary": {"critical_count": 0, "warning_count": 1},
                        }
                    },
                },
            )
            result = load_all_reports(tmpdir)
            assert result is not None
            self.assertEqual(result["metadata"]["fleet_stats"]["total_hosts"], 2)
            self.assertIn("host1", result["hosts"])
            self.assertIn("host2", result["hosts"])
            self.assertEqual(result["metadata"]["fleet_stats"]["critical_alerts"], 1)
            self.assertEqual(result["metadata"]["fleet_stats"]["warning_alerts"], 3)

    def test_audit_filter_limits_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_report_tree(
                tmpdir,
                {
                    "host1": {
                        "discovery.yaml": {"data": {"audit_type": "discovery"}},
                        "health.yaml": {"data": {"audit_type": "health"}},
                    }
                },
            )
            result = load_all_reports(tmpdir, audit_filter="discovery")
            assert result is not None
            host_data = result["hosts"]["host1"]
            # Filtered to only discovery; health should not be present
            self.assertIn("discovery", host_data)
            self.assertNotIn("health", host_data)

    def test_nonexistent_dir_returns_none(self):
        result = load_all_reports("/tmp/nonexistent_dir_12345")
        self.assertIsNone(result)

    def test_excludes_fleet_state_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_report_tree(
                tmpdir,
                {
                    "host1": {"report.yaml": {"data": {"audit_type": "test"}}},
                },
            )
            # Create a file that should be excluded
            with open(os.path.join(tmpdir, "host1", "vmware_fleet_state.yaml"), "w") as f:
                yaml.dump({"should": "be_excluded"}, f)
            result = load_all_reports(tmpdir)
            assert result is not None
            self.assertNotIn("should", result["hosts"].get("host1", {}))

    def test_normalizer_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._create_report_tree(
                tmpdir,
                {
                    "host1": {"report.yaml": {"data": {"audit_type": "raw", "value": 1}}},
                },
            )

            def my_normalizer(hostname, audit_type, report):
                report["normalized"] = True
                return "normalized_type", report

            result = load_all_reports(tmpdir, normalizer=my_normalizer)
            assert result is not None
            # Normalizer renames audit_type to "normalized_type"; data stored under that key
            self.assertIn("normalized_type", result["hosts"]["host1"])
            self.assertTrue(result["hosts"]["host1"]["normalized_type"].get("normalized"))


class WriteOutputTests(unittest.TestCase):
    def test_writes_yaml_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "sub", "output.yaml")
            data = {"hosts": {"h1": {"status": "ok"}}}
            write_output(data, path)
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                loaded = yaml.safe_load(f)
            self.assertEqual(loaded["hosts"]["h1"]["status"], "ok")

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "a", "b", "c", "output.yaml")
            write_output({"test": True}, path)
            self.assertTrue(os.path.exists(path))


class NormalizeHostBundleExtraDirsTests(unittest.TestCase):
    """``normalize_host_bundle`` must honor ``extra_dirs`` so the ``all``
    pipeline can attach ``schema_<name>`` keys when schemas come from
    ``--config-dir`` rather than ``$NCS_REPORTER_CONFIG_DIR`` / cwd. Without
    this, the site dashboard's per-platform widgets stay empty even when
    raw bundles are present."""

    def setUp(self) -> None:
        # Each test installs a custom schema dir that's NOT in the env-var
        # path, so we can prove the extra_dirs param is what made detection
        # succeed. lru_cache must be cleared because the env-var path was
        # already primed by conftest.
        discover_schemas.cache_clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(discover_schemas.cache_clear)
        schema_path = Path(self._tmp.name) / "myproduct.yaml"
        schema_path.write_text(
            "config:\n"
            "  display_name: My Product\n"
            "  platform: myproduct\n"
        )

    def test_extra_dirs_attaches_schema_key(self) -> None:
        bundle = {"raw_myproduct": {"data": {"hostname": "h-01"}}}

        # Without extra_dirs the schema isn't visible — env var path doesn't
        # know about /tmp/.../myproduct.yaml — and no schema_* key lands.
        plain = normalize_host_bundle("h-01", bundle)
        self.assertNotIn("schema_myproduct", plain)

        # Threading the same dir as extra_dirs makes detection succeed.
        with_extras = normalize_host_bundle(
            "h-01", bundle, extra_dirs=(self._tmp.name,)
        )
        self.assertIn("schema_myproduct", with_extras)


if __name__ == "__main__":
    unittest.main()
