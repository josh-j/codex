# NCS App-Layer Playbooks

This directory is the **application layer** of `ncs-ansible`. It contains the
site orchestrators and shared NCS infrastructure playbooks. Per-platform
playbooks now live inside their respective collections under `internal/`
(see the `internal/<collection>/playbooks/` directories).

## Directory Structure

```
playbooks/
├── site.yml, site_*.yml   # Site orchestrators (chain platform phases)
├── ncs/                   # NCS infra: report dir init, report gen, samba, timers
│   ├── setup_env.yml
│   ├── generate_reports.yml
│   ├── setup_samba.yml
│   └── manage_schedules.yml
├── core/                  # Localhost alerting
│   └── send_alert_email.yml
└── templates/             # Shared Jinja2 templates (smb.conf, systemd units)
```

All shared variables (SMTP, reporting paths, `ncs_config`) now live under
`inventory/production/group_vars/all/`, auto-loaded by Ansible when the
site orchestrators run against the production inventory.

## Collection playbooks (invoke by FQCN)

| Collection | Playbooks |
|---|---|
| `internal.vmware` | `collect`, `esxi_collect`, `esxi_stig_audit`, `esxi_stig_remediate`, `esxi_password_status`, `esxi_password_rotate`, `esxi_refresh_inventory`, `vcsa_collect`, `vcsa_stig_audit`, `vcsa_stig_remediate`, `vcsa_password_*`, `vm_collect`, `vm_stig_audit`, `vm_stig_remediate`, `vm_stig_*_parallel` |
| `internal.linux` | `ubuntu_collect`, `ubuntu_stig_audit`, `ubuntu_stig_remediate`, `ubuntu_stig_verify`, `ubuntu_update`, `ubuntu_password_*`, `ubuntu_run`, `photon_stig_audit`, `photon_stig_remediate`, `photon_password_*` |
| `internal.windows` | `server_collect`, `server_health`, `server_stig_audit`, `server_stig_remediate`, `server_run`, `server_cleanup`, `server_kb_install`, `server_openssh`, `server_registry_fix`, `server_windows_update`, `server_patch`, `server_scheduled_task`, `server_service`, `server_vuln_scan`, `server_winrm_enable`, `server_remote_ops`, `server_ad_search`, `server_update_software`, `server_uninstall_software`, `domain_collect`, `domain_run` |

## Usage

```bash
# Full fleet audit + report generation
ansible-playbook -i inventory/production playbooks/site.yml

# Site-level STIG audit across every platform
ansible-playbook -i inventory/production playbooks/site_stig_audit.yml

# Per-platform action via FQCN (invokes the collection directly)
ansible-playbook -i inventory/production internal.vmware.esxi_stig_audit
ansible-playbook -i inventory/production internal.linux.ubuntu_collect
ansible-playbook -i inventory/production internal.windows.server_stig_remediate
```

Every platform playbook accepts the shared role interface vars:
`ncs_action`, `ncs_profile`, and `ncs_operation`.
