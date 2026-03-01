"""Structural YAML tests for the internal.vmware.vm role task files.

Mirrors test_esxi_role_yaml.py for the vm role. The same class of bugs
that affected esxi (missing module_defaults, failed_when: false silencing
connection failures) must not regress here.

vm_v7r4.yaml uses community.vmware.vmware_vm_info and community.vmware.vmware_guest —
both are covered by the group/community.vmware.vmware module_defaults.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

VM_TASKS = (
    Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "roles"
    / "vm"
    / "tasks"
)

VMWARE_GROUP_KEY = "group/community.vmware.vmware"
REQUIRED_CREDENTIAL_PARAMS = ("hostname", "username", "password", "validate_certs")


def _load(filename: str) -> list[dict[str, Any]]:
    raw = yaml.safe_load((VM_TASKS / filename).read_text())
    return raw if isinstance(raw, list) else []


# ---------------------------------------------------------------------------
# main.yaml: module_defaults
# ---------------------------------------------------------------------------


class TestVmMainYamlModuleDefaults(unittest.TestCase):
    """vm/tasks/main.yaml must declare module_defaults for the vmware group.

    community.vmware.vmware_vm_info and community.vmware.vmware_guest (used in
    vm_v7r4.yaml) require hostname/username/password. Without module_defaults
    every STIG task fails with 'missing required arguments: hostname'.
    """

    def setUp(self) -> None:
        self.tasks = _load("main.yaml")
        self.dispatcher = next((t for t in self.tasks if "module_defaults" in t), None)

    def test_dispatcher_task_has_module_defaults(self) -> None:
        self.assertIsNotNone(
            self.dispatcher,
            "main.yaml has no task with module_defaults. "
            "All community.vmware modules need hostname/username/password injected "
            "via module_defaults: {group/community.vmware.vmware: {...}}",
        )

    def test_module_defaults_covers_vmware_group(self) -> None:
        self.assertIsNotNone(self.dispatcher)
        md: dict[str, Any] = self.dispatcher["module_defaults"]  # type: ignore[index]
        self.assertIn(
            VMWARE_GROUP_KEY,
            md,
            f"module_defaults must include '{VMWARE_GROUP_KEY}'. "
            "Per-module keys won't cover vmware_vm_info and vmware_guest together.",
        )

    def test_module_defaults_has_all_credential_params(self) -> None:
        self.assertIsNotNone(self.dispatcher)
        group_defaults: dict[str, Any] = (
            self.dispatcher["module_defaults"].get(VMWARE_GROUP_KEY, {})  # type: ignore[index]
        )
        missing = [p for p in REQUIRED_CREDENTIAL_PARAMS if p not in group_defaults]
        self.assertFalse(
            missing,
            f"module_defaults['{VMWARE_GROUP_KEY}'] is missing: {missing}. "
            "Modules will raise 'missing required arguments' at runtime.",
        )

    def test_include_tasks_is_inside_block(self) -> None:
        """module_defaults only propagate to tasks inside the same block scope."""
        self.assertIsNotNone(self.dispatcher)
        self.assertIn(
            "block",
            self.dispatcher,  # type: ignore[arg-type]
            "include_tasks must be nested inside block: alongside module_defaults.",
        )
        block: list[dict[str, Any]] = self.dispatcher["block"]  # type: ignore[index]
        has_include = any(
            "ansible.builtin.include_tasks" in t or "include_tasks" in t for t in block
        )
        self.assertTrue(has_include, "block: inside the dispatcher task has no include_tasks.")


# ---------------------------------------------------------------------------
# check.yaml: error handling
# ---------------------------------------------------------------------------


class TestVmCheckYamlErrorHandling(unittest.TestCase):
    """vm/tasks/check.yaml must propagate per-VM failures.

    failed_when: false on the VM loop silently discards connection errors and
    makes remediation appear successful when no VM was actually changed.
    """

    def setUp(self) -> None:
        self.tasks = _load("check.yaml")
        self.vm_loop = next(
            (t for t in self.tasks if "vm_stig_target_vms" in str(t.get("loop", ""))),
            None,
        )

    def test_vm_loop_task_exists(self) -> None:
        self.assertIsNotNone(
            self.vm_loop,
            "Could not locate the vm_stig_target_vms loop task in check.yaml.",
        )

    def test_vm_loop_does_not_suppress_failures(self) -> None:
        self.assertIsNotNone(self.vm_loop)
        self.assertIsNot(
            self.vm_loop.get("failed_when"),  # type: ignore[union-attr]
            False,
            "failed_when: false on the VM loop silently discards connection errors. "
            "Remove it so host failures fail the play.",
        )

    def test_audit_complete_flag_is_set(self) -> None:
        flag_task = next(
            (
                t
                for t in self.tasks
                if "ansible.builtin.set_fact" in t or "set_fact" in t
            ),
            None,
        )
        self.assertIsNotNone(
            flag_task,
            "check.yaml should set a completion flag (set_fact) after the VM loop.",
        )


# ---------------------------------------------------------------------------
# vm_v7r4.yaml: no inline credentials
# ---------------------------------------------------------------------------


class TestVmV7r4NoInlineCredentials(unittest.TestCase):
    """community.vmware module calls in vm_v7r4.yaml must not embed credentials inline.

    vmware_vm_info and vmware_guest both need hostname/username/password, but
    these must come from module_defaults in main.yaml — not hardcoded per-task.
    Inline credentials would mean module_defaults could be removed without any
    test catching the regression.
    """

    VMWARE_MODULES = (
        "community.vmware.vmware_vm_info",
        "community.vmware.vmware_guest",
        "community.vmware.vmware_guest_facts",
    )

    def setUp(self) -> None:
        all_tasks = _load("vm_v7r4.yaml")
        self.vmware_tasks = [
            t
            for t in all_tasks
            if isinstance(t, dict) and any(m in t for m in self.VMWARE_MODULES)
        ]

    def test_has_vmware_module_tasks(self) -> None:
        self.assertGreater(
            len(self.vmware_tasks),
            0,
            "No community.vmware module tasks found in vm_v7r4.yaml — "
            "module names or file path may have changed.",
        )

    def _violations(self, param: str) -> list[str]:
        out = []
        for task in self.vmware_tasks:
            for module in self.VMWARE_MODULES:
                params = task.get(module, {})
                if isinstance(params, dict) and param in params:
                    out.append(task.get("name", "<unnamed>"))
        return out

    def test_no_inline_hostname(self) -> None:
        v = self._violations("hostname")
        self.assertFalse(v, f"Tasks with inline 'hostname' (use module_defaults): {v}")

    def test_no_inline_username(self) -> None:
        v = self._violations("username")
        self.assertFalse(v, f"Tasks with inline 'username' (use module_defaults): {v}")

    def test_no_inline_password(self) -> None:
        v = self._violations("password")
        self.assertFalse(v, f"Tasks with inline 'password' (use module_defaults): {v}")


if __name__ == "__main__":
    unittest.main()
