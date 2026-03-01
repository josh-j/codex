"""Integration tests for playbook structure and ncs-reporter invocation config.

These tests parse playbook YAML as data and assert structural invariants:
- All playbooks are valid YAML
- generate_reports.yml passes --config-dir so ncs_ansible's local configuration
  is used rather than ncs_reporter's bundled defaults
- All roles referenced in playbooks exist in the internal collections
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from _paths import COLLECTIONS_INTERNAL, PLAYBOOKS_DIR


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


def _all_tasks(play_or_block: Any) -> list[dict[str, Any]]:
    """Recursively collect all task dicts from a play or block."""
    tasks: list[dict[str, Any]] = []
    if not isinstance(play_or_block, dict):
        return tasks
    for key in ("tasks", "pre_tasks", "post_tasks", "block", "rescue", "always", "handlers"):
        for item in play_or_block.get(key) or []:
            tasks.append(item)
            tasks.extend(_all_tasks(item))
    return tasks


def _command_string(task: dict[str, Any]) -> str:
    """Extract the command string from an ansible.builtin.command or command task."""
    for key in ("ansible.builtin.command", "command"):
        val = task.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            return val.get("cmd", "") or val.get("argv", [""])[0]
    return ""


class TestAllPlaybooksValidYaml(unittest.TestCase):
    """Every .yml file in playbooks/ must parse as valid YAML."""

    def test_all_playbooks_parse(self) -> None:
        playbook_files = list(PLAYBOOKS_DIR.glob("*.yml"))
        self.assertGreater(len(playbook_files), 0, "No playbooks found")
        for path in playbook_files:
            with self.subTest(playbook=path.name):
                parsed = _load(path)
                self.assertIsNotNone(parsed, f"{path.name} parsed as None")

    def test_all_playbooks_are_lists(self) -> None:
        for path in PLAYBOOKS_DIR.glob("*.yml"):
            with self.subTest(playbook=path.name):
                parsed = _load(path)
                self.assertIsInstance(parsed, list, f"{path.name} is not a list of plays")

    def test_all_plays_have_hosts_key(self) -> None:
        import_keys = {"ansible.builtin.import_playbook", "import_playbook"}
        for path in PLAYBOOKS_DIR.glob("*.yml"):
            plays = _load(path) or []
            for play in plays:
                if any(k in play for k in import_keys):
                    continue  # orchestrator entries delegate to another playbook
                with self.subTest(playbook=path.name, play=play.get("name", "(unnamed)")):
                    self.assertIn("hosts", play, f"Play in {path.name} missing 'hosts'")


class TestGenerateReportsPlaybook(unittest.TestCase):
    """generate_reports.yml must invoke ncs-reporter with ncs_ansible's local config flags."""

    PLAYBOOK = PLAYBOOKS_DIR / "generate_reports.yml"

    def setUp(self) -> None:
        self.plays = _load(self.PLAYBOOK) or []
        self.all_tasks: list[dict[str, Any]] = []
        for play in self.plays:
            self.all_tasks.extend(_all_tasks(play))

    def _ncs_reporter_commands(self) -> list[str]:
        cmds = []
        for task in self.all_tasks:
            cmd = _command_string(task)
            if "ncs-reporter" in cmd:
                cmds.append(cmd)
        return cmds

    def test_playbook_exists(self) -> None:
        self.assertTrue(self.PLAYBOOK.exists())

    def test_has_ncs_reporter_invocation(self) -> None:
        cmds = self._ncs_reporter_commands()
        self.assertGreater(len(cmds), 0, "generate_reports.yml has no ncs-reporter invocation")

    def test_ncs_reporter_passes_config_dir(self) -> None:
        cmds = self._ncs_reporter_commands()
        has_flag = any("--config-dir" in cmd for cmd in cmds)
        self.assertTrue(
            has_flag,
            "ncs-reporter invocation is missing --config-dir; "
            "ncs_ansible local report config will not be used",
        )

    def test_ncs_reporter_passes_platform_root(self) -> None:
        cmds = self._ncs_reporter_commands()
        has_flag = any("--platform-root" in cmd for cmd in cmds)
        self.assertTrue(has_flag, "ncs-reporter invocation is missing --platform-root")

    def test_ncs_reporter_passes_reports_root(self) -> None:
        cmds = self._ncs_reporter_commands()
        has_flag = any("--reports-root" in cmd for cmd in cmds)
        self.assertTrue(has_flag, "ncs-reporter invocation is missing --reports-root")

    def test_ncs_reporter_passes_groups(self) -> None:
        cmds = self._ncs_reporter_commands()
        has_flag = any("--groups" in cmd for cmd in cmds)
        self.assertTrue(has_flag, "ncs-reporter invocation is missing --groups")


class TestPlaybookRoleReferences(unittest.TestCase):
    """Roles referenced in playbooks must exist in the internal collections."""

    def _role_exists(self, role_ref: str) -> bool:
        """Check if a role reference resolves to a path under internal collections.

        Handles both FQCN (internal.vmware.vcenter) and short-name (vcenter) refs.
        """
        # FQCN: internal.<collection>.<role>
        fqcn_match = re.match(r"^internal\.(\w+)\.(\w+)$", role_ref)
        if fqcn_match:
            collection, role = fqcn_match.groups()
            return (COLLECTIONS_INTERNAL / collection / "roles" / role).exists()

        # Short name: search all internal collections
        for collection_dir in COLLECTIONS_INTERNAL.iterdir():
            roles_dir = collection_dir / "roles"
            if roles_dir.exists() and (roles_dir / role_ref).exists():
                return True
        return False

    def _collect_role_refs(self, plays: list[Any]) -> list[str]:
        refs = []
        for play in plays or []:
            for role_entry in play.get("roles") or []:
                if isinstance(role_entry, str):
                    refs.append(role_entry)
                elif isinstance(role_entry, dict):
                    name = role_entry.get("role") or role_entry.get("name", "")
                    if name:
                        refs.append(name)
        return refs

    def test_platform_audit_playbooks_reference_valid_roles(self) -> None:
        audit_playbooks = ["vmware_audit.yml", "ubuntu_audit.yml", "windows_audit.yml"]
        for filename in audit_playbooks:
            path = PLAYBOOKS_DIR / filename
            if not path.exists():
                continue
            plays = _load(path) or []
            refs = self._collect_role_refs(plays)
            for ref in refs:
                with self.subTest(playbook=filename, role=ref):
                    self.assertTrue(self._role_exists(ref), f"Role '{ref}' in {filename} not found")

    def test_stig_playbooks_reference_valid_roles(self) -> None:
        stig_playbooks = [p for p in PLAYBOOKS_DIR.glob("*stig*.yml")]
        for path in stig_playbooks:
            plays = _load(path) or []
            refs = self._collect_role_refs(plays)
            for ref in refs:
                with self.subTest(playbook=path.name, role=ref):
                    self.assertTrue(self._role_exists(ref), f"Role '{ref}' in {path.name} not found")


if __name__ == "__main__":
    unittest.main()
