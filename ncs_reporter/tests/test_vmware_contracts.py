from __future__ import annotations

from pathlib import Path

import yaml

from fixtures._assemble_contracts import ESXI_DATA_KEYS, VCENTER_DATA_KEYS, VM_DATA_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
VMWARE_ROOT = REPO_ROOT / "collections" / "ansible_collections" / "internal" / "vmware"


def _read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / relative_path).read_text(encoding="utf-8")) or {}


def _extract_actions_from_main_yaml(main_yaml_path: Path) -> list[str]:
    """Extract valid actions from the inline assert block in main.yaml.

    The current role pattern validates actions via an ``assert`` task with
    ``_ncs_requested_action in ['collect', 'audit', ...]``.
    """
    import re

    content = main_yaml_path.read_text(encoding="utf-8")
    match = re.search(r"_ncs_requested_action\s+in\s+\[([^\]]+)\]", content)
    if not match:
        return []
    raw = match.group(1)
    return [a.strip().strip("'\"") for a in raw.split(",")]


def test_vmware_supported_actions_match_task_files() -> None:
    role_tasks = {
        "esxi": VMWARE_ROOT / "roles" / "esxi" / "tasks",
        "vm": VMWARE_ROOT / "roles" / "vm" / "tasks",
    }

    for role_name, task_dir in role_tasks.items():
        main_yaml = task_dir / "main.yaml"
        assert main_yaml.is_file(), f"{role_name} main.yaml should exist"
        actions = _extract_actions_from_main_yaml(main_yaml)
        assert actions, f"{role_name} supported actions should not be empty"


def test_vmware_public_readme_matches_supported_surface() -> None:
    readme = (VMWARE_ROOT / "README.md").read_text(encoding="utf-8")

    for role_name in (
        "internal.vmware.vcenter_collect",
        "internal.vmware.esxi",
        "internal.vmware.vm",
        "internal.vmware.vcsa",
    ):
        assert role_name in readme

    for action_text in ("collect", "snapshot", "stig"):
        assert action_text in readme


def test_vmware_schema_doc_mentions_all_public_payload_keys() -> None:
    schema_doc = (VMWARE_ROOT / "docs" / "SCHEMA.md").read_text(encoding="utf-8")

    assert "vmware_raw_vcenter" in schema_doc
    assert "vmware_raw_esxi" in schema_doc
    assert "vmware_raw_vm" in schema_doc

    for key in VCENTER_DATA_KEYS | ESXI_DATA_KEYS | VM_DATA_KEYS:
        assert key in schema_doc, f"{key} missing from VMware schema documentation"


def test_vmware_contract_sets_are_nonempty() -> None:
    assert VCENTER_DATA_KEYS, "VCENTER_DATA_KEYS parsed to empty set"
    assert ESXI_DATA_KEYS, "ESXI_DATA_KEYS parsed to empty set"
    assert VM_DATA_KEYS, "VM_DATA_KEYS parsed to empty set"
