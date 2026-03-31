# internal.windows.server

Unified role for managing and auditing Windows systems.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: audit` (Default)
Collects system info, installed applications, and ConfigMgr status.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats`.

### `ncs_action: audit`, `ncs_profile: stig`
Performs native Windows STIG compliance checks.
- **Handoff:** Emits raw findings via `ansible.builtin.set_stats`.

### `ncs_action: audit`, `ncs_profile: health`
Runs the Windows health-check workflow.

### `ncs_action: remediate`, `ncs_operation: ...`
Runs targeted admin and maintenance workflows such as `patch`, `registry_fix`,
`kb_install`, `windows_update`, `remote_ops`, `service`, and `scheduled_task`.


## Usage

```yaml
- name: Audit Windows Fleet
  hosts: windows_servers
  roles:
    - role: internal.windows.server
      vars:
        ncs_action: audit
```
