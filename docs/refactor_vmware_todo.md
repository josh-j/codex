# VMware Composable Refactor TODO

## Done So Far
1. Introduced `vmware_ctx` and bound it in `playbooks/site_health.yaml`.
2. Created `internal.vmware` collection with composable roles:
   - `init`, `discovery`, `inventory`, `checks`, `alerts`, `export`, `health`, `notify`.
3. Refactored vSphere audit to wrap composable roles.
4. Migrated all exports to `internal.vmware.export` and removed `vcenter` fallbacks.
5. Migrated all checks/alerts to read from `vmware_ctx` (resources, snapshots, alarms, VMs, datastores).
6. Migrated producers to populate `vmware_ctx` (resources, datastores, VMs, snapshots, alarms).
7. Updated vCenter summary template to use `vmware_ctx`.
8. Removed `vcenter` domain defaults and legacy bridge logic.
9. `vmware_ctx.config` now sourced from `vmware_config` (no fallback).
10. Documented `vmware_ctx` as primary in `collections/ansible_collections/internal/vsphere/README.md`.
11. Removed `vcenter` defaults entirely from vSphere audit role.
12. Switched reachability + checks_failed to `vmware_ctx`.
13. Ported discovery task bodies into `internal.vmware.discovery`:
    - `roles/discovery/tasks/resources.yaml`
    - `roles/discovery/tasks/datastores.yaml`
    - `roles/discovery/tasks/vms.yaml`
    - `roles/discovery/tasks/snapshots.yaml`
    - `roles/discovery/tasks/alarms.yaml`
    - Copied `get_vcenter_alarms.py` to `roles/discovery/files/`.
14. Created `internal.vmware.checks` role with all domain checks:
    - `roles/checks/tasks/main.yaml` (orchestrator)
    - `roles/checks/tasks/infrastructure.yaml`
    - `roles/checks/tasks/resources.yaml`
    - `roles/checks/tasks/datastores.yaml`
    - `roles/checks/tasks/vms.yaml`
    - `roles/checks/tasks/snapshots.yaml`
    - `roles/checks/tasks/alarms.yaml`
15. Created `internal.vmware.health` orchestrator role:
    - `roles/health/tasks/main.yaml` (init -> discovery -> checks -> summary -> export)
    - `roles/health/tasks/discovery.yaml` (discovery phase orchestrator)
    - `roles/health/templates/vmware_checks_summary.md.j2`
    - `roles/health/meta/main.yaml` (dependencies)
16. Replaced vSphere audit `discovery.yaml` and `checks.yaml` with thin wrappers.
17. Removed `ops_config.vcenter` fallback — standardized on `vmware_config` only.
18. Created `internal.vmware.init` role (connection + reachability).
19. Updated vSphere STIG role to use `vmware_ctx`:
    - `discover.yaml`: uses `vmware_username`/`vmware_password`, `generic_namespace: "vmware"`
    - `check.yaml`: reads from `vmware.stig_facts`
    - `main.yaml`: references `vmware_config_quiet_mode`
    - `defaults/main.yaml`: renamed `vcenter_config_*` to `vmware_config_*`
20. Updated ESXi STIG role:
    - `discover.yaml`: uses `vmware_hostname`/`vmware_username`/`vmware_password`
    - `audit_ssh.yaml`: uses `vmware_hostname`/`vmware_username`/`vmware_password`
21. Updated STIG playbook `site.yaml` credential bridge to `vmware_username`/`vmware_password`.
22. Migrated inventory/group_vars:
    - `all.yaml`: `vcenter_hostname` -> `vmware_hostname`, etc.
    - `vcenter.yaml` -> `vmware.yaml`: config under `vmware_config`
    - `00_global.yaml`: day_matrix `vcenter` -> `vmware`
23. Updated `site_health.yaml` to call `internal.vmware.health` directly.
24. Updated vmware collection roles to remove `vcenter` intermediate accumulator:
    - `discovery/main.yaml`: uses `vmware_ctx` exclusively, stores in `_vmw_*` locals
    - `inventory/main.yaml`: uses `vmware_ctx` exclusively, stores in `_vmw_*` locals
    - `alerts/main.yaml`: uses `vmware_ctx` exclusively, stores in `_vmw_*` locals
25. Ported owner notification workflow to `internal.vmware.notify`:
    - `roles/notify/tasks/main.yaml` (gatekeeping + recipient filtering)
    - `roles/notify/tasks/notify_loop.yaml` (per-owner issue compilation)
    - `roles/notify/templates/owner_notification_email.html.j2`
26. Deleted `internal.vsphere.vsphere_audit` role entirely.
27. Updated vsphere `README.md` to reflect final architecture.

## Refactor Complete

All VMware health audit logic now lives in `internal.vmware`.
`site_health.yaml` calls `internal.vmware.health` directly.
`internal.vsphere` only contains `vsphere_stig_audit` (STIG compliance).
No `vcenter` or `ops_config.vcenter` legacy references remain.
