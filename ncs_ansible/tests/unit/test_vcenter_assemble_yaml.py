"""Structural tests for vcenter/tasks/assemble.yaml payload canonicalization."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

ASSEMBLE_YAML = (
    Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "roles"
    / "vcenter"
    / "tasks"
    / "assemble.yaml"
)


def _load() -> list[dict[str, Any]]:
    raw = yaml.safe_load(ASSEMBLE_YAML.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


class TestVcenterAssembleYaml(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = _load()

    def test_has_normalize_task(self) -> None:
        normalize = next(
            (t for t in self.tasks if t.get("name") == "Normalize raw vCenter module payloads"),
            None,
        )
        self.assertIsNotNone(normalize, "Missing payload normalization task in assemble.yaml")

    def test_normalize_task_sets_unwrapped_facts(self) -> None:
        normalize = next(
            (t for t in self.tasks if t.get("name") == "Normalize raw vCenter module payloads"),
            {},
        )
        fact_map = normalize.get("ansible.builtin.set_fact", {})
        expected = {
            "_raw_appliance_health_unwrapped",
            "_raw_appliance_backup_unwrapped",
            "_raw_datacenters_unwrapped",
            "_raw_clusters_unwrapped",
            "_raw_datastores_unwrapped",
            "_raw_vms_unwrapped",
            "_raw_snapshots_unwrapped",
            "_raw_alarms_unwrapped",
        }
        self.assertTrue(expected.issubset(set(fact_map.keys())), "Normalization facts are incomplete")

    def test_vmware_raw_vcenter_has_canonical_top_level_keys(self) -> None:
        assemble = next(
            (t for t in self.tasks if t.get("name") == "Assemble raw vCenter context"),
            {},
        )
        fact_map = assemble.get("ansible.builtin.set_fact", {})
        vmware_raw = fact_map.get("vmware_raw_vcenter", {})
        self.assertIsInstance(vmware_raw, dict)
        self.assertNotIn("metadata", vmware_raw)
        self.assertNotIn("data", vmware_raw)

        required = {
            "appliance_health_info",
            "appliance_backup_info",
            "datacenters_info",
            "clusters_info",
            "datastores_info",
            "vms_info",
            "snapshots_info",
            "alarms_info",
            "config",
            "collection_status",
            "collection_error",
        }
        self.assertTrue(required.issubset(set(vmware_raw.keys())), "vmware_raw_vcenter shape is incomplete")

    def test_assemble_uses_unwrapped_facts_for_primary_inputs(self) -> None:
        assemble = next(
            (t for t in self.tasks if t.get("name") == "Assemble raw vCenter context"),
            {},
        )
        fact_map = assemble.get("ansible.builtin.set_fact", {})
        vmware_raw = fact_map.get("vmware_raw_vcenter", {})
        self.assertIn("_raw_appliance_health_unwrapped", str(vmware_raw.get("appliance_health_info", "")))
        self.assertIn("_raw_appliance_backup_unwrapped", str(vmware_raw.get("appliance_backup_info", "")))
        self.assertIn("_raw_datacenters_unwrapped", str(vmware_raw.get("datacenters_info", "")))
        self.assertIn("_raw_clusters_unwrapped", str(vmware_raw.get("clusters_info", "")))
        self.assertIn("_raw_vms_unwrapped", str(vmware_raw.get("vms_info", "")))
        self.assertIn("_raw_alarms_unwrapped", str(vmware_raw.get("alarms_info", "")))


if __name__ == "__main__":
    unittest.main()
