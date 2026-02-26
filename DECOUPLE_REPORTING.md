# Decoupling Reporting from Ansible: Migration Status

This document tracks the migration of the NCS reporting pipeline from Ansible-native rendering to a standalone Python CLI (`ncs_reporter`).

## Summary

Reporting stages 2–6 (aggregation, normalization, view-model building, rendering, presentation) have been migrated to `tools/ncs_reporter/`. Ansible collections are now solely responsible for auditing systems and emitting raw YAML data. The CLI is invoked by `playbooks/common/generate_fleet_reports.yaml`.

## Migration Phases

### Phase 1: Package Structure — Done

- `tools/ncs_reporter/` created as a standard Python package with `pyproject.toml`
- Dependencies: `Jinja2`, `PyYAML`, `Click`

### Phase 2: Migrate Core Logic — Done

- View models moved to `tools/ncs_reporter/src/ncs_reporter/view_models/` (vmware, linux, windows, site, common)
- Templates and shared CSS moved to `tools/ncs_reporter/src/ncs_reporter/templates/`
- Aggregation logic in `tools/ncs_reporter/src/ncs_reporter/aggregation.py`
- Unit tests in `tools/ncs_reporter/tests/`

### Phase 3: CLI Engine — Done

- `ncs_reporter.cli` provides commands: `all`, `collect`, `linux`, `vmware`, `windows`, `node`, `site`
- Initializes native Jinja2 environment, loads YAML data, applies view models, renders HTML

### Phase 4: Integration — Done

- `playbooks/common/generate_fleet_reports.yaml` invokes the CLI after Ansible audit playbooks complete
- `master_audit.yaml` imports `generate_fleet_reports.yaml` as the final stage

### Phase 5: Cleanup — Done

- Deleted `core/roles/reporting/` (shared rendering role)
- Deleted `core/plugins/filter/reporting.py` and platform summary filter plugins
- Deleted `core/plugins/module_utils/report_view_models.py`
- Updated `docs/REPORTING_ARCHITECTURE.md` to reflect new architecture
- Migrated per-host STIG HTML rendering from Ansible (`core/roles/stig/tasks/finalize.yaml`) to `ncs_reporter` CLI with `stig_host_report.html.j2` and `stig_fleet_report.html.j2` templates

## Architecture Reference

See `docs/REPORTING_ARCHITECTURE.md` for the full pipeline description.

## Benefits Realized

- **Performance:** Native Python Jinja rendering is orders of magnitude faster than Ansible `template` loops.
- **Maintainability:** True separation of concerns. Ansible playbooks are purely for infrastructure automation; Python handles data shaping and presentation.
- **Testability:** The entire reporting pipeline can be tested locally using mock YAML data without invoking `ansible-playbook` or managing inventory contexts.
- **Simplicity:** Removes the complex boilerplate required to pass data between Ansible tasks, custom Python filters, and module utilities.
