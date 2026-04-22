# internal.windows.server

Windows Server audit, health check, STIG compliance, and maintenance operations.

## Interface

Specify behavior via `ncs_action`, plus optional `ncs_profile` or `ncs_operation`.

### `ncs_action: audit` (Default)
Collects system info, installed applications, and ConfigMgr status.

### `ncs_action: audit`, `ncs_profile: stig`
Performs Windows Server STIG compliance checks.

### `ncs_action: audit`, `ncs_profile: health`
Runs health checks: disk, memory/CPU, services, event logs, secure channel, reboot pending.

### `ncs_action: remediate`, `ncs_operation: <operation>`
Available operations: `patch`, `registry_fix`, `kb_install`, `windows_update`,
`update_software`, `uninstall_software`, `service`, `scheduled_task`, `cleanup`,
`ad_search`, `vuln_scan`, `openssh`, `winrm_enable`, `remote_ops`.

## Prerequisites

- WinRM credentials from inventory (`ansible_connection: winrm` in `group_vars/windows_servers`)
- Hosts in `windows_servers` inventory group

## Usage

```yaml
- hosts: windows_servers
  roles:
    - role: internal.windows.server
      vars:
        ncs_action: audit
        ncs_profile: stig
```
