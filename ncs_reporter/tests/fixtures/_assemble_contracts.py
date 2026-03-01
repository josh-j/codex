"""Expected bundle data key sets for each platform.

These sets were extracted from the Ansible task files that assemble raw collection bundles:

- VCENTER_DATA_KEYS: from ``collections/ansible_collections/internal/vmware/roles/vcenter/tasks/assemble.yaml``
  (the ``data`` sub-dict of the ``vmware_raw_vcenter`` set_fact)
- LINUX_DATA_KEYS: from ``collections/ansible_collections/internal/linux/roles/ubuntu/tasks/discover.yaml``
  (the ``ubuntu_raw_discovery`` set_fact payload)
- WINDOWS_DATA_KEYS: from ``collections/ansible_collections/internal/windows/roles/windows/tasks/audit.yaml``
  (the ``_win_raw_payload`` set_fact payload)

Update these sets when the corresponding Ansible roles change their set_fact structures.
"""

from __future__ import annotations

VCENTER_DATA_KEYS: set[str] = {
    "appliance_health_info",
    "appliance_backup_info",
    "datacenters_info",
    "clusters_info",
    "datastores_info",
    "vms_info",
    "snapshots_info",
    "alarms_info",
    "config",
}

LINUX_DATA_KEYS: set[str] = {
    "ansible_facts",
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
