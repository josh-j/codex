# OpenSSH + Kerberos/GSSAPI for Domain-Joined Windows Servers

Hybrid connection strategy: **WinRM for bootstrap, SSH for steady-state management** using Kerberos (GSSAPI) authentication via a dedicated AD service account. No passwords on the wire, no authorized_keys distribution.

## Architecture

```
┌──────────────┐   WinRM (bootstrap)   ┌──────────────────┐
│ Ansible       │ ───────────────────► │ Windows Server    │
│ Control Node  │                      │ (domain-joined)   │
│               │   SSH + GSSAPI       │                   │
│ krb5.conf     │ ───────────────────► │ sshd + GSSAPI     │
│ svc-ansible@  │   (steady-state)     │                   │
└──────────────┘                       └──────────────────┘
```

## Prerequisites

### Control Node

1. **Kerberos client libraries**: `sudo apt install krb5-user libkrb5-dev`
2. **Python Kerberos bindings**: `pip install pywinrm[kerberos] pykerberos` (included in project venv)
3. **krb5.conf**: Copy `files/krb5.conf.example` to `/etc/krb5.conf` and update with your domain's realm and KDC hostnames
4. **Service account**: Create an AD service account (e.g. `svc-ansible`) and obtain a keytab or use `kinit svc-ansible@YOURDOMAIN.MIL` before running playbooks

### Windows Target

- Must be domain-joined
- WinRM must be enabled for initial bootstrap (see `just windows-winrm-enable`)
- No manual SSH setup required — the bootstrap playbook handles everything

## Usage

### First-time Bootstrap (WinRM)

Install OpenSSH and deploy the managed `sshd_config` on a new Windows server:

```bash
just windows-openssh-bootstrap <hostname>

# Use NTLM instead of Kerberos for WinRM transport:
just windows-openssh-bootstrap <hostname> ntlm
```

This runs the `openssh.yml` playbook over WinRM, which:
1. Installs Win32-OpenSSH server capability
2. Starts sshd and sets it to auto-start
3. Opens firewall port 22
4. Sets default shell to PowerShell
5. Deploys managed `sshd_config` with GSSAPI enabled
6. Restarts sshd to apply config

### Steady-state Management (SSH)

After bootstrap, all other playbooks connect over SSH using the `windows_servers` inventory group:

```bash
just windows-health <hostname>
just audit-windows <hostname>
```

The inventory group (`inventory/production/hosts.yaml`) is pre-configured with SSH + GSSAPI connection vars.

## Configuration

### Inventory Variables (`inventory/production/hosts.yaml`)

The `windows_servers` group sets these connection vars:

| Variable | Default | Purpose |
|---|---|---|
| `ansible_connection` | `ssh` | Use SSH instead of WinRM |
| `ansible_shell_type` | `powershell` | PowerShell as remote shell |
| `ansible_user` | `svc-ansible@YOURDOMAIN.MIL` | AD service account (update for your domain) |
| `ansible_ssh_common_args` | `-o GSSAPIAuthentication=yes ...` | Enable Kerberos auth on the SSH client side |

### Role Defaults (`defaults/main.yaml`)

These control the deployed `sshd_config`:

| Variable | Default | Purpose |
|---|---|---|
| `windows_openssh_manage_config` | `true` | Deploy managed sshd_config |
| `windows_openssh_allow_gssapi` | `true` | Enable GSSAPI/Kerberos authentication |
| `windows_openssh_allow_password` | `false` | Disable password authentication |
| `windows_openssh_allow_pubkey` | `false` | Disable public key authentication |
| `windows_openssh_allow_groups` | `[]` | Restrict SSH access to specific AD groups |
| `windows_openssh_max_auth_tries` | `3` | Maximum authentication attempts |
| `windows_openssh_client_alive_interval` | `300` | Keepalive interval (seconds) |
| `windows_openssh_client_alive_count_max` | `3` | Missed keepalives before disconnect |

### Example: Lock down to a specific AD group with GSSAPI only

```yaml
# host_vars or group_vars override
windows_openssh_allow_gssapi: true
windows_openssh_allow_password: false
windows_openssh_allow_pubkey: false
windows_openssh_allow_groups:
  - SG-Ansible-Admins
  - Domain Admins
```

## Inventory Setup

Add your Windows hosts to `inventory/production/hosts.yaml`:

```yaml
    windows_servers:
      vars:
        ansible_connection: ssh
        ansible_shell_type: powershell
        ansible_user: svc-ansible@YOURDOMAIN.MIL
        ansible_ssh_common_args: '-o GSSAPIAuthentication=yes -o GSSAPIServerIdentity=yes'
      hosts:
        win-app01.yourdomain.mil:
        win-db01.yourdomain.mil:
```

## Verification

After bootstrapping a host, verify SSH + GSSAPI works:

```bash
# 1. Get a Kerberos ticket
kinit svc-ansible@YOURDOMAIN.MIL

# 2. Test SSH directly
ssh -o GSSAPIAuthentication=yes svc-ansible@YOURDOMAIN.MIL@win-app01.yourdomain.mil

# 3. Test via Ansible
just windows-health win-app01.yourdomain.mil
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `kinit: Cannot find KDC for realm` | Check `/etc/krb5.conf` realm and KDC settings, verify DNS resolves KDC hostnames |
| `GSSAPI Error: No credentials were supplied` | Run `kinit svc-ansible@YOURDOMAIN.MIL` and verify with `klist` |
| SSH falls back to password prompt | Verify `GSSAPIAuthentication yes` in target's `sshd_config`, check SPN registration for the host |
| `Permission denied` after GSSAPI succeeds | Check `AllowGroups` in sshd_config — the service account must be in an allowed group |
| Bootstrap fails over WinRM | Ensure WinRM is enabled (`just windows-winrm-enable <host>`) and the transport matches (kerberos vs ntlm) |
