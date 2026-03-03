# NCS (Network Compliance & Status)

Ansible-based system for auditing and reporting on Linux (Ubuntu/Photon), VMware (ESXi/vCenter), and Windows environments.

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
2.  **Phase 2: VMware Infrastructure** (`vmware_audit.yml`) - Runs the full VMware collector (vCenter + ESXi + VM data) for reporting.
3.  **Phase 3: Linux/Windows Fleet** (`ubuntu_audit.yml`, `windows_audit.yml`) - Performs system-level audits.
4.  **Phase 4: Unified Reporting** (`generate_reports.yml`) - Invokes the `ncs-reporter` CLI to process the collected YAML data into HTML dashboards.

Additional orchestration variants:
- `playbooks/site_collect_only.yml`: Setup + collection only (no report rendering).
- `playbooks/site_reports_only.yml`: Reporting only from existing artifacts.
- `playbooks/site_vmware_only.yml`: VMware-only collection + reporting.

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
- **Input:** Raw JSON/YAML audit results collected via `ncs_collect` and persisted by `ncs_collector`.
- **Processing:** Results are mapped against STIG XCCDF skeletons.
- **Output:** Native `.cklb` files compatible with STIG Viewer, containing status (Pass/Fail/Open), finding details, and fix actions.

### STIG Playbooks
- `ubuntu_stig_audit.yml` / `ubuntu_stig_remediate.yml`: Audit and remediate Ubuntu systems against STIG requirements.
- `photon_stig_audit.yml` / `photon_stig_remediate.yml`: Audit and remediate VMware Photon OS 5.0 systems against STIG requirements.
- `vmware_esxi_stig_audit.yml` / `vmware_esxi_stig_remediate.yml`: Audit and remediate ESXi STIG controls.
- `vmware_vm_stig_audit.yml` / `vmware_vm_stig_remediate.yml`: Audit and remediate VM STIG controls.
- `vmware_vcsa_stig_audit.yml` / `vmware_vcsa_stig_remediate.yml`: Audit and remediate vCenter Server Appliance (VCSA) STIG controls.
- `vmware_stig_audit.yml` / `vmware_stig_remediate.yml`: Compatibility wrappers that run both ESXi and VM STIG flows.
- `vmware_vcenter_audit.yml` / `vmware_esxi_audit.yml` / `vmware_vm_audit.yml`: Split non-STIG VMware audits for control-plane, host, and workload scopes.
- `windows_stig_audit.yml`: Audit Windows systems against STIG requirements.
- `ubuntu_discover.yml` / `ubuntu_remediate_apply.yml` / `ubuntu_stig_remediate_apply.yml` / `ubuntu_stig_verify.yml`: Split Ubuntu phase playbooks for discover/apply/verify workflows.
- `windows_update.yml` / `windows_post_patch_audit.yml`: Split Windows patch apply and verification phases.

## Key Commands


Commands are managed via `just`:

- `just site`: Executes the audit pipeline and generates the dashboard.
- `just site-collect`: Executes collection only.
- `just site-reports`: Executes reporting only.
- `just site-vmware`: Executes VMware-only pipeline.
- `just test`: Runs Python unit and E2E tests for the reporting engine.
- `just check`: Runs static analysis (Ruff, MyPy).
- `just audit-linux-host <hostname>`: Audits a specific Linux server.
- `just stig-audit-vm <vcenter> <vm_name>`: Performs a STIG audit on a VM.
- `just stig-audit-esxi-site <site>`: Audits ESXi STIG controls for all ESXi hosts associated to the site group.
- `just stig-audit-esxi-site-inv <site> <inventory>`: Same as above, with an explicit inventory path.
- `just stig-harden-esxi-site <site>`: Applies ESXi STIG remediation for all ESXi hosts associated to the site group (mutating).
- `just stig-harden-esxi-site-inv <site> <inventory>`: Same remediation workflow with an explicit inventory path.
- `just stig-audit-vcsa [target]`: Audits VCSA STIG controls (default target `vcenters`).
- `just stig-remediate-vcsa [target]`: Applies VCSA STIG remediation (mutating).
- `just stig-audit-vcsa-site <site>` / `just stig-remediate-vcsa-site <site>`: Site-scoped VCSA STIG workflows via site group targeting.
- `just stig-audit-vcsa-inv <target> <inventory>` / `just stig-remediate-vcsa-inv <target> <inventory>`: VCSA STIG workflows with explicit inventory path.
- `just stig-audit-vcsa-site-inv <site> <inventory>` / `just stig-remediate-vcsa-site-inv <site> <inventory>`: Site-scoped VCSA STIG workflows with explicit inventory path.
- `just stig-audit-photon [target]`: Audits Photon STIG controls (default target `photon_servers`).
- `just stig-remediate-photon [target]`: Applies Photon STIG remediation (mutating).
- `just stig-audit-photon-inv <target> <inventory>` / `just stig-remediate-photon-inv <target> <inventory>`: Photon STIG workflows with explicit inventory path.
- `just simulate-production-stig-run [out_root]`: Generates deterministic mock artifacts for core + VCSA-component STIG targets, runs full reporting, and enforces publish gates.
- `just simulate-vmware-playbook [out_root]`: Runs the real `vmware_audit.yml` playbook in `simulation_mode` against fixture-backed vCenter data, then renders and verifies reports.
- `just simulate-production-ansible-run [out_root]`: Replays all generated mock raw artifacts through Ansible (`set_stats` + `internal.core.ncs_collector`) for every target type, then enforces report/coverage gates.

