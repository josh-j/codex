# NCS Playbooks Reference

This directory contains the Ansible playbooks for fleet-wide auditing, remediation, and reporting.

## Orchestration & Reporting

- **`site.yml`**: Master orchestrator for full-fleet audits. Executes environment setup, platform audits (VMware, Linux, Windows), and final report generation in a single run.
- **`site_collect_only.yml`**: Collection-only orchestration. Runs setup and platform audits without report rendering.
- **`site_reports_only.yml`**: Reporting-only orchestration. Renders dashboards from existing artifacts.
- **`site_vmware_only.yml`**: VMware-only orchestration with report rendering.
- **`generate_reports.yml`**: Unified reporting bridge. Exports inventory metadata and invokes the `ncs-reporter` Python CLI to process raw telemetry into HTML dashboards.
- **`setup_env.yml`**: Infrastructure bootstrap. Initializes local artifact directories and remote report folder structures with required permissions.
- **`setup_samba.yml`**: Service deployment. Configures the Samba share used to host and serve the generated dashboards.

## Platform Audits (Read-Only Collection)

These playbooks are purely collectors that gather un-normalized state via the `ncs_collector` callback.

- **`ubuntu_audit.yml`**: Read-only collection of Linux system health, hardware utilization, service status, and security configuration.
- **`ubuntu_discover.yml`**: Phase playbook for Ubuntu discovery only.
- **`vmware_audit.yml`**: Full read-only VMware collection (vCenter + ESXi + VM data) for unified reporting.
- **`vmware_vcenter_audit.yml`**: Read-only VMware control-plane audit focused on vCenter appliance and alarms.
- **`vmware_vcsa_stig_audit.yml`**: Read-only VCSA STIG audit for appliance security controls.
- **`vmware_esxi_audit.yml`**: Read-only VMware infrastructure audit focused on ESXi hosts and datastores.
- **`vmware_vm_audit.yml`**: Read-only VMware workload audit focused on VMs and snapshots.
- **`windows_audit.yml`**: Read-only collection of Windows health metrics, installed software, and update status.
- **`windows_post_patch_audit.yml`**: Phase playbook for post-patch Windows verification.
- **`vmware_collect.yml`**: Compatibility alias to `vmware_audit.yml`.

## STIG Compliance & Hardening

Security-focused playbooks for baseline verification and automated enforcement.

- **`*_stig_audit.yml`**: Read-only compliance verification. Executes checks against DISA STIG requirements and emits raw STIG telemetry via `ncs_collector`.
- **`*_stig_remediate.yml`**: State enforcement. Applies configuration changes to align systems with STIG security requirements.
- **`vmware_vcsa_stig_remediate.yml`**: VCSA STIG hardening plus post-remediation compliance verification.
- **`ubuntu_remediate.yml`**: General security hardening and configuration enforcement for Ubuntu hosts outside the formal STIG baseline.
- **`ubuntu_remediate_apply.yml`**: Phase playbook that applies non-STIG Ubuntu remediation.
- **`ubuntu_stig_remediate_apply.yml`**: Phase playbook that applies Ubuntu STIG remediation.
- **`ubuntu_stig_verify.yml`**: Phase playbook that runs Ubuntu STIG verification.

## Lifecycle & Maintenance

- **`*_patch.yml`**: Software lifecycle management. Orchestrates OS-level package updates and reboots for Linux and Windows.
- **`ubuntu_patch_apply.yml`**: Phase playbook that applies Ubuntu patching actions.
- **`windows_update.yml`**: Phase playbook that applies Windows updates.
- **`ubuntu_rotate_passwords.yml`**: Security utility for automated rotation and management of local system passwords.

## Usage

Standard execution via `ansible-playbook`:

```bash
# Full fleet audit and report generation
ansible-playbook playbooks/site.yml

# Read-only VMware STIG audits
ansible-playbook playbooks/vmware_esxi_stig_audit.yml
ansible-playbook playbooks/vmware_vm_stig_audit.yml

# Ubuntu package patching
ansible-playbook playbooks/ubuntu_patch.yml
```
