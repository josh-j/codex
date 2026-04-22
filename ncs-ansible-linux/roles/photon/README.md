# internal.linux.photon

Photon OS audit, collection, and STIG orchestration.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: collect` (Default)
Collects Photon OS system state and security configuration.

### `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
Performs STIG compliance evaluation or hardening.

### `ncs_action: remediate`, `ncs_operation: password_rotate`
Rotates local user passwords.

### `ncs_action: audit`, `ncs_operation: password_status`
Reports password aging and account status.

## Prerequisites

- SSH credentials from inventory (`ansible_user`, `ansible_password` in `group_vars/photon_servers`)
- Hosts in `photon_servers` inventory group

## Usage

```yaml
- hosts: photon_servers
  roles:
    - role: internal.linux.photon
      vars:
        ncs_action: audit
        ncs_profile: stig
```
