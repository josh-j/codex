"""Expected bundle data key sets for platform raw collection contracts."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


def _walk_tasks(tasks: object):
    """Yield every task dict in a task list, descending into block/rescue/always."""
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        yield task
        for nested_key in ("block", "rescue", "always"):
            yield from _walk_tasks(task.get(nested_key))


def _extract_set_fact_keys(relative_path: str, fact_name: str) -> set[str]:
    task_file = REPO_ROOT / relative_path
    tasks = yaml.safe_load(task_file.read_text(encoding="utf-8")) or []
    for task in _walk_tasks(tasks):
        payload = task.get("ansible.builtin.set_fact")
        if not isinstance(payload, dict) or fact_name not in payload:
            continue
        fact_payload = payload[fact_name]
        if isinstance(fact_payload, dict):
            return {str(k) for k in fact_payload}
    return set()


VCENTER_DATA_KEYS = _extract_set_fact_keys(
    "ncs-ansible/collections/ansible_collections/internal/vmware/roles/vcsa/tasks/collect.yaml",
    "vmware_raw_vcenter",
)

ESXI_DATA_KEYS = _extract_set_fact_keys(
    "ncs-ansible/collections/ansible_collections/internal/vmware/roles/esxi/tasks/collect.yaml",
    "vmware_raw_esxi",
)

VM_DATA_KEYS = _extract_set_fact_keys(
    "ncs-ansible/collections/ansible_collections/internal/vmware/roles/vm/tasks/collect.yaml",
    "vmware_raw_vm",
)

# Hardcoded because discover.yaml's set_fact is inside a block (not
# top-level), so _extract_set_fact_keys can't reach it.  Keep in sync
# with internal.linux.ubuntu tasks/discover.yaml → ubuntu_raw_discovery.
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
