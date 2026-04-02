# NCS Playbooks Reference

This directory contains the Ansible playbooks for fleet-wide auditing, remediation, and reporting.
Playbooks are organized into platform subdirectories for discoverability.

Most platform playbooks now drive roles through the shared interface:
`ncs_action`, optional `ncs_profile`, and optional `ncs_operation`.

## Directory Structure

```
playbooks/
├── site*.yml           # Top-level orchestrators
├── group_vars/         # Shared variables
├── templates/          # Shared Jinja2 templates
├── vmware/             # VMware cross-component orchestrators
├── esxi/               # ESXi STIG and audit playbooks
├── vcsa/               # VCSA (vCenter Server Appliance) playbooks
├── vm/                 # VM STIG and audit playbooks
├── ubuntu/             # Ubuntu/Linux playbooks
├── windows/            # Windows playbooks
├── photon/             # Photon OS playbooks
├── infra/              # Infrastructure setup & reporting
└── test/               # Test/lab playbooks
```

Each subdirectory contains a `group_vars` symlink to `../group_vars` so inventory variables resolve correctly regardless of which subdirectory a playbook runs from.

## Orchestration & Reporting

- **`site.yml`**: Master orchestrator for full-fleet audits. Executes environment setup, platform audits (VMware, Linux, Windows), and final report generation in a single run.
- **`site_collect_only.yml`**: Collection-only orchestration. Runs setup and platform audits without report rendering.
- **`site_reports_only.yml`**: Reporting-only orchestration. Renders dashboards from existing artifacts.
- **`site_vmware_only.yml`**: VMware-only orchestration with report rendering.
- **`infra/generate_reports.yml`**: Unified reporting bridge. Exports inventory metadata and invokes the `ncs-reporter` Python CLI to process raw telemetry into HTML dashboards.
- **`infra/setup_env.yml`**: Infrastructure bootstrap. Initializes local artifact directories and remote report folder structures with required permissions.
- **`infra/setup_samba.yml`**: Service deployment. Configures the Samba share used to host and serve the generated dashboards.

## Platform Audits (Read-Only Collection)

These playbooks are purely collectors that gather un-normalized state via the `ncs_collector` callback.

- **`ubuntu/audit.yml`**: Read-only collection of Linux system health, hardware utilization, service status, and security configuration.
- **`ubuntu/discover.yml`**: Phase playbook for Ubuntu discovery only.
- **`vmware/audit.yml`**: Full read-only VMware collection (vCenter + ESXi + VM data) for unified reporting.
- **`vcsa/audit.yml`**: Read-only VMware control-plane audit focused on vCenter appliance and alarms.
- **`vcsa/stig_audit.yml`**: Read-only VCSA STIG audit for appliance security controls.
- **`esxi/audit.yml`**: Read-only VMware infrastructure audit focused on ESXi hosts and datastores.
- **`vm/audit.yml`**: Read-only VMware workload audit focused on VMs and snapshots.
- **`windows/audit.yml`**: Read-only collection of Windows health metrics, installed software, and update status.
- **`windows/post_patch_audit.yml`**: Phase playbook for post-patch Windows verification.
- **`vmware/collect.yml`**: Compatibility alias to `vmware/audit.yml`.

## STIG Compliance & Hardening

Security-focused playbooks for baseline verification and automated enforcement.

- **`**/stig_audit.yml`**: Read-only compliance verification. Executes checks against DISA STIG requirements and emits raw STIG telemetry via `ncs_collector`.
- **`**/stig_remediate.yml`**: State enforcement. Applies configuration changes to align systems with STIG security requirements.
- **`vcsa/stig_remediate.yml`**: VCSA STIG hardening plus post-remediation compliance verification.
- **`ubuntu/stig_remediate_apply.yml`**: Phase playbook that applies Ubuntu STIG remediation.
- **`ubuntu/stig_verify.yml`**: Phase playbook that runs Ubuntu STIG verification.

## Lifecycle & Maintenance

- **`**/patch.yml`**: Software lifecycle management. Orchestrates OS-level package updates and reboots for Linux and Windows.
- **`ubuntu/patch_apply.yml`**: Phase playbook that applies Ubuntu patching actions.
- **`windows/update.yml`**: Phase playbook that applies Windows updates.
- **`ubuntu/password_rotate_bulk.yml`**: Security utility for automated rotation and management of local system passwords.

## Usage

Standard execution via `ansible-playbook`:

```bash
# Full fleet audit and report generation
ansible-playbook playbooks/site.yml

# Read-only VMware STIG audits
ansible-playbook playbooks/vmware/esxi/stig_audit.yml
ansible-playbook playbooks/vmware/vm/stig_audit.yml
ansible-playbook playbooks/vmware/vcsa/stig_audit.yml

# Ubuntu package patching
ansible-playbook playbooks/linux/ubuntu/patch.yml
```
