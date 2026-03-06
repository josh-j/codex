# internal.windows.windows

Unified role for managing and auditing Windows systems.

## Actions

Specify the action via the `windows_action` variable.

### `audit` (Default)
Collects system info, installed applications, and ConfigMgr status.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats`.

### `stig`
Performs native Windows STIG compliance checks.
- **Handoff:** Emits raw findings via `ansible.builtin.set_stats`.


## Usage

```yaml
- name: Audit Windows Fleet
  hosts: windows_servers
  roles:
    - role: internal.windows.windows
      vars:
        windows_action: audit
```
