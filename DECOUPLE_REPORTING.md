# Decoupling Reporting from Ansible: A Migration Plan

This document outlines the strategy for moving the Codex reporting pipeline from an Ansible-native (Jinja template tasks + custom Python filters) architecture to a fully decoupled, standalone Python CLI approach.

## 1. Executive Summary

**The Problem:** Ansible is an excellent execution and orchestration engine, but it is not built to be a high-performance reporting engine. The current architecture forces Ansible to loop over hundreds of hosts, passing variables through complex custom Python filters just to render Jinja templates. This is slow, difficult to test natively, and tightly couples the presentation layer to the orchestration layer.

**The Solution:** Extract all reporting logic (View Models, Jinja Templates, CSS) into a standalone Python CLI tool. Ansible collections will solely be responsible for auditing systems and emitting raw JSON/YAML data. The new tool will parse this data, apply the View Models, and render the final HTML reports in milliseconds.

## 2. Current State vs. Future State

### Current State (Coupled)
1. **Emit:** Platform roles (`internal.linux`, `internal.vmware`, `internal.windows`) write host-level YAML reports.
2. **Aggregate:** `aggregate_yaml_reports.py` collects host-level YAML into fleet state files.
3. **Normalize & Render (Ansible):** Ansible runs `summary` roles. It calls custom Jinja filters (e.g., `vmware_fleet_view`) which internally call Python View Models in `internal.core`.
4. **Output:** Ansible `template` module renders HTML files in a loop.

### Future State (Decoupled)
1. **Emit:** Platform roles write host-level YAML reports. (Unchanged)
2. **Aggregate:** `aggregate_yaml_reports.py` collects host-level YAML into fleet state files. (Unchanged)
3. **Process & Render (Python CLI):** A new standalone CLI (e.g., `codex-reporter`) reads the fleet state files, applies the View Models directly in Python, uses native Jinja2 to render the templates, and writes the HTML output.

## 3. Step-by-Step Implementation Plan

### Phase 1: Establish the Standalone Tool
1. **Create Package Structure:** Create a new directory for the reporting tool (e.g., `tools/codex_reporter/` or as a standard Python package at the project root).
2. **Setup Dependencies:** Ensure `Jinja2`, `PyYAML`, and any required CLI libraries (like `argparse` or `click`) are in the requirements file or `pyproject.toml`.

### Phase 2: Migrate Core Logic
1. **Move View Models:** Relocate the contents of `internal/core/plugins/module_utils/report_view_models*.py` and `reporting_primitives.py` into the new `codex_reporter` package. 
2. **Move Templates:** Relocate all `.j2` reporting templates and associated CSS files from the various collections (e.g., `internal/vmware/roles/summary/templates/`, `playbooks/templates/site_health_report.html.j2`) into a `templates/` directory within the new package.
3. **Migrate Tests:** Move the corresponding unit tests from `tests/unit/` (e.g., `test_report_view_model_vmware.py`, `test_reporting_view_contract.py`) to the new tool's test suite and update import paths.

### Phase 3: Build the CLI Engine
1. **Develop the CLI Entrypoint:** Write a main script that:
   - Accepts input paths for the aggregated YAML files.
   - Accepts an output directory for the HTML reports.
   - Initializes a native Jinja2 environment pointing to the new `templates/` directory.
   - Loads the YAML data, passes it through the migrated View Model functions to get the context dictionary.
   - Renders the templates and writes the final HTML files to disk.

### Phase 4: Integration and Orchestration Updates
1. **Update Make/CI:** Add a `make report` target or update CI/CD pipelines to run the new Python CLI after the Ansible playbooks complete.
2. **Refactor Playbooks:** Remove the reporting playbook calls (e.g., `playbooks/common/generate_site_health_report.yaml` or parts of `master_audit.yaml` that trigger rendering). The playbooks should stop after aggregation.

### Phase 5: Cleanup and Deprecation
1. **Remove Ansible Reporting Roles:** Delete the `internal.core.roles.reporting` role and all `summary` roles in the platform collections.
2. **Remove Custom Filters:** Delete the custom Jinja filter plugins (e.g., `internal/vmware/plugins/filter/reporting.py`, `internal/core/plugins/filter/reporting.py`) that were used solely to expose View Models to Ansible.
3. **Update Documentation:** Revise `docs/REPORTING_ARCHITECTURE.md` to reflect the new decoupled workflow.

## 4. Expected Benefits
- **Performance:** Native Python Jinja rendering is orders of magnitude faster than Ansible `template` loops.
- **Maintainability:** True separation of concerns. Ansible playbooks are purely for infrastructure automation; Python handles data shaping and presentation.
- **Testability:** The entire reporting pipeline can be tested locally using mock YAML data without invoking `ansible-playbook` or managing inventory contexts.
- **Simplicity:** Removes the complex boilerplate required to pass data between Ansible tasks, custom Python filters, and module utilities.
