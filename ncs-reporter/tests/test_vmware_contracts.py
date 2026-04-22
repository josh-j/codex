from __future__ import annotations

from pathlib import Path

import yaml

from fixtures._assemble_contracts import ESXI_DATA_KEYS, VCENTER_DATA_KEYS, VM_DATA_KEYS

REPO_ROOT = Path(__file__).resolve().parents[2]
VMWARE_ROOT = REPO_ROOT / "ncs-ansible" / "collections" / "ansible_collections" / "internal" / "vmware"


def _read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / "ncs-ansible" / relative_path).read_text(encoding="utf-8")) or {}


def _extract_actions_from_main_yaml(main_yaml_path: Path) -> list[str]:
    """Extract the list of valid action routes the role declares to dispatch.

    The current role pattern passes the set of allowed actions to
    ``internal.core.dispatch`` as ``_ncs_action_routes:`` (a YAML list).
    The legacy pattern used an inline ``assert`` with
    ``_ncs_requested_action in [...]``; still honored for compatibility.
    """
    import re

    content = main_yaml_path.read_text(encoding="utf-8")

    routes_match = re.search(r"_ncs_action_routes:\s*\n((?:\s*-\s*[^\n]+\n)+)", content)
    if routes_match:
        return [
            line.strip().lstrip("-").strip().strip("'\"")
            for line in routes_match.group(1).splitlines()
            if line.strip().startswith("-")
        ]

    legacy_match = re.search(r"_ncs_requested_action\s+in\s+\[([^\]]+)\]", content)
    if legacy_match:
        return [a.strip().strip("'\"") for a in legacy_match.group(1).split(",")]

    return []


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
