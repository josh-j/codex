# internal.windows

Windows audit, health checks, STIG compliance, and Active Directory operations.

## Roles

| Role | Purpose | Actions | Profiles | Operations |
|---|---|---|---|---|
| [server](roles/server/README.md) | Windows Server audit, health, and maintenance | `collect`, `audit`, `remediate`, `verify` | `stig`, `health` | `patch`, `registry_fix`, `kb_install`, `windows_update`, `update_software`, `uninstall_software`, `service`, `scheduled_task`, `cleanup`, `ad_search`, `vuln_scan`, `openssh`, `winrm_enable`, `remote_ops` |
| [domain](roles/domain/README.md) | Active Directory domain queries | `collect`, `audit` | — | `user_search`, `group_search`, `computer_search`, `ou_search`, `group_membership`, `privileged_groups`, `stale_accounts`, `password_policy`, `gpo_audit`, `dns_zones`, `dhcp_scopes`, `domain_trusts` |

Both roles use `internal.core.dispatch` with dynamic dispatch for operation routing.

## Server Health Checks

The `health` profile runs: disk, memory/CPU, network, OS info, event logs, secure channel, services, and reboot-pending checks.

## Server Update Management

Software update operations cover Chrome, Edge, Office, Notepad++, ConfigMgr, and general Windows Update.
