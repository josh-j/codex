"""Structural tests for vCenter simulation-mode task wiring."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

V_CENTER_TASKS = (
    Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "roles"
    / "vcenter"
    / "tasks"
)

V_CENTER_DEFAULTS = (
    Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "roles"
    / "vcenter"
    / "defaults"
    / "main.yaml"
)


def _load_yaml(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


class TestVcenterSimulationWiring(unittest.TestCase):
    def test_defaults_expose_simulation_knobs(self) -> None:
        defaults = yaml.safe_load(V_CENTER_DEFAULTS.read_text(encoding="utf-8"))
        self.assertIsInstance(defaults, dict)
        self.assertIn("simulation_mode", defaults)
        self.assertIn("simulation_vcenter_fixture_root", defaults)
        self.assertIn("simulation_vcenter_fixture_file", defaults)

    def test_collect_includes_simulated_tasks(self) -> None:
        tasks = _load_yaml(V_CENTER_TASKS / "collect.yaml")
        include_task = None
        for task in tasks:
            block = task.get("block")
            if isinstance(block, list):
                include_task = next((t for t in block if t.get("name") == "Collect | Simulated vCenter State"), None)
                if include_task is not None:
                    break
        self.assertIsNotNone(include_task, "collect.yaml must include simulation task path")
        include_target = include_task.get("ansible.builtin.include_tasks") if isinstance(include_task, dict) else None
        self.assertEqual(include_target, "collect/simulated.yaml")

    def test_preflight_reachability_is_disabled_for_simulation(self) -> None:
        tasks = _load_yaml(V_CENTER_TASKS / "preflight.yaml")
        reachability = next((t for t in tasks if t.get("name") == "Check vCenter reachability"), None)
        self.assertIsNotNone(reachability, "preflight must define reachability check task")
        when_clause = str(reachability.get("when", ""))
        self.assertIn("simulation_mode", when_clause)
        self.assertIn("not", when_clause)


if __name__ == "__main__":
    unittest.main()
