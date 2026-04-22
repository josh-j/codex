from __future__ import annotations

from pathlib import Path

import yaml

from fixtures._assemble_contracts import (
    ANSIBLE_ROOT,
    ESXI_DATA_KEYS,
    VCENTER_DATA_KEYS,
    VM_DATA_KEYS,
    VMWARE_ROLES_ROOT,
    _walk_tasks,
)

VMWARE_ROOT = ANSIBLE_ROOT / "collections/ansible_collections/internal/vmware"


def _extract_dispatch_action_routes(main_yaml_path: Path) -> list[str]:
    """Return the `_ncs_action_routes` list a role passes to internal.core.dispatch."""
    tasks = yaml.safe_load(main_yaml_path.read_text(encoding="utf-8")) or []
    for task in _walk_tasks(tasks):
        include = task.get("ansible.builtin.include_role")
        if not isinstance(include, dict) or include.get("name") != "internal.core.dispatch":
            continue
        task_vars = task.get("vars")
        if not isinstance(task_vars, dict):
            continue
        routes = task_vars.get("_ncs_action_routes")
        if isinstance(routes, list):
            return [str(r) for r in routes]
    return []


def test_vmware_supported_actions_match_task_files() -> None:
    for role_name in ("esxi", "vm"):
        main_yaml = VMWARE_ROLES_ROOT / role_name / "tasks" / "main.yaml"
        assert main_yaml.is_file(), f"{role_name} main.yaml should exist"
        actions = _extract_dispatch_action_routes(main_yaml)
        assert actions, f"{role_name} supported actions should not be empty"


def test_vmware_public_readme_matches_supported_surface() -> None:
    readme = (VMWARE_ROOT / "README.md").read_text(encoding="utf-8")

    for role_name in (
        "internal.vmware.esxi",
        "internal.vmware.vm",
        "internal.vmware.vcsa",
    ):
        assert role_name in readme

    for action_text in ("collect", "snapshot", "stig"):
        assert action_text in readme


def test_vmware_schema_doc_mentions_all_public_payload_keys() -> None:
    schema_doc = (VMWARE_ROOT / "docs" / "SCHEMA.md").read_text(encoding="utf-8")

    assert "raw_vcenter" in schema_doc
    assert "raw_esxi" in schema_doc
    assert "raw_vm" in schema_doc

    for key in VCENTER_DATA_KEYS | ESXI_DATA_KEYS | VM_DATA_KEYS:
        assert key in schema_doc, f"{key} missing from VMware schema documentation"


def test_vmware_contract_sets_are_nonempty() -> None:
    assert VCENTER_DATA_KEYS, "VCENTER_DATA_KEYS parsed to empty set"
    assert ESXI_DATA_KEYS, "ESXI_DATA_KEYS parsed to empty set"
    assert VM_DATA_KEYS, "VM_DATA_KEYS parsed to empty set"
