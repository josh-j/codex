# internal.linux.ubuntu

Unified role for managing and auditing Ubuntu systems.

## Actions

Specify the action via the `ubuntu_action` variable.

### `discover` (Default)
Collects system facts, security settings, and update status.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats`.


### `remediate`
Applies system hardening and maintenance tasks.

### `stig`
Performs STIG compliance evaluation.
- **Handoff:** Emits STIG telemetry via `ansible.builtin.set_stats` and `ncs_collector`.

### `passwords`
Manages user passwords and aging policies.

## Usage

```yaml
- name: Collect Ubuntu Discovery
  hosts: ubuntu_servers
  roles:
    - role: internal.linux.ubuntu
      vars:
        ubuntu_action: discover
```
