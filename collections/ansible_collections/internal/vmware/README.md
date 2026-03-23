# internal.vmware

An Ansible collection for VMware audit collection and STIG automation.

The maintained audit entrypoints are:

- `internal.vmware.vcenter_collect` for vCenter appliance health, backup state, and active alarms
- `internal.vmware.esxi` for ESXi inventory collection and ESXi STIG workflows
- `internal.vmware.vm` for VM inventory collection, snapshot state, and VM STIG workflows

`internal.vmware.vcsa` remains the VCSA STIG role. The service-specific VCSA roles such as `vcsa_sts` and `vcsa_lookup` are internal composition roles and should not be used as standalone audit entrypoints.

## Usage

Read-only VMware fleet audit:

```yaml
- name: VMware health and compliance audit
  hosts: vcenters
  connection: local
  gather_facts: false
  roles:
    - role: internal.vmware.vcenter_collect
    - role: internal.vmware.esxi
      vars:
        ncs_action: collect
    - role: internal.vmware.vm
      vars:
        ncs_action: collect
```

Targeted STIG entrypoints:

- `internal.vmware.vcsa` for VCSA STIG audit/remediation
- `internal.vmware.esxi` with `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
- `internal.vmware.vm` with `ncs_action: audit|remediate|verify`, `ncs_profile: stig`

## Supported Interface

- `internal.vmware.vcenter_collect`: `collect`
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
- `roles/vcenter_collect`: vCenter audit collection pipeline
- `roles/esxi`: ESXi collection and STIG pipeline
- `roles/vm`: VM collection, snapshot, and STIG pipeline
- `roles/vcsa*`: VCSA STIG orchestration and service-specific subroles
- `plugins/modules/vmware_triggered_alarms_info.py`: internal custom collector
