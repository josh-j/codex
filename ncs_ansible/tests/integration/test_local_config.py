"""Integration tests verifying ncs_ansible's local schemas/ and platforms.yaml
are compatible with ncs_reporter's schema loader and platform config parser.

These tests assert that ncs_ansible can call ncs_reporter as an installed tool
with its own local configuration, without relying on ncs_reporter's bundled defaults.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from ncs_reporter.models.platforms_config import PlatformsConfig
from ncs_reporter.schema_loader import discover_schemas, load_schema_from_file

from _paths import PLATFORMS_YAML, SCHEMAS_DIR

EXPECTED_SCHEMA_NAMES = {"linux", "vcenter", "windows"}
EXPECTED_PLATFORMS = {"linux", "vmware", "windows"}


class TestPlatformsYaml(unittest.TestCase):
    """platforms.yaml must be a valid PlatformsConfig and cover all required platforms."""

    def test_platforms_yaml_exists(self) -> None:
        self.assertTrue(PLATFORMS_YAML.exists(), f"platforms.yaml not found at {PLATFORMS_YAML}")

    def test_platforms_yaml_parses_as_valid_config(self) -> None:
        raw = yaml.safe_load(PLATFORMS_YAML.read_text())
        config = PlatformsConfig(**raw)
        self.assertGreater(len(config.platforms), 0)

    def test_platforms_yaml_covers_all_required_platforms(self) -> None:
        raw = yaml.safe_load(PLATFORMS_YAML.read_text())
        config = PlatformsConfig(**raw)
        found = {p.platform for p in config.platforms}
        self.assertTrue(
            EXPECTED_PLATFORMS.issubset(found),
            f"Missing platforms: {EXPECTED_PLATFORMS - found}",
        )

    def test_all_platform_entries_have_required_fields(self) -> None:
        raw = yaml.safe_load(PLATFORMS_YAML.read_text())
        config = PlatformsConfig(**raw)
        for entry in config.platforms:
            self.assertTrue(entry.input_dir, f"Empty input_dir for platform {entry.platform}")
            self.assertTrue(entry.report_dir, f"Empty report_dir for platform {entry.platform}")
            self.assertTrue(entry.state_file, f"Empty state_file for platform {entry.platform}")


class TestLocalSchemas(unittest.TestCase):
    """Each schema YAML in ncs_ansible/schemas/ must load cleanly via ncs_reporter."""

    def test_schemas_dir_exists(self) -> None:
        self.assertTrue(SCHEMAS_DIR.exists(), f"schemas/ not found at {SCHEMAS_DIR}")

    def test_all_expected_schema_files_present(self) -> None:
        found = {p.stem for p in SCHEMAS_DIR.glob("*.yaml")}
        self.assertTrue(
            EXPECTED_SCHEMA_NAMES.issubset(found),
            f"Missing schema files: {EXPECTED_SCHEMA_NAMES - found}",
        )

    def test_linux_schema_loads(self) -> None:
        schema = load_schema_from_file(SCHEMAS_DIR / "linux.yaml")
        self.assertEqual(schema.name, "linux")
        self.assertEqual(schema.platform, "linux")

    def test_vcenter_schema_loads(self) -> None:
        schema = load_schema_from_file(SCHEMAS_DIR / "vcenter.yaml")
        self.assertEqual(schema.name, "vcenter")
        self.assertEqual(schema.platform, "vmware")

    def test_windows_schema_loads(self) -> None:
        schema = load_schema_from_file(SCHEMAS_DIR / "windows.yaml")
        self.assertEqual(schema.name, "windows")
        self.assertEqual(schema.platform, "windows")

    def test_all_schemas_have_detection_keys(self) -> None:
        for schema_file in SCHEMAS_DIR.glob("*.yaml"):
            schema = load_schema_from_file(schema_file)
            has_detection = bool(schema.detection.keys_any or schema.detection.keys_all)
            self.assertTrue(has_detection, f"{schema_file.name} has no detection keys")

    def test_all_schemas_have_at_least_one_field(self) -> None:
        for schema_file in SCHEMAS_DIR.glob("*.yaml"):
            schema = load_schema_from_file(schema_file)
            self.assertGreater(len(schema.fields), 0, f"{schema_file.name} has no fields")


class TestSchemaDiscovery(unittest.TestCase):
    """discover_schemas() must find ncs_ansible's schemas when passed as extra_dirs,
    and they must take priority over the ncs_reporter built-ins."""

    def test_extra_schema_dir_discovers_all_local_schemas(self) -> None:
        schemas = discover_schemas(extra_dirs=(str(SCHEMAS_DIR),))
        for name in EXPECTED_SCHEMA_NAMES:
            self.assertIn(name, schemas, f"Schema '{name}' not discovered from {SCHEMAS_DIR}")

    def test_local_schemas_take_priority_over_builtins(self) -> None:
        # Without extra_dirs, built-ins are used; with extra_dirs, local files win.
        builtin_schemas = discover_schemas()
        local_schemas = discover_schemas(extra_dirs=(str(SCHEMAS_DIR),))

        for name in EXPECTED_SCHEMA_NAMES:
            if name not in builtin_schemas:
                continue  # schema is ncs_ansible-only — priority not applicable
            builtin_source = getattr(builtin_schemas[name], "_source_path", None)
            local_source = getattr(local_schemas[name], "_source_path", None)
            if builtin_source and local_source:
                self.assertNotEqual(
                    builtin_source,
                    local_source,
                    f"Schema '{name}' did not switch source when extra_dirs provided",
                )
                self.assertIn(str(SCHEMAS_DIR), str(local_source))

    def test_discovered_schema_platform_names_match_platforms_config(self) -> None:
        schemas = discover_schemas(extra_dirs=(str(SCHEMAS_DIR),))
        raw = yaml.safe_load(PLATFORMS_YAML.read_text())
        config = PlatformsConfig(**raw)
        configured_platforms = {p.platform for p in config.platforms}

        for schema in schemas.values():
            if schema.name in EXPECTED_SCHEMA_NAMES:
                self.assertIn(
                    schema.platform,
                    configured_platforms,
                    f"Schema '{schema.name}' platform '{schema.platform}' not in platforms.yaml",
                )


if __name__ == "__main__":
    unittest.main()
