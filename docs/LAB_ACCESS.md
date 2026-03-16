# Lab Access

This document consolidates the current lab environment credentials and access
paths used during the VCSA/STIG migration work.

## Hosts

### Reporting Host / Codex Workspace

- Role: report generation host, Samba share host, current workspace host
- IP: `192.168.2.110`
- Access:
  - Local shell on this machine
  - Samba share for reports
- Samba:
  - Share: `NCSReports`
  - URL: `smb://192.168.2.110/NCSReports`
  - Username: `ansible`
  - Password: `ineption`

### Proxmox

- Role: jump point / management path used when direct host access is unavailable
- IP: `192.168.2.36`
- Access:
  - SSH
- Username: `root`
- Password: `ineption`
- Example:
  ```bash
  ssh root@192.168.2.36
  ```

### ESXi Host

- Role: ESXi host running the VCSA VM
- IP: `192.168.2.118`
- Access:
  - Direct SSH is disabled
  - Reach/manage through Proxmox
- Username: `root`
- Password: `12qwaszx!@QWASZX`
- Notes:
  - Snapshot work for the VCSA was performed against this host
  - If shell access is needed, use Proxmox as the entry path first

### VCSA

- Role: test vCenter Server Appliance used for STIG migration/testing
- Name: `test-vcsa`
- IP: `192.168.2.120`
- Access:
  - HTTPS UI: `https://192.168.2.120/ui`
  - VAMI: `https://192.168.2.120:5480`
  - SSH as `root`
- Credentials:
  - `root` / `Ineption123!`
  - `Administrator@vsphere.local` / `Ineption123!`
- Notes:
  - Bash shell access was enabled temporarily during automation work

## Service-Specific Notes

### VCSA UI / SSO

- URL: `https://192.168.2.120/ui`
- Username: `Administrator@vsphere.local`
- Password: `Ineption123!`

### VAMI

- URL: `https://192.168.2.120:5480`
- Username: `root`
- Password: `Ineption123!`

## Access Paths

### Reach ESXi Through Proxmox

Use Proxmox as the management entry point when ESXi SSH is disabled.

1. SSH to Proxmox:
   ```bash
   ssh root@192.168.2.36
   ```
2. From there, use the Proxmox-side tools/workflow to manage the ESXi-backed VM.

### Reach VCSA Directly

- Browser:
  - `https://192.168.2.120/ui`
  - `https://192.168.2.120:5480`
- SSH:
  ```bash
  ssh root@192.168.2.120
  ```

### Reach Reports From macOS

In Finder, use:

```text
smb://192.168.2.110/NCSReports
```

Credentials:

- Username: `ansible`
- Password: `ineption`

## Snapshot History

### VCSA Pre-Migration Snapshot

- VM: `test-vcsa`
- ESXi host: `192.168.2.118`
- Snapshot name: `vcsa-pre-migration-20260315T164950Z`
- Description: `Pre-migration snapshot before VCSA EAM STIG migration work`

## Common Commands

### SSH

#### Proxmox

```bash
ssh root@192.168.2.36
```

#### VCSA Root

```bash
ssh root@192.168.2.120
```

#### Non-interactive VCSA SSH

```bash
sshpass -p 'Ineption123!' ssh -o StrictHostKeyChecking=no root@192.168.2.120
```

### Ansible Environment

- Ansible config: `/tmp/ansible-vcsa.cfg`
- Inventory: `/tmp/vcsa-eam-inventory.yml`
- Playbook runner: `/tmp/venv-vcsa-316/bin/ansible-playbook`

### VCSA STIG Audit

#### Full VCSA service audit

```bash
ANSIBLE_CONFIG=/tmp/ansible-vcsa.cfg \
/tmp/venv-vcsa-316/bin/ansible-playbook \
  -f 1 \
  -i /tmp/vcsa-eam-inventory.yml \
  playbooks/vmware_vcsa_stig_audit.yml \
  -l test-vcsa-eam \
  -e '{"vault_vcenter_ssh_password":"Ineption123!"}'
```

#### Full VCSA service remediation

```bash
ANSIBLE_CONFIG=/tmp/ansible-vcsa.cfg \
/tmp/venv-vcsa-316/bin/ansible-playbook \
  -f 1 \
  -i /tmp/vcsa-eam-inventory.yml \
  playbooks/vmware_vcsa_stig_remediate.yml \
  -l test-vcsa-eam \
  -e '{"vault_vcenter_ssh_password":"Ineption123!"}'
```

#### Single-role audit example

```bash
ANSIBLE_CONFIG=/tmp/ansible-vcsa.cfg \
/tmp/venv-vcsa-316/bin/ansible-playbook \
  -f 1 \
  -i /tmp/vcsa-eam-inventory.yml \
  playbooks/vmware_vcsa_stig_audit.yml \
  -l test-vcsa-eam \
  -e '{"vault_vcenter_ssh_password":"Ineption123!","vcenter_stig_roles":["internal.vmware.vcsa_sts"]}'
```

#### Single-role remediation example

```bash
ANSIBLE_CONFIG=/tmp/ansible-vcsa.cfg \
/tmp/venv-vcsa-316/bin/ansible-playbook \
  -f 1 \
  -i /tmp/vcsa-eam-inventory.yml \
  playbooks/vmware_vcsa_stig_remediate.yml \
  -l test-vcsa-eam \
  -e '{"vault_vcenter_ssh_password":"Ineption123!","vcenter_stig_roles":["internal.vmware.vcsa_sts"]}'
```

### Report Generation

#### Render HTML and CKLB reports

```bash
./ncs_reporter/.venv/bin/python -m ncs_reporter.cli all \
  --platform-root /srv/samba/reports/platform \
  --reports-root /srv/samba/reports \
  --groups /srv/samba/reports/platform/inventory_groups.json \
  --report-stamp 20260316 \
  --config-dir files/ncs_reporter_configs
```

### Manual Validation Examples

#### VAMI cipher/FIPS checks

```bash
sshpass -p 'Ineption123!' ssh -o StrictHostKeyChecking=no root@192.168.2.120 \
  "/bin/bash -lc '/opt/vmware/sbin/vami-lighttpd -p -f /opt/vmware/etc/lighttpd/lighttpd.conf 2>/dev/null | grep \"ssl.cipher-list\" | sed -e \"s/^[ ]*//\"; /opt/vmware/sbin/vami-lighttpd -p -f /opt/vmware/etc/lighttpd/lighttpd.conf 2>/dev/null | grep \"server.fips-mode\" | sed -e \"s/^[ ]*//\"'"
```

#### Envoy syslog rule check

```bash
sshpass -p 'Ineption123!' ssh -o StrictHostKeyChecking=no root@192.168.2.120 \
  "/bin/bash -lc 'rpm -V VMware-visl-integration | grep vmware-services-envoy.conf | grep \"^..5......\" || true'"
```
