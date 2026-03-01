"""Ensure STIG role tasks do not emit legacy ncs_collect set_stats payloads."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2] / "collections" / "ansible_collections" / "internal"

STIG_TASK_FILES = [
    ROOT / "linux" / "roles" / "ubuntu" / "tasks" / "stig.yaml",
    ROOT / "vmware" / "roles" / "esxi" / "tasks" / "stig.yaml",
    ROOT / "vmware" / "roles" / "vm" / "tasks" / "stig.yaml",
]


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


class TestStigRolesNoSetStats(unittest.TestCase):
    def test_stig_roles_do_not_emit_ncs_collect(self) -> None:
        offenders: list[str] = []
        for task_file in STIG_TASK_FILES:
            for task in _load_tasks(task_file):
                uses_set_stats = "ansible.builtin.set_stats" in task or "set_stats" in task
                if not uses_set_stats:
                    continue
                serialized = str(task)
                if "ncs_collect" in serialized:
                    offenders.append(f"{task_file}: {task.get('name', '<unnamed>')}")

        self.assertFalse(
            offenders,
            "STIG roles should not emit legacy ncs_collect payloads via set_stats: "
            + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
