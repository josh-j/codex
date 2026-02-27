# internal.vmware

An Ansible collection for VMware infrastructure auditing and data collection. Following the **NCS Decoupled Architecture**, this collection focuses strictly on data collection across the fleet, while processing and reporting are handled by the `ncs-reporter` Python CLI.

## Roles

### `internal.vmware.vcenter`
Performs deep inventory and health discovery of vCenter instances. 
- **Action:** Executes standard VMware modules and custom collectors.
- **Handoff:** Saves raw module results to `raw_discovery.yaml` using the `internal.core.state:save_raw` task.
- **Idiomatic:** Uses `module_defaults` to centralize connection parameters.

### `internal.vmware.esxi`
Handles host-level configuration and STIG auditing against ESXi hypervisors.
- **Action:** Runs native compliance checks against individual ESXi hosts.

### `internal.vmware.vm`
Handles virtual machine level configuration, snapshotting, and STIG auditing.
- **Action:** Creates safety snapshots, runs STIG checks against VMs.

### `internal.vmware.common`
Shared utility tasks, including `init_vcenter.yaml` for standardized hostname and credential resolution.


## Usage

```yaml
- name: Collect VMware Discovery Data
  hosts: vcenters
  roles:
    - role: internal.vmware.vcenter
      vars:
        vcenter_action: collect
```


## Structure
- `plugins/modules/`: Custom Ansible modules (e.g., `vmware_triggered_alarms_info`).
- `roles/*/tasks/`: Pure Ansible YAML tasks for collection.
- `meta/runtime.yml`: Collection metadata and plugin routing.

## Requirements
- `community.vmware` collection.
- `vmware.vmware_rest` collection.
- `pyVmomi` and `vSphere Automation SDK` installed in the Ansible Python environment.
