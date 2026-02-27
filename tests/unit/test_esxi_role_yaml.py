"""Structural YAML tests for the internal.vmware.esxi role task files.

These tests parse task YAML as data and assert structural invariants that
ansible-lint cannot detect but which cause silent runtime failures when
running against real vCenter infrastructure.

Bugs caught by these tests:
  - Missing module_defaults in main.yaml → vmware_host_config_manager tasks
    receive no hostname/username/password and fail with a missing-argument
    error on every STIG rule.
  - `failed_when: false` on the host loop in check.yaml → connection failures
    are silently discarded and remediation appears to succeed when it has not.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

ESXI_TASKS = (
    Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "roles"
    / "esxi"
    / "tasks"
)

VMWARE_GROUP_KEY = "group/community.vmware.vmware"
REQUIRED_CREDENTIAL_PARAMS = ("hostname", "username", "password", "validate_certs")


def _load(filename: str) -> list[dict[str, Any]]:
    raw = yaml.safe_load((ESXI_TASKS / filename).read_text())
    return raw if isinstance(raw, list) else []


class TestMainYamlModuleDefaults(unittest.TestCase):
    """main.yaml dispatcher task must declare module_defaults for the vmware group.

    Without this, community.vmware.vmware_host_config_manager tasks in
    esxi_v7r4.yaml have no vCenter connection details and fail at runtime
    with "missing required arguments: hostname".
    """

    def setUp(self) -> None:
        self.tasks = _load("main.yaml")
        self.dispatcher = next((t for t in self.tasks if "module_defaults" in t), None)

    def test_dispatcher_task_has_module_defaults(self) -> None:
        self.assertIsNotNone(
            self.dispatcher,
            "main.yaml has no task with module_defaults. "
            "vmware_host_config_manager requires hostname/username/password — "
            "add module_defaults: {group/community.vmware.vmware: {hostname: ..., ...}}",
        )

    def test_module_defaults_covers_vmware_group(self) -> None:
        self.assertIsNotNone(self.dispatcher)
        md: dict[str, Any] = self.dispatcher["module_defaults"]  # type: ignore[index]
        self.assertIn(
            VMWARE_GROUP_KEY,
            md,
            f"module_defaults must include '{VMWARE_GROUP_KEY}' to inject credentials "
            "into all community.vmware module calls automatically.",
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
            "vmware_host_config_manager will raise 'missing required arguments' at runtime.",
        )

    def test_include_tasks_is_inside_block(self) -> None:
        """module_defaults only apply to tasks within the same block scope.

        An include_tasks at the top level of the task, even alongside
        module_defaults, does not propagate the defaults into included tasks.
        The include must be nested inside block:.
        """
        self.assertIsNotNone(self.dispatcher)
        self.assertIn(
            "block",
            self.dispatcher,  # type: ignore[arg-type]
            "include_tasks must be nested inside block: so that module_defaults propagate.",
        )
        block: list[dict[str, Any]] = self.dispatcher["block"]  # type: ignore[index]
        has_include = any(
            "ansible.builtin.include_tasks" in t or "include_tasks" in t for t in block
        )
        self.assertTrue(has_include, "block: inside the dispatcher task has no include_tasks.")


class TestCheckYamlErrorHandling(unittest.TestCase):
    """check.yaml must propagate per-host failures instead of discarding them.

    failed_when: false on the host loop means a host that fails to connect
    (or for which every STIG task errors) is indistinguishable from a
    successful run — the play stays green and the post-audit will show the
    host as still non-compliant with no indication that remediation failed.
    """

    def setUp(self) -> None:
        self.tasks = _load("check.yaml")
        self.host_loop = next(
            (t for t in self.tasks if "esxi_stig_target_hosts" in str(t.get("loop", ""))),
            None,
        )

    def test_host_loop_task_exists(self) -> None:
        self.assertIsNotNone(
            self.host_loop,
            "Could not locate the esxi_stig_target_hosts loop task in check.yaml.",
        )

    def test_host_loop_does_not_suppress_failures(self) -> None:
        self.assertIsNotNone(self.host_loop)
        self.assertIsNot(
            self.host_loop.get("failed_when"),  # type: ignore[union-attr]
            False,
            "failed_when: false on the host loop silently discards connection errors. "
            "Remove it so host failures surface as play failures.",
        )

    def test_audit_complete_flag_is_set(self) -> None:
        """A set_fact task must mark the audit as complete after the loop."""
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
            "check.yaml should set a completion flag (set_fact) after the host loop.",
        )


class TestEsxiV7r4NoInlineCredentials(unittest.TestCase):
    """vmware_host_config_manager tasks must not embed vCenter credentials inline.

    Credentials must come exclusively from module_defaults in main.yaml.
    Inline credentials would create a second, inconsistent source of truth
    and indicate that module_defaults is not being relied upon — meaning it
    could be removed without any test catching the regression.
    """

    MODULE = "community.vmware.vmware_host_config_manager"

    def setUp(self) -> None:
        all_tasks = _load("esxi_v7r4.yaml")
        self.config_manager_tasks = [t for t in all_tasks if self.MODULE in t]

    def test_has_config_manager_tasks(self) -> None:
        self.assertGreater(
            len(self.config_manager_tasks),
            0,
            f"No {self.MODULE} tasks found in esxi_v7r4.yaml — path or module name may have changed.",
        )

    def _credential_violations(self, param: str) -> list[str]:
        return [
            t.get("name", "<unnamed>")
            for t in self.config_manager_tasks
            if param in t.get(self.MODULE, {})
        ]

    def test_no_inline_hostname(self) -> None:
        violations = self._credential_violations("hostname")
        self.assertFalse(
            violations,
            f"Tasks with inline 'hostname' (use module_defaults instead): {violations}",
        )

    def test_no_inline_username(self) -> None:
        violations = self._credential_violations("username")
        self.assertFalse(
            violations,
            f"Tasks with inline 'username' (use module_defaults instead): {violations}",
        )

    def test_no_inline_password(self) -> None:
        violations = self._credential_violations("password")
        self.assertFalse(
            violations,
            f"Tasks with inline 'password' (use module_defaults instead): {violations}",
        )


if __name__ == "__main__":
    unittest.main()
