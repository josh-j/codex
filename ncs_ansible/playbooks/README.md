# NCS Playbooks Reference

This directory contains the Ansible playbooks for fleet-wide auditing, remediation, and reporting.

## Orchestration & Reporting

- **`site.yml`**: Master orchestrator for full-fleet audits. Executes environment setup, platform audits (VMware, Linux, Windows), and final report generation in a single run.
- **`generate_reports.yml`**: Unified reporting bridge. Exports inventory metadata and invokes the `ncs-reporter` Python CLI to process raw telemetry into HTML dashboards.
- **`setup_env.yml`**: Infrastructure bootstrap. Initializes local artifact directories and remote report folder structures with required permissions.
- **`setup_samba.yml`**: Service deployment. Configures the Samba share used to host and serve the generated dashboards.

## Platform Audits (Read-Only Collection)

These playbooks are purely collectors that gather un-normalized state via the `ncs_collector` callback.

- **`ubuntu_audit.yml`**: Read-only collection of Linux system health, hardware utilization, service status, and security configuration.
- **`vmware_audit.yml`**: Read-only collection of vCenter and ESXi health, alarms, resource utilization, and inventory state.
- **`windows_audit.yml`**: Read-only collection of Windows health metrics, installed software, and update status.
- **`vmware_collect.yml`**: Lightweight read-only collection focused strictly on vCenter inventory discovery.

## STIG Compliance & Hardening

Security-focused playbooks for baseline verification and automated enforcement.

- **`*_stig_audit.yml`**: Read-only compliance verification. Executes checks against DISA STIG requirements and generates XCCDF-compliant JSON/XML results via the `stig_xml` callback.
- **`*_stig_remediate.yml`**: State enforcement. Applies configuration changes to align systems with STIG security requirements.
- **`ubuntu_remediate.yml`**: General security hardening and configuration enforcement for Ubuntu hosts outside the formal STIG baseline.

## Lifecycle & Maintenance

- **`*_patch.yml`**: Software lifecycle management. Orchestrates OS-level package updates and reboots for Linux and Windows.
- **`ubuntu_rotate_passwords.yml`**: Security utility for automated rotation and management of local system passwords.

## Usage

Standard execution via `ansible-playbook`:

```bash
# Full fleet audit and report generation
ansible-playbook playbooks/site.yml

# Read-only VMware STIG audit
ansible-playbook playbooks/vmware_stig_audit.yml

# Ubuntu package patching
ansible-playbook playbooks/ubuntu_patch.yml
```
