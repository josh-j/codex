"""Integration tests for the ncs_collector → ncs_reporter normalization pipeline.

These tests verify that raw_*.yaml artifacts written by the ncs_collector callback
(Ansible side) can be processed by ncs_reporter's normalization layer (Python side)
using ncs_ansible's local schemas.

The artifact envelope format written by ncs_collector:
    {
        "<detection_key>": {
            "metadata": {"host": ..., "raw_type": ..., "timestamp": ..., "engine": ...},
            "data": { <module result dicts> }
        }
    }
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from ncs_reporter.normalization.schema_driven import normalize_from_schema
from ncs_reporter.schema_loader import detect_schemas_for_bundle, discover_schemas, load_schema_from_file

from _paths import SCHEMAS_DIR

_EXTRA_DIRS = (str(SCHEMAS_DIR),)

NORMALIZE_OUTPUT_KEYS = {"metadata", "health", "summary", "alerts", "fields", "widgets_meta", "schema"}


def _envelope(raw_type: str, data: dict | None = None) -> dict:
    return {
        "metadata": {
            "host": "test-host",
            "raw_type": raw_type,
            "timestamp": "2026-03-01T00:00:00Z",
            "engine": "ncs_collector_callback",
        },
        "data": data or {},
    }


class TestSchemaDetection(unittest.TestCase):
    """detect_schemas_for_bundle picks the correct schema for each platform bundle."""

    def test_linux_bundle_matches_linux_schema(self) -> None:
        bundle = {"ubuntu_raw_discovery": _envelope("ubuntu_raw_discovery")}
        matched = detect_schemas_for_bundle(bundle, extra_dirs=_EXTRA_DIRS)
        names = [s.name for s in matched]
        self.assertIn("linux", names)

    def test_vcenter_bundle_matches_vcenter_schema(self) -> None:
        bundle = {"vmware_raw_vcenter": _envelope("vmware_raw_vcenter")}
        matched = detect_schemas_for_bundle(bundle, extra_dirs=_EXTRA_DIRS)
        names = [s.name for s in matched]
        self.assertIn("vcenter", names)

    def test_windows_bundle_matches_windows_schema(self) -> None:
        bundle = {"windows_raw_audit": _envelope("windows_raw_audit")}
        matched = detect_schemas_for_bundle(bundle, extra_dirs=_EXTRA_DIRS)
        names = [s.name for s in matched]
        self.assertIn("windows", names)

    def test_empty_bundle_matches_no_schema(self) -> None:
        matched = detect_schemas_for_bundle({}, extra_dirs=_EXTRA_DIRS)
        self.assertEqual(matched, [])

    def test_unknown_key_matches_no_schema(self) -> None:
        bundle = {"totally_unknown_key": {}}
        matched = detect_schemas_for_bundle(bundle, extra_dirs=_EXTRA_DIRS)
        self.assertEqual(matched, [])


class TestNormalizeOutputStructure(unittest.TestCase):
    """normalize_from_schema returns the standard audit dict for each platform."""

    def _normalize(self, schema_name: str, bundle: dict) -> dict:
        schema = load_schema_from_file(SCHEMAS_DIR / f"{schema_name}.yaml")
        return normalize_from_schema(schema, bundle)

    def test_linux_normalize_returns_required_keys(self) -> None:
        bundle = {"ubuntu_raw_discovery": _envelope("ubuntu_raw_discovery")}
        result = self._normalize("linux", bundle)
        self.assertEqual(result.keys(), NORMALIZE_OUTPUT_KEYS)

    def test_vcenter_normalize_returns_required_keys(self) -> None:
        bundle = {"vmware_raw_vcenter": _envelope("vmware_raw_vcenter")}
        result = self._normalize("vcenter", bundle)
        self.assertEqual(result.keys(), NORMALIZE_OUTPUT_KEYS)

    def test_windows_normalize_returns_required_keys(self) -> None:
        bundle = {"windows_raw_audit": _envelope("windows_raw_audit")}
        result = self._normalize("windows", bundle)
        self.assertEqual(result.keys(), NORMALIZE_OUTPUT_KEYS)

    def test_normalize_metadata_references_local_schema(self) -> None:
        bundle = {"ubuntu_raw_discovery": _envelope("ubuntu_raw_discovery")}
        result = self._normalize("linux", bundle)
        self.assertEqual(result["metadata"]["schema_name"], "linux")
        self.assertEqual(result["metadata"]["platform"], "linux")

    def test_normalize_health_is_string(self) -> None:
        for schema_name, key in [("linux", "ubuntu_raw_discovery"), ("vcenter", "vmware_raw_vcenter"), ("windows", "windows_raw_audit")]:
            bundle = {key: _envelope(key)}
            result = self._normalize(schema_name, bundle)
            self.assertIsInstance(result["health"], str, f"{schema_name} health is not a string")

    def test_normalize_alerts_is_list(self) -> None:
        for schema_name, key in [("linux", "ubuntu_raw_discovery"), ("vcenter", "vmware_raw_vcenter"), ("windows", "windows_raw_audit")]:
            bundle = {key: _envelope(key)}
            result = self._normalize(schema_name, bundle)
            self.assertIsInstance(result["alerts"], list, f"{schema_name} alerts is not a list")

    def test_normalize_fields_is_dict(self) -> None:
        for schema_name, key in [("linux", "ubuntu_raw_discovery"), ("vcenter", "vmware_raw_vcenter"), ("windows", "windows_raw_audit")]:
            bundle = {key: _envelope(key)}
            result = self._normalize(schema_name, bundle)
            self.assertIsInstance(result["fields"], dict, f"{schema_name} fields is not a dict")

    def test_normalize_fields_contains_alert_counts(self) -> None:
        """Virtual alert count fields must always be present regardless of data."""
        for schema_name, key in [("linux", "ubuntu_raw_discovery"), ("vcenter", "vmware_raw_vcenter"), ("windows", "windows_raw_audit")]:
            bundle = {key: _envelope(key)}
            result = self._normalize(schema_name, bundle)
            fields = result["fields"]
            self.assertIn("_critical_count", fields, f"{schema_name} missing _critical_count")
            self.assertIn("_warning_count", fields, f"{schema_name} missing _warning_count")
            self.assertIn("_total_alerts", fields, f"{schema_name} missing _total_alerts")


class TestArtifactRoundTrip(unittest.TestCase):
    """Artifacts written as YAML by ncs_collector survive a disk round-trip
    and can still be normalized by ncs_reporter."""

    def _write_and_reload(self, bundle: dict, tmp_dir: Path, filename: str) -> dict:
        path = tmp_dir / filename
        path.write_text(yaml.dump(bundle, default_flow_style=False))
        return yaml.safe_load(path.read_text())

    def test_linux_artifact_survives_yaml_round_trip(self) -> None:
        bundle = {"ubuntu_raw_discovery": _envelope("ubuntu_raw_discovery")}
        with tempfile.TemporaryDirectory() as tmp:
            reloaded = self._write_and_reload(bundle, Path(tmp), "raw_ubuntu_raw_discovery.yaml")
        schema = load_schema_from_file(SCHEMAS_DIR / "linux.yaml")
        result = normalize_from_schema(schema, reloaded)
        self.assertIn("metadata", result)

    def test_vcenter_artifact_survives_yaml_round_trip(self) -> None:
        bundle = {"vmware_raw_vcenter": _envelope("vmware_raw_vcenter")}
        with tempfile.TemporaryDirectory() as tmp:
            reloaded = self._write_and_reload(bundle, Path(tmp), "raw_vmware_raw_vcenter.yaml")
        schema = load_schema_from_file(SCHEMAS_DIR / "vcenter.yaml")
        result = normalize_from_schema(schema, reloaded)
        self.assertIn("metadata", result)

    def test_windows_artifact_survives_yaml_round_trip(self) -> None:
        bundle = {"windows_raw_audit": _envelope("windows_raw_audit")}
        with tempfile.TemporaryDirectory() as tmp:
            reloaded = self._write_and_reload(bundle, Path(tmp), "raw_windows_raw_audit.yaml")
        schema = load_schema_from_file(SCHEMAS_DIR / "windows.yaml")
        result = normalize_from_schema(schema, reloaded)
        self.assertIn("metadata", result)


class TestLocalSchemaFieldCoverage(unittest.TestCase):
    """Fields defined in local schemas must resolve without errors on empty data.

    All fields must have either a fallback or gracefully return None — the schema
    must not crash normalize_from_schema when a platform provides partial data.
    """

    def test_linux_schema_fields_all_have_fallback_or_none(self) -> None:
        schema = load_schema_from_file(SCHEMAS_DIR / "linux.yaml")
        bundle = {"ubuntu_raw_discovery": _envelope("ubuntu_raw_discovery")}
        # Must not raise
        result = normalize_from_schema(schema, bundle)
        self.assertIsInstance(result["fields"], dict)

    def test_vcenter_schema_fields_all_have_fallback_or_none(self) -> None:
        schema = load_schema_from_file(SCHEMAS_DIR / "vcenter.yaml")
        bundle = {"vmware_raw_vcenter": _envelope("vmware_raw_vcenter")}
        result = normalize_from_schema(schema, bundle)
        self.assertIsInstance(result["fields"], dict)

    def test_windows_schema_fields_all_have_fallback_or_none(self) -> None:
        schema = load_schema_from_file(SCHEMAS_DIR / "windows.yaml")
        bundle = {"windows_raw_audit": _envelope("windows_raw_audit")}
        result = normalize_from_schema(schema, bundle)
        self.assertIsInstance(result["fields"], dict)


if __name__ == "__main__":
    unittest.main()
