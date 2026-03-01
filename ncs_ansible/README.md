# NCS (Network Compliance & Status)

Ansible-based system for auditing and reporting on Linux (Ubuntu), VMware (ESXi/vCenter), and Windows environments.

## Architecture: Decoupled Pipeline

Reporting is decoupled from Ansible to separate data collection from processing.

1.  **Collection (Ansible):** Roles in `collections/ansible_collections/internal/` execute on target hosts and emit raw telemetry via `ansible.builtin.set_stats`.
2.  **Persistence (Callback):** The `ncs_collector` callback plugin saves telemetry to disk as raw YAML files.
3.  **Reporting (Python):** The `ncs_reporter` CLI tool (located in `tools/ncs_reporter/`) ingests the YAML, normalizes the data, applies health-check logic, and renders HTML dashboards using Jinja2.

## Project Structure

- `collections/ansible_collections/internal/`:
    - `core/`: Shared reporting logic, callbacks, and orchestration roles.
    - `linux/`, `vmware/`, `windows/`: Platform-specific collection and remediation roles.
- `tools/ncs_reporter/`: Standalone Python reporting engine.
- `playbooks/`: Entry points for audits, patching, and STIG remediation.
- `inventory/`: Fleet definitions and configuration.
- `docs/`: Architectural documentation and engineering standards.

## Operational Workflow

### Playbook Execution Flow (`site.yml`)
The main entry point `playbooks/site.yml` orchestrates the audit lifecycle across the fleet:
1.  **Phase 1: Environment Readiness** (`setup_env.yml`) - Configures reporting directories and ensures prerequisites.
2.  **Phase 2: VMware Infrastructure** (`vmware_audit.yml`) - Audits vCenter and ESXi health/inventory.
3.  **Phase 3: Linux/Windows Fleet** (`ubuntu_audit.yml`, `windows_audit.yml`) - Performs system-level audits.
4.  **Phase 4: Unified Reporting** (`generate_reports.yml`) - Invokes the `ncs-reporter` CLI to process the collected YAML data into HTML dashboards.

### Directory & Report Structure
Reports are persisted to a central directory (default `/srv/samba/reports/`).

**Data Lake Structure:**
```text
/srv/samba/reports/
├── index.html                  # Site-wide Dashboard (Fleet Overview)
├── inventory_groups.json       # Exported Ansible inventory for reporter
├── platform/
│   ├── linux/
│   │   ├── linux_health_report.html
│   │   └── <hostname>/
│   │       ├── raw_ubuntu_audit.yaml
│   │       └── node_report.html
│   ├── vmware/
│   │   ├── vmware_health_report.html
│   │   └── <vcenter_name>/
│   │       ├── raw_vcenter_audit.yaml
│   │       └── node_report.html
│   └── windows/
│       ├── windows_health_report.html
│       └── <hostname>/
│           ├── raw_windows_audit.yaml
│           └── node_report.html
└── stig/
    ├── stig_fleet_report.html  # Unified STIG Overview
    └── <hostname>/
        ├── xccdf-results_<hostname>.json
        ├── xccdf-results_<hostname>.xml
        ├── <hostname>_ubuntu.cklb
        └── <hostname>_vm.cklb
```

## STIG & Compliance

### CKLB Generation
The `ncs-reporter` tool includes a specialized `cklb` command that generates STIG Checklist files:
- **Input:** Raw JSON/YAML audit results collected by the `stig_xml` callback.
- **Processing:** Results are mapped against STIG XCCDF skeletons.
- **Output:** Native `.cklb` files compatible with STIG Viewer, containing status (Pass/Fail/Open), finding details, and fix actions.

### STIG Playbooks
- `ubuntu_stig_audit.yml` / `ubuntu_stig_remediate.yml`: Audit and remediate Linux systems against STIG requirements.
- `vmware_stig_audit.yml` / `vmware_stig_remediate.yml`: Audit and remediate VMware infrastructure.
- `windows_stig_audit.yml`: Audit Windows systems against STIG requirements.

## Key Commands


Commands are managed via `just`:

- `just site`: Executes the audit pipeline and generates the dashboard.
- `just test`: Runs Python unit and E2E tests for the reporting engine.
- `just check`: Runs static analysis (Ruff, MyPy).
- `just audit-linux-host <hostname>`: Audits a specific Linux server.
- `just stig-audit-vm <vcenter> <vm_name>`: Performs a STIG audit on a VM.

## Usage

1.  **Environment:** Requires Nix and Direnv.
2.  **Dependencies:** `ansible-galaxy collection install -r requirements.yml`.
3.  **Inventory:** Define targets in `inventory/production/hosts.yaml`.
4.  **Execution:** `just site`.

Refer to `docs/REPORTING_ARCHITECTURE.md` and `GEMINI.md` for technical specifications.
