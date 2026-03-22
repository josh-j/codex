from __future__ import annotations

from pathlib import Path

import yaml

from fixtures._assemble_contracts import ESXI_DATA_KEYS, VCENTER_DATA_KEYS, VM_DATA_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
VMWARE_ROOT = REPO_ROOT / "collections" / "ansible_collections" / "internal" / "vmware"


def _read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / relative_path).read_text(encoding="utf-8")) or {}


def test_vmware_supported_actions_match_task_files() -> None:
    role_actions = {
        "collections/ansible_collections/internal/vmware/roles/esxi/defaults/main.yaml": (
            "esxi_supported_actions",
            VMWARE_ROOT / "roles" / "esxi" / "tasks",
        ),
        "collections/ansible_collections/internal/vmware/roles/vm/defaults/main.yaml": (
            "vm_supported_actions",
            VMWARE_ROOT / "roles" / "vm" / "tasks",
        ),
    }

    for defaults_path, (actions_key, task_dir) in role_actions.items():
        defaults = _read_yaml(defaults_path)
        actions = defaults.get(actions_key, [])
        assert actions, f"{actions_key} should not be empty"
        missing = [action for action in actions if not (task_dir / f"{action}.yaml").is_file()]
        assert not missing, f"{actions_key} contains actions without task files: {missing}"


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
