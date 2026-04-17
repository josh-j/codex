# internal.windows

Windows audit, health checks, STIG compliance, and Active Directory operations.

## Roles

| Role | Purpose | Actions | Profiles | Operations |
|---|---|---|---|---|
| [server](roles/server/README.md) | Windows Server audit, health, and maintenance | `collect`, `audit`, `remediate`, `verify` | `stig`, `health` | `patch`, `registry_fix`, `kb_install`, `windows_update`, `update_software`, `uninstall_software`, `service`, `scheduled_task`, `cleanup`, `ad_search`, `vuln_scan`, `openssh`, `winrm_enable`, `remote_ops` |
| [domain](roles/domain/README.md) | Active Directory domain queries | `collect`, `audit` | — | `user_search`, `group_search`, `computer_search`, `ou_search`, `group_membership`, `privileged_groups`, `stale_accounts`, `password_policy`, `gpo_audit`, `dns_zones`, `dhcp_scopes`, `domain_trusts` |

Both roles use `internal.core.dispatch` with dynamic dispatch for operation routing.

Depends on `internal.core` (`>=1.0.0,<2.0.0`).

## Installation

```bash
# from a built tarball
ansible-galaxy collection install internal-windows-<version>.tar.gz

# or via the app repo's requirements.yml manifest
ansible-galaxy collection install -r requirements.yml
```

Playbooks ship under `playbooks/` inside the collection; invoke by FQCN:

```bash
ansible-playbook -i inventory/production internal.windows.server_collect
ansible-playbook -i inventory/production internal.windows.server_stig_audit
```

## Server Health Checks

The `health` profile runs: disk, memory/CPU, network, OS info, event logs, secure channel, services, and reboot-pending checks.

## Server Update Management

Software update operations cover Chrome, Edge, Office, Notepad++, ConfigMgr, and general Windows Update.
