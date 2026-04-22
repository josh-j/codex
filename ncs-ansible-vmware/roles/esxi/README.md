# internal.vmware.esxi

ESXi audit, collection, and STIG orchestration for VMware environments.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: collect` (Default)
Collects ESXi host inventory, datastore metrics, and per-host health data.

### `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
Performs STIG compliance evaluation or hardening across discovered ESXi hosts.

### `ncs_action: remediate`, `ncs_operation: password_rotate`
Rotates local user passwords on ESXi hosts via the vCenter API.

### `ncs_action: audit`, `ncs_operation: password_status`
Reports local user account status on ESXi hosts.

## Prerequisites

- vCenter credentials via `vmware_username`/`vmware_password` or vault (`vault_vcenter_username`/`vault_vcenter_password`)
- Hosts in `vcsa` or `esxi_hosts` inventory group
- `connection: local` (API-based, no SSH to ESXi)

## Usage

```yaml
- hosts: "vcsa:esxi_hosts"
  connection: local
  roles:
    - role: internal.vmware.esxi
      vars:
        ncs_action: audit
        ncs_profile: stig
```
