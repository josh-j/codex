# internal.vmware

An Ansible collection for VMware audit collection and STIG automation.

The maintained audit entrypoints are:

- `internal.vmware.vcsa` for vCenter appliance health, backup state, active alarms, and VCSA STIG workflows
- `internal.vmware.esxi` for ESXi inventory collection and ESXi STIG workflows
- `internal.vmware.vm` for VM inventory collection, snapshot state, and VM STIG workflows

All service-specific STIG tasks (eam, lookup, perfcharts, postgresql, rhttpproxy, sts, ui, vami) are consolidated within the vcsa role.

## Usage

Read-only VMware fleet audit:

```yaml
- name: VMware health and compliance audit
  hosts: vcenters
  connection: local
  gather_facts: false
  roles:
    - role: internal.vmware.vcsa
      vars:
        ncs_action: collect
    - role: internal.vmware.esxi
      vars:
        ncs_action: collect
    - role: internal.vmware.vm
      vars:
        ncs_action: collect
```

Targeted STIG entrypoints:

- `internal.vmware.vcsa` with `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
- `internal.vmware.esxi` with `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
- `internal.vmware.vm` with `ncs_action: audit|remediate|verify`, `ncs_profile: stig`

## Supported Interface

- `internal.vmware.vcsa`: `ncs_action: collect`; STIG via `ncs_profile: stig`
- `internal.vmware.esxi`: `ncs_action: collect`; STIG via `ncs_profile: stig`; maintenance via `ncs_operation: rotate_password|password_status`
- `internal.vmware.vm`: `ncs_action: collect`; STIG via `ncs_profile: stig`; snapshot via `ncs_operation: snapshot`

Unsupported interface combinations fail early with an explicit assertion instead of a task-file lookup error.

## Data Contracts

The collection exports three raw payload families through `set_stats` for the `internal.core.ncs_collector` callback:

- `vmware_raw_vcenter`
- `vmware_raw_esxi`
- `vmware_raw_vm`

Their canonical top-level keys are documented in [docs/SCHEMA.md](/home/sio/codex/collections/ansible_collections/internal/vmware/docs/SCHEMA.md).

## Requirements

- `ansible-core >= 2.15`
- `community.vmware`
- `vmware.vmware`
- `pyVmomi` for the custom alarm collector

## Layout

- `roles/common`: shared VMware connection and collection helper tasks
- `roles/vcsa`: vCenter collection, VCSA STIG orchestration, and service-specific tasks
- `roles/esxi`: ESXi collection and STIG pipeline
- `roles/vm`: VM collection, snapshot, and STIG pipeline
- `plugins/modules/vmware_triggered_alarms_info.py`: internal custom collector