## Full-Production STIG Simulation

Run the complete deterministic simulation pipeline:

```bash
just simulate-production-stig-run
```

Optional output root:

```bash
just simulate-production-stig-run tests/reports/mock_production_run
```

The pipeline performs:
1. Mock raw artifact generation from `inventory/production/hosts.yaml`.
2. Full `ncs-reporter all` rendering (fleet + host + STIG + CKLB).
3. Artifact gate validation (`verify-report-artifacts`).
4. STIG emission gate validation for:
   `vcsa,esxi,vm,windows,ubuntu,photon,vami,eam,lookup_svc,perfcharts,vcsa_photon_os,postgresql,rhttpproxy,sts,ui`.

Expected output tree (abridged):

```text
<out_root>/
├── site_health_report.html
├── stig_fleet_report.html
├── cklb/
├── platform/
│   ├── inventory_groups.json
│   ├── vmware/
│   │   ├── vcenter/vcsa/<host>/raw_vcenter.yaml
│   │   ├── vcenter/vcsa/<host>/raw_stig_vcsa.yaml
│   │   ├── vcenter/vcsa/<host>/raw_stig_<vcsa_component>.yaml
│   │   ├── esxi/<host>/raw_stig_esxi.yaml
│   │   └── vm/<host>/raw_stig_vm.yaml
│   ├── windows/<host>/raw_audit.yaml
│   ├── windows/<host>/raw_stig_windows.yaml
│   ├── linux/ubuntu/<host>/raw_discovery.yaml
│   ├── linux/ubuntu/<host>/raw_stig_ubuntu.yaml
│   └── linux/photon/<host>/raw_stig_photon.yaml
```

Interpreting verification failures:
- `missing target '<name>' coverage`: target type was not emitted or host count is below threshold.
- `target_type mismatch`: filename and payload `target_type` disagree; regenerate mock artifacts.
- `missing CKLB`: STIG exists but checklist generation did not produce `<host>_<target>.cklb`.
- `missing STIG host html`: STIG raw was present but report rendering did not produce `<host>_stig_<target>.html`.
- `engine expected 'ncs_collector_callback'`: payload metadata does not match production callback envelope.

## Playbook-Level Simulation Mode

For playbook execution without production dependencies:

1. Simulation inventory: `inventory/simulation/hosts.yaml`
2. Simulation vars: `inventory/simulation/group_vars/all.yml` (`simulation_mode: true`)
3. Role path: `internal.vmware.vcenter` loads fixture data from:
   `simulation_vcenter_fixture_root/<host>/raw_vcenter.yaml`

Run:

```bash
just simulate-vmware-playbook
```

This executes the real playbook path and callback emission logic while substituting API calls with fixture-backed task data.

## Production Simulation With Ansible Execution

To validate a production-like simulation and include a real Ansible execution step:

```bash
just simulate-production-ansible-run
```

Optional output root:

```bash
just simulate-production-ansible-run tests/reports/mock_production_ansible_run
```

What this adds beyond `simulate-production-stig-run`:
1. Generates fixtures into `<out_root>/_fixtures/`.
2. Replays every `raw_*.yaml` fixture through Ansible callback emission into `<out_root>/platform/...` using a generated temporary local inventory derived from fixture hostnames.
3. Validates the same strict report and STIG coverage gates from Ansible-emitted artifacts.

Compatibility note:
- `scripts/replay_mock_artifacts_via_ansible.py` accepts `--inventory` for compatibility, but host resolution is currently fixture-derived and does not consume inventory host vars.

## Usage

1.  **Environment:** Requires Nix and Direnv.
2.  **Python deps (preferred):** `uv sync --dev` (installs dev tools including `pytest`).
3.  **Ansible collections:** `ansible-galaxy collection install -r requirements.yml`.
4.  **Inventory:** Define targets in `inventory/production/hosts.yaml`.
5.  **Execution:** `just site`.

Refer to `docs/REPORTING_ARCHITECTURE.md` and `GEMINI.md` for technical specifications.
