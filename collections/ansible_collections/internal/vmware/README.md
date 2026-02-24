# internal.vmware

A consolidated Ansible collection for VMware infrastructure auditing, reporting, and operational health checks.

## Roles

### `internal.vmware.discovery`
Collects and normalizes vCenter inventory/health data into `vmware_ctx`, then exports `discovery.yaml`.
Supports overriding the export destination with `ncs_export_path`.

### `internal.vmware.audit`
Runs audit checks against discovery data and exports vCenter health state.

**Capabilities:**
*   **Checks:** Analyzes discovery data against health/compliance rules (e.g., Snapshot Age, Datastore Capacity, Host HA/DRS settings).
*   **Reporting:** Aggregates findings into structured alerts and exports vCenter audit state.

**Usage:**
```yaml
- name: Run VMware Health Audit
  ansible.builtin.include_role:
    name: internal.vmware.audit
  vars:
    # Optional: Override defaults
    vmware_skip_discovery: false
    # Optional: Override export destination
    ncs_export_path: "/srv/samba/reports/platform/vmware/{{ inventory_hostname }}/vcenter.yaml"
```

## Structure
Primary role layout:

*   `roles/discovery/tasks/init.yaml`: vCenter initialization and reachability checks.
*   `roles/discovery/tasks/discovery/*.yaml`: API data collection and normalization.
*   `roles/audit/tasks/checks*.yaml`: Business logic and alert generation.
*   `roles/audit/tasks/export.yaml`: Audit export payload generation.
*   `roles/summary/tasks/*.yaml`: Fleet report rendering.

## Configuration
Defaults are primarily defined in:
* `roles/discovery/defaults/main.yaml` for discovery/runtime context shape
* `roles/audit/defaults/main.yaml` for thresholds and audit toggles

Validation toggles:
* `vmware_validate_ctx_schema` (discovery): assert `vmware_ctx` shape before export
* `vmware_validate_export_schema` (audit): assert audit export payload shape before export
