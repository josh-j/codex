# Architecture Refactor TODO

## Reporting Architecture (High Priority)

- [ ] Consolidate reporting data shaping into a single layer.
  - Move report "view-model" shaping out of Ansible task vars and Jinja templates.
  - Ensure VMware normalization is not split between Python adapters and role inline vars.

- [ ] Introduce a dedicated reporting view-model builder module.
  - Add `/Users/joshj/dev/codex/internal/core/plugins/module_utils/report_view_models.py`.
  - Implement builders for:
    - `build_vmware_fleet_view(aggregated_hosts)`
    - `build_linux_fleet_view(aggregated_hosts)`
    - `build_site_dashboard_view(all_hosts, inventory_groups)`

- [ ] Make templates presentation-only (or close to it).
  - Remove cross-host aggregation loops and metric calculations from Jinja where possible.
  - Pass precomputed objects like `fleet_summary`, `host_rows`, `alert_totals`, and gauge/chart data.

- [ ] Remove inline VMware compatibility shims from summary role task vars.
  - Eliminate `_bundle`, `_discovery`, `_audit`, `vmware_ctx`, `vmware_alerts`, and `vcenter_health` assembly in:
    - `/Users/joshj/dev/codex/internal/vmware/roles/summary/tasks/report.yaml`
  - Replace with a single template input object from the view-model builder.

- [ ] Centralize report naming conventions and "skip keys" in one module.
  - Define canonical skip keys (`Summary`, `Split`, `platform`, `history`, `*_fleet_state`, etc.) in one shared location.
  - Remove duplicated skip-key lists from:
    - core reporting tasks
    - platform summary roles
    - templates
    - aggregation helpers

- [ ] Unify the global site report pipeline with the extracted reporting architecture.
  - Move logic from `/Users/joshj/dev/codex/playbooks/common/generate_site_health_report.yaml` into:
    - `internal.core.reporting` tasks, or
    - a new `internal.core.site_reporting` role
  - Keep the playbook as an orchestration entrypoint only.

- [ ] Separate reporting responsibilities by layer.
  - Collector/Aggregator layer (Python): read raw YAML reports, normalize platform payloads, aggregate canonical state.
  - View-model layer (Python): build template-ready structures.
  - Renderer/Orchestration layer (Ansible): directories, rendering, symlinks, retention.
  - Presentation layer (Jinja/CSS): rendering only, minimal conditionals.

- [ ] Reduce brittle repo-layout path derivation in reporting tasks.
  - Replace `playbook_dir.split('/playbooks')[0]` style path logic with a stable configured path or role variable.
  - Standardize script path resolution used by platform summary roles and shared reporting tasks.

## CI / Validation Alignment (High Priority)

- [ ] Fix CI path drift in Molecule job.
  - Update `/.gitlab-ci.yml` to point to the current role path(s), or remove the obsolete job.
  - Confirm the current repo layout vs `collections/ansible_collections/internal/stig/roles/common`.

- [ ] Expand syntax/validation coverage for nested playbooks.
  - Ensure CI checks include `playbooks/common/*.yaml` and other nested playbooks, not only `playbooks/*.yaml`.

- [ ] Enforce a single canonical runtime path for Python helpers.
  - Decide between:
    - collection-loader-first runtime, or
    - repo-local wrapper/runtime
  - Update CI to validate the chosen mode consistently.

## Contract / Schema Hardening (High Priority)

- [ ] Define a versioned report schema/contract for aggregated and template-facing data.
  - Formalize canonical report shape across Linux, VMware, and site-level reporting.
  - Include explicit schema/version metadata where appropriate.

- [ ] Centralize normalization rules for platform payloads.
  - Avoid ad hoc shape adaptation in playbooks/roles/templates.
  - Keep payload adaptation in shared Python normalization/view-model code.

- [ ] Add view-model contract tests.
  - Add unit tests for:
    - VMware fleet template input shape
    - Linux fleet template input shape
    - Site dashboard template input shape
  - Treat template-facing structures as stable contracts.

## Reporting Role Refactor Steps (Practical / Incremental)

- [ ] Step 1: Add `report_view_models.py` with VMware fleet builder.
  - Start with VMware because it currently has the most inline shaping logic.

- [ ] Step 2: Refactor VMware summary role to use `vmware_fleet_view`.
  - Update `/Users/joshj/dev/codex/internal/vmware/roles/summary/tasks/report.yaml`.
  - Update `/Users/joshj/dev/codex/internal/vmware/roles/summary/templates/vmware_health_report.html.j2`.
  - Aim to remove host filtering, alert aggregation, and utilization rollups from the template.

- [ ] Step 3: Refactor Linux summary role to use `linux_fleet_view`.
  - Update `/Users/joshj/dev/codex/internal/linux/roles/ubuntu_summary/tasks/report.yaml`.
  - Update Linux fleet and host templates to consume precomputed display data.

- [ ] Step 4: Refactor global site report to use `site_dashboard_view`.
  - Replace inline `set_fact` aggregations and template-side cross-platform loops with prebuilt view data.

- [ ] Step 5: Move retention and "latest symlink" behavior into reusable reporting tasks.
  - Keep platform/site reporting pipelines consistent.

## Cleanup / Consistency

- [ ] Standardize naming for aggregated vars.
  - Reduce mixed names like `all_hosts` vs `vmw_all_hosts` unless there is a clear boundary reason.

- [ ] Document the reporting pipeline architecture.
  - Add a short architecture doc describing:
    - raw report emitters
    - aggregation
    - normalization
    - view-model builders
    - template rendering
    - retention/symlink maintenance

- [ ] Audit templates for duplicated logic patterns.
  - Identify repeated alert counting, host filtering, and status derivation patterns.
  - Replace with shared computed fields or shared helpers.
