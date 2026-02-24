# internal.vmware

A consolidated Ansible collection for VMware infrastructure auditing, reporting, and operational health checks.

## Roles

### `internal.vmware.audit`
The primary capability role for this collection. It acts as an **ETL (Extract, Transform, Load)** pipeline to audit vCenter environments.

**Capabilities:**
*   **Discovery:** Collects data on Datacenters, Clusters, Hosts, Datastores, VMs, Snapshots, and Alarms.
*   **Checks:** Analyzes collected data against compliance rules (e.g., Snapshot Age, Datastore Capacity, Host HA/DRS settings).
*   **Reporting:** Aggregates findings into structured alerts and exports detailed CSV reports.

**Usage:**
```yaml
- name: Run VMware Health Audit
  ansible.builtin.include_role:
    name: internal.vmware.audit
  vars:
    # Optional: Override defaults
    vmware_skip_discovery: false
```

## Structure
The collection logic is organized into atomic task files within the `audit` role:

*   `tasks/init.yaml`: Connection handling and reachability checks.
*   `tasks/discovery/*.yaml`: API data collection (Read-Only).
*   `tasks/checks/*.yaml`: Business logic and alert generation (Local execution).
*   `tasks/summary.yaml`: Aggregation of metrics and alerts.
*   `tasks/export/*.yaml`: CSV/Report generation.

## Configuration
Defaults are defined in `roles/audit/defaults/main.yaml` (inherited from global `vmware_config` if set).
