# internal.windows.domain

Active Directory domain audit and query operations.

## Interface

Driven primarily by `ncs_operation` — each operation queries a specific AD aspect.

### `ncs_action: collect`
Collects domain controller and AD topology information.

### `ncs_action: audit`, `ncs_operation: <operation>`
Available operations: `user_search`, `group_search`, `computer_search`, `ou_search`,
`group_membership`, `privileged_groups`, `stale_accounts`, `password_policy`,
`gpo_audit`, `dns_zones`, `dhcp_scopes`, `domain_trusts`.

## Prerequisites

- WinRM credentials from inventory
- Hosts in `windows_servers` inventory group (domain controllers)
- `domain_search_base` set for query operations
- `domain_dhcp_server` set for `dhcp_scopes` operation

## Usage

```yaml
- hosts: windows_servers
  roles:
    - role: internal.windows.domain
      vars:
        ncs_action: audit
        ncs_operation: stale_accounts
        domain_search_base: "DC=example,DC=mil"
```
