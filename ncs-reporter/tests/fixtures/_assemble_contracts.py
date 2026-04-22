"""Expected bundle data key sets for platform raw collection contracts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSIBLE_ROOT = REPO_ROOT / "ncs-ansible"
VMWARE_ROLES_ROOT = ANSIBLE_ROOT / "collections/ansible_collections/internal/vmware/roles"


def _walk_tasks(tasks: object) -> Iterator[dict]:
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        yield task
        for nested_key in ("block", "rescue", "always"):
            yield from _walk_tasks(task.get(nested_key))


def _extract_set_fact_keys(task_file: Path, fact_name: str) -> set[str]:
    tasks = yaml.safe_load(task_file.read_text(encoding="utf-8")) or []
    for task in _walk_tasks(tasks):
        payload = task.get("ansible.builtin.set_fact")
        if not isinstance(payload, dict) or fact_name not in payload:
            continue
        fact_payload = payload[fact_name]
        if isinstance(fact_payload, dict):
            return {str(k) for k in fact_payload}
    raise RuntimeError(f"{fact_name} not set as a dict in {task_file}")


def _vmware_keys(role: str, fact: str) -> set[str]:
    return _extract_set_fact_keys(VMWARE_ROLES_ROOT / role / "tasks" / "collect.yaml", fact)


VCENTER_DATA_KEYS = _vmware_keys("vcsa", "vmware_raw_vcenter")
ESXI_DATA_KEYS = _vmware_keys("esxi", "vmware_raw_esxi")
VM_DATA_KEYS = _vmware_keys("vm", "vmware_raw_vm")

# Linux/Windows fact sets stay hardcoded: their assemblers are spread
# across multiple task files and dynamic set_facts, so a single-file
# extractor can't recover them. Keep in sync with the corresponding
# internal.linux.ubuntu and internal.windows.server collect tasks.
LINUX_DATA_KEYS: set[str] = {
    "hostname",
    "ip_address",
    "kernel",
    "os_family",
    "distribution",
    "distribution_version",
    "uptime_seconds",
    "load_avg_15m",
    "memory_total_mb",
    "memory_free_mb",
    "swap_total_mb",
    "swap_free_mb",
    "getent_passwd",
    "epoch_seconds",
    "mounts",
    "failed_services",
    "shadow_raw",
    "sshd_raw",
    "world_writable",
    "reboot_stat",
    "apt_simulate",
    "file_stats",
}

WINDOWS_DATA_KEYS: set[str] = {
    "ansible_facts",
    "ccm_service",
    "configmgr_apps",
    "installed_apps",
    "apps_to_update",
    "update_results",
    "audit_failed",
}
