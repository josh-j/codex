# internal.linux.ubuntu

Unified role for managing and auditing Ubuntu systems.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: collect` (Default)
Collects system facts, security settings, and update status.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats`.

### `ncs_action: remediate`, `ncs_operation: maintain|patch`
Applies non-STIG system maintenance or patching actions.

### `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
Performs STIG compliance evaluation.
- **Handoff:** Emits STIG telemetry via `ansible.builtin.set_stats` and `ncs_collector`.

### `ncs_action: remediate`, `ncs_operation: password_rotate`
Manages local user passwords and aging policies.

### `ncs_action: audit`, `ncs_operation: password_status`
Reports password aging and account status for a local user.

## Usage

```yaml
- name: Collect Ubuntu Discovery
  hosts: ubuntu_servers
  roles:
    - role: internal.linux.ubuntu
      vars:
        ncs_action: collect
```
