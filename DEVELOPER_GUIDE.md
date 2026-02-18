# CODEX Developer Guide

This guide explains the architectural patterns, data structures, and development workflows for the CODEX Ansible automation suite.

## 🏗️ Architecture Overview

CODEX follows a **three-play lifecycle** to ensure standard state management and deterministic results.

1.  **Initialize (Localhost)**: Generates a unique `run_id`, sets global metadata (date, timestamp), and determines which tasks to run based on the schedule.
2.  **Execute (Target Hosts)**: Performs discovery, compliance checks, and local data exports on the infrastructure.
3.  **Aggregate & Render (Localhost)**: Collects results from all hosts, validates the data, and renders HTML/Markdown dashboards.

---

## 📊 The `ops` Data Schema

All roles must populate a standard `ops` dictionary on each host. This object is used by the aggregator to build the final report.

### Required Structure
```yaml
ops:
  check:
    id: "2026-02-18_120000"  # Global Run ID
    date: "2026-02-18"
    timestamp: "..."
    site: "vcenter-01"      # inventory_hostname
  alerts: []                # List of alert objects
  reports: []               # List of generated report metadata
  overall:
    status: "OK"            # OK, Warning, or Critical
    issues: 0
```

### Alert Object Schema
```yaml
- severity: "CRITICAL"      # INFO, WARNING, CRITICAL
  category: "capacity"      # capacity, connectivity, performance, security
  message: "Disk usage > 95%"
  details: {}               # Arbitrary key-value pairs for the report
```

---

## 🛠️ Role Design Patterns

To maintain a "Single Responsibility Principle" (SRP) and ensure robustness, follow these patterns:

### 1. Safe Initialization (`tasks/init.yaml`)
Every role should have an `init.yaml` that defines default values for its namespace. This prevents the aggregator from crashing if discovery is skipped or fails.

### 2. Decoupled Discovery
Separate heavy data gathering from the audit logic.
*   **Discovery**: `vmware.vmware_rest.vcenter_datacenter_info`, `command: sshd -T`, etc.
*   **Audit**: Logic that compares discovered facts against thresholds or STIG policies.

### 3. Check Mode Support
Ensure your role is "dry-run" friendly:
*   Add `check_mode: false` to read-only discovery tasks so they run even during `--check`.
*   Provide defaults in `normalize.yaml` or `init.yaml` for variables that might be missing if a task is skipped.

---

## 🚀 Adding a New Check

1.  **Discovery**: Add a task to the role's `discover.yaml` to gather the raw data. Use `check_mode: false`.
2.  **Normalization**: Update `normalize.yaml` to parse the raw output into a clean dictionary under your namespace (e.g., `ubuntu.security.my_new_metric`).
3.  **Audit**: Create a task in `check.yaml` that evaluates the normalized data and uses the `internal.core.reporting` role's `alert` task to generate an alert if needed.
4.  **Export**: (Optional) Add a row to the CSV export in `export.yaml`.

---

## 🏗️ Starting a New Platform Role

To quickly add support for a new infrastructure platform (e.g., `netapp`), use the `starter_role` template:

```bash
# 1. Choose your collection (e.g., internal.storage)
# 2. Copy the starter_role to your collection
cp -r collections/ansible_collections/internal/templates/roles/starter_role \
      collections/ansible_collections/internal/storage/roles/netapp

# 3. Search and replace 'starter' with 'netapp' in the new role
find collections/ansible_collections/internal/storage/roles/netapp -type f \
     -exec sed -i '' 's/starter/netapp/g' {} +

# 4. Implement your logic in discover.yaml and check.yaml
```

---

## 🏷️ Naming Conventions

Consistency is key to maintainability. Follow these prefix rules:

| Scope | Prefix | Example |
|-------|--------|---------|
| **Role Variables** | `role_name_` | `ubuntu_skip_discovery` |
| **Internal/Helper Vars** | `_role_name_` | `_ubuntu_temp_file` |
| **Facts (Global)** | `ops` | `ops.ubuntu.facts` |
| **Playbook Variables** | `play_` | `play_site_name` |

---

## 🔌 Plug-and-Play Role Interface

A role is "CODEX-compliant" if it adheres to the following interface:

### 1. The `ops` Contract
The role **MUST** contribute to the `ops` dictionary. It **MUST NOT** overwrite other roles' data in `ops`.
*   **Initialization**: Always call `init.yaml` first.
*   **Namespace**: Always store platform-specific facts under `ops.<platform_name>.facts`.

### 2. Standard Task Entry Points
Every role should expose these files in `tasks/`:
- `main.yaml`: The master orchestrator.
- `init.yaml`: Safe state initialization.
- `discover.yaml`: Read-only data collection.
- `check.yaml`: Logic and audit evaluation.
- `export.yaml`: Data normalization for the reporting engine.

### 3. Unified Logging
Do not use `ansible.builtin.debug` for progress messages. Use the centralized logging tasks:
```yaml
- name: Log progress
  ansible.builtin.include_role:
    name: internal.core.common
    tasks_from: logging/info.yaml
  vars:
    msg: "My descriptive message"
```

### 4. Alert Generation
Do not manually append to `ops.alerts`. Use the standardized alert emitter:
```yaml
- name: "Raise alert if disk usage is high"
  ansible.builtin.include_role:
    name: internal.core.reporting
    tasks_from: alert.yaml
  vars:
    ops_alert_severity: "WARNING"
    ops_alert_category: "capacity"
    ops_alert_message: "Disk usage is at {{ usage }}%"
    ops_alert_details:
      mount: "/data"
  when: usage > 90
```

---

## 🧪 Testing with Molecule

We use Molecule with the `delegated` driver for local verification of the aggregation engine.

```bash
# Navigate to the role
cd collections/ansible_collections/internal/stig/roles/common

# Run the test suite
molecule test
```

The CI pipeline (GitLab CI) automatically runs these tests on every push.
