# Codex - Ansible DC Automation & Audit

This project provides Ansible-based automation for data center operational health checks and STIG (Security Technical Implementation Guide) compliance auditing across various infrastructure platforms.

## Project Overview

The system is designed to perform daily health monitoring and security audits for:
- **Virtualization:** VMware vCenter and ESXi hosts.
- **Storage:** Dell Unity arrays and Data Domain (backup).
- **Compute:** Cisco UCS Fabric Interconnects.
- **Operating Systems:** Ubuntu Linux and Windows Server.

It utilizes a centralized reporting engine that aggregates data from multiple sites and renders them into HTML and Markdown dashboards.

## Key Technologies

- **Ansible:** Core automation engine.
- **Python:** Used for custom audit logic and API interactions (pyVmomi for VMware).
- **PowerShell:** Used for ESXi and Windows fact gathering.
- **Jinja2:** Extensive use for dynamic reporting templates.

## Architecture

The project is organized into modular **Ansible Collections** located in `collections/ansible_collections/internal/`. All logic follows a standard three-play lifecycle (Initialize -> Execute -> Aggregate).

### Core Collections
- **`internal.core`**: Centralized reporting engine, common utilities, logging, and **STIG compliance shared logic**.
- **`internal.linux`**: Ubuntu system discovery, auditing, and STIG compliance.
- **`internal.vmware`**: Unified VMware automation including:
    - **Discovery:** Inventory and appliance health.
    - **Audit:** Health checks, configuration compliance, and reporting.
    - **Remediation:** Configuration fixes (e.g., HA/DRS).
    - **STIG:** ESXi and VM Guest compliance.
- **`internal.windows`**: Windows Server application and security auditing.
- **`internal.storage`**: Dell Unity and Data Domain health monitoring.
- **`internal.compute`**: Cisco UCS Fabric Interconnect status checks.
- **`internal.templates`**: Boilerplate roles for rapid onboarding of new infrastructure platforms.

### Project Structure
- **Inventory:** Site-specific configurations in `inventory/production/`.
- **Playbooks:** Orchestration entry points for health, STIG, and OS audits.
- **Reporting:** Centralized aggregation via the `internal.core.reporting` role.

## Key Commands

### Environment Setup
The project expects a Python virtual environment and a vault password file.
- **Activate Environment:** `source .venv/bin/activate`
- **Validate Environment:** `ansible-playbook playbooks/validate_environment.yaml`

### Running Automation
- **Daily Health Checks:**
  ```bash
  ansible-playbook -i inventory/production playbooks/site_health.yaml
  ```
- **STIG Compliance Audits:**
  ```bash
  ansible-playbook -i inventory/production playbooks/audit_stigs.yaml
  ```
- **Ubuntu System Audit:**
  ```bash
  ansible-playbook -i inventory/production playbooks/site_ubuntu.yaml
  ```

## Development Conventions

- **Shared Context:** Uses a global `run_ctx` (Run ID, timestamp, run-day) created at the start of a run on `localhost` and shared via `hostvars['localhost']`.
- **Reporting Logic:** STIG reporting tasks are delegated to the `stig` role in the `internal.core` collection.
- **Tags:** Use tags (`vmware`, `esxi`, `linux`, `stig`) to target specific platforms or audit types.
- **Credentials:** Credential bridging logic in playbooks ensures compatibility across different inventory sources.
- **Vault:** Sensitive data is protected using Ansible Vault; a `.vaultpass` file is required in the parent directory or configured in `ansible.cfg`.
