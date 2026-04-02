# internal.template.example

Example platform role — copy and customize for your platform.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: collect` (Default)
Collects system facts and platform-specific telemetry.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats` and `ncs_collector`.

### `ncs_action: audit|remediate|verify`, `ncs_profile: stig`
Performs STIG compliance evaluation or hardening.
- **Handoff:** Emits STIG telemetry via `ansible.builtin.set_stats` and `ncs_collector`.

### `ncs_action: remediate`, `ncs_operation: password_rotate`
Manages local/service account passwords and aging policies.

### `ncs_action: audit`, `ncs_operation: password_status`
Reports password aging and account status.

## Usage

```yaml
- name: Collect Example Discovery
  hosts: example_servers
  roles:
    - role: internal.template.example
      vars:
        ncs_action: collect
```
