# Reporting Pipeline Architecture

NCS uses a **totally decoupled** reporting pipeline. Ansible is restricted strictly to data collection across the fleet, while all data processing, normalization, and report rendering are handled by the standalone `ncs_reporter` Python CLI.

## The Two-Stage Architecture

### Stage 1: Data Collection (Ansible)
Ansible roles are responsible for executing modules and scripts on target hosts and emitting the **raw, un-normalized results** as telemetry.

- **Collector Roles:** `internal.linux.ubuntu`, `internal.vmware.vcenter`, `internal.windows.windows`.
- **Handoff:** Results are emitted via `ansible.builtin.set_stats` under the `ncs_collect` key. The `internal.core.ncs_collector` callback plugin then automatically saves these to `raw_*.yaml` files on disk at the end of the run.
- **Rule:** Ansible MUST NOT attempt to shape data for reporting. It only captures and emits module return values.


### Stage 2: Processing & Rendering (ncs_reporter)
The `ncs_reporter` tool ingests the raw YAML files and performs the heavy lifting.

1.  **Normalization:** The `ncs_reporter.normalization` layer converts platform-specific raw data into canonical view models.
2.  **Alert Generation:** Logic for determining health status and generating alerts (e.g., "Disk space > 90%") lives in Python, not Jinja.
3.  **View-Model Construction:** Data is shaped into template-ready contracts.
4.  **Rendering:** Jinja2 templates are rendered into HTML dashboards.

## Canonical Source Layout

- **Ansible Collectors:** `collections/ansible_collections/internal/...`
- **Processing Logic:** `tools/ncs_reporter/src/ncs_reporter/normalization/`
- **View Builders:** `tools/ncs_reporter/src/ncs_reporter/view_models/`
- **Templates:** `tools/ncs_reporter/src/ncs_reporter/templates/`

## Key Design Rules

### 1. Total Decoupling
Ansible purely collects; Python purely processes. This eliminates complex Jinja2 filters and `module_utils` inside Ansible collections, making the system significantly faster and easier to test.

### 2. The Context Pattern (Internal)
While most processing moved to Python, some roles still use a `ncs_ctx` pattern if they need to pass data between tasks (e.g., remediation needing discovery facts). Use the appropriate collector role to refresh state if needed.


### 3. Automated Path Management
Never hardcode file paths. The `ncs_collector` callback plugin and the `ncs-reporter` tool automatically manage the directory structure based on the platform and hostname.


### 4. Logic in Python, not Jinja
All status derivation, alert counting, and data shaping MUST happen in Python normalizers. Templates should be "dumb" and only render the provided structure.

### 5. Contract Testing
Normalization logic and view-model builders are tested using `pytest` in `tools/ncs_reporter/tests/`. This allows verifying the entire reporting pipeline using mock raw data without running Ansible.

## Standard Workflow

1.  **Execute Audit:** `ansible-playbook playbooks/site.yml`
2.  **Generate Reports:** Ansible automatically invokes `ncs-reporter all` at the end of the playbook.

3.  **View Results:** Access the HTML dashboards in the configured report directory (e.g., `/srv/samba/reports/index.html`).

## Benefits of the Decoupled Architecture

- **Performance:** Native Python Jinja rendering is orders of magnitude faster than Ansible `template` loops.
- **Maintainability:** True separation of concerns. Ansible playbooks are purely for infrastructure automation; Python handles data shaping and presentation.
- **Testability:** The entire reporting pipeline can be tested locally using mock YAML data without invoking `ansible-playbook` or managing inventory contexts.
- **Simplicity:** Removes the complex boilerplate required to pass data between Ansible tasks, custom Python filters, and module utilities.
