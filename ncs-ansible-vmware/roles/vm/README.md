# internal.vmware.vm

VM audit, collection, snapshot workflows, and STIG orchestration.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: collect` (Default)
Collects VM inventory, snapshot state, and workload metrics.

### `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
Performs STIG compliance evaluation or hardening across discovered VMs.

### `ncs_action: remediate`, `ncs_operation: snapshot`
Creates safety snapshots before remediation operations.

## Prerequisites

- vCenter credentials via `vmware_username`/`vmware_password` or vault
- Hosts in `vcsa` inventory group (VMs are discovered via vCenter API)
- `connection: local` (API-based)

## Usage

```yaml
- hosts: vcsa
  connection: local
  roles:
    - role: internal.vmware.vm
      vars:
        ncs_action: audit
        ncs_profile: stig
```
