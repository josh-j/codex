# Architecture Refactor TODO

## Reporting Architecture (High Priority)

- [x] Consolidate reporting data shaping into a single layer.
  - Reporting view-model shaping now lives in shared Python builders instead of Ansible task vars/Jinja loops.
  - VMware role inline compatibility shims were removed from summary rendering.
  - Remaining note: VMware legacy aggregation adapter still exists as compatibility glue (now hardened + tested).

- [x] Introduce a dedicated reporting view-model builder module.
  - Added `/Users/joshj/dev/codex/collections/ansible_collections/internal/core/plugins/module_utils/report_view_models.py`.
  - Implement builders for:
    - `build_vmware_fleet_view(aggregated_hosts)`
    - `build_vmware_node_view(hostname, bundle)`
    - `build_linux_fleet_view(aggregated_hosts)`
    - `build_linux_node_view(hostname, bundle)`
    - `build_site_dashboard_view(all_hosts, inventory_groups)`
    - `build_stig_host_view(hostname, audit_type, stig_payload)`
    - `build_stig_fleet_view(aggregated_hosts)`

- [x] Make templates presentation-only (or close to it).
  - Linux/VMware/site/STIG templates now consume precomputed view-model fields for fleet rows, alert totals, and STIG findings.
  - Remaining template logic is mostly display formatting and UI conditionals.

- [x] Remove inline VMware compatibility shims from summary role task vars.
  - Replaced inline `_bundle`/`_audit`/`vmware_ctx` shaping with `vmware_node_view` + `vmware_fleet_view`.
  - Updated:
    - `/Users/joshj/dev/codex/collections/ansible_collections/internal/vmware/roles/summary/tasks/report.yaml`

- [x] Centralize report naming conventions and "skip keys" in one module.
  - Define canonical skip keys (`Summary`, `Split`, `platform`, `history`, `*_fleet_state`, etc.) in one shared location.
  - Canonical provider/filter implemented and consumed by:
    - core reporting tasks
    - Linux/VMware summary roles
    - legacy call sites that were still using duplicated lists (before removal)

- [x] Unify the global site report pipeline with the extracted reporting architecture.
  - Site dashboard generation was moved into reusable core reporting tasks (`site_dashboard.yaml`).
  - `playbooks/common/generate_site_health_report.yaml` now acts as orchestration entrypoint.

- [x] Separate reporting responsibilities by layer.
  - Collector/Aggregator layer (Python): read raw YAML reports, normalize platform payloads, aggregate canonical state.
  - View-model layer (Python): build template-ready structures.
  - Renderer/Orchestration layer (Ansible): directories, rendering, symlinks, retention.
  - Presentation layer (Jinja/CSS): rendering only, minimal conditionals.

- [x] Reduce brittle repo-layout path derivation in reporting tasks.
  - Replaced `split('/playbooks')` path derivation in VMware summary reporting.
  - Linux/VMware summary roles now use safer `playbook_dir | dirname` script path resolution.

## STIG Reporting Architecture (High Priority)

- [x] Move STIG host/fleet reporting onto the shared view-model architecture.
  - Added `stig_host_view` and `stig_fleet_view` builders + core filters.
  - Core STIG HTML template now renders from `stig_host_view`.
  - Linux/site STIG summary sections now render from `stig_fleet_view`.

- [x] Remove STIG reporting compatibility shims after migration.
  - Removed temporary compatibility fields:
    - `linux_fleet_view.stig_rows`
    - `site_dashboard_view.security.stig_entries`
  - Templates now use canonical `security.stig_fleet.rows` and `status.raw`.

- [ ] Add broader STIG payload-variant coverage (beyond current Linux/ESXi cases).
  - Expand tests for malformed/partial STIG rows and additional VMware STIG variants if encountered.

## CI / Validation Alignment (High Priority)

- [x] Fix CI path drift in Molecule job.
  - Obsolete Molecule path job was removed from `/.gitlab-ci.yml`.
  - Replaced with unit-test coverage for refactored reporting contracts.
  - Follow-up (optional): reintroduce integration-level coverage on the new collection layout.

- [x] Expand syntax/validation coverage for nested playbooks.
  - CI now includes nested playbooks such as `playbooks/common/*.yaml`.

- [x] Enforce a single canonical runtime path for Python helpers.
  - Canonical source layout is now under `collections/ansible_collections/internal/...`.
  - `./internal` compatibility symlinks were removed.
  - Helper/test fallback paths were updated to the collection layout.

## Contract / Schema Hardening (High Priority)

- [ ] Define a versioned report schema/contract for aggregated and template-facing data.
  - Formalize canonical report shape across Linux, VMware, and site-level reporting.
  - Include explicit schema/version metadata where appropriate.

- [x] Centralize normalization rules for platform payloads.
  - Payload adaptation and template-facing normalization now live in shared Python code (view-model builders + VMware adapter).
  - Remaining compatibility normalization is isolated in VMware aggregation adapter (with tests).

- [x] Add view-model contract tests.
  - Added unit tests for VMware, Linux, Site, and STIG template-facing view-model shapes.
  - Added VMware adapter compatibility tests and discovery defaults contract checks.

- [ ] Add deeper malformed/partial payload tests.
  - Expand edge-case coverage for unexpected nested types and partially populated exports.

## Reporting Role Refactor Steps (Practical / Incremental)

- [x] Step 1: Add `report_view_models.py` with VMware fleet builder.

- [x] Step 2: Refactor VMware summary role to use `vmware_fleet_view`.
  - VMware fleet and node templates now use `vmware_fleet_view` / `vmware_node_view`.

- [x] Step 3: Refactor Linux summary role to use `linux_fleet_view`.
  - Linux fleet and host templates now render from `linux_fleet_view` / `linux_node_view`.

- [x] Step 4: Refactor global site report to use `site_dashboard_view`.
  - Site template now renders platform/security/compute sections from `site_dashboard_view`.

- [x] Step 5: Move retention and "latest symlink" behavior into reusable reporting tasks.
  - Platform reporting pipelines now use shared host-loop directory/render/symlink tasks.
  - Legacy aggregate pipeline was removed.

## Cleanup / Consistency

- [x] Standardize naming for aggregated vars.
  - Reporting pipelines now use `aggregated_hosts` consistently in Linux/VMware summary roles and site dashboard task flow.

- [x] Document the reporting pipeline architecture.
  - Add a short architecture doc describing:
    - raw report emitters
    - aggregation
    - normalization
    - view-model builders
    - template rendering
    - retention/symlink maintenance
  - Added `/Users/joshj/dev/codex/docs/REPORTING_ARCHITECTURE.md`.

- [x] Audit templates for duplicated logic patterns.
  - Major duplicated alert counting/host filtering/status derivation logic was removed from Linux/VMware/site/STIG summary templates.
  - Remaining duplication is mostly presentational markup rather than data aggregation logic.

## Collection Layout / Migration Cleanup

- [x] Move canonical source to collection layout.
  - Source now lives under `/Users/joshj/dev/codex/collections/ansible_collections/internal/...`.
  - `./internal` compatibility symlinks were removed.

- [x] Remove legacy aggregate pipeline.
  - Deleted `playbooks/common/aggregate_results.yaml`.
  - Deleted `playbooks/templates/site_health_report.md.j2`.
  - Updated Ubuntu playbooks to use `generate_site_health_report.yaml`.

- [ ] Add/restore integration-level CI coverage on the new collection layout.
  - Unit tests and syntax checks are strong now.
  - Runtime integration coverage (Molecule or equivalent) is still thinner than ideal.

## VMware-Specific Hardening (Follow-up)

- [x] Reduce remaining VMware reporting path/layout assumptions.
  - VMware summary reporting no longer uses `split('/playbooks')` path derivation.

- [x] Harden VMware aggregation compatibility adapter with tests.
  - Added adapter type guards and explicit compatibility tests for legacy VMware export shapes.

- [x] Add lightweight VMware discovery defaults contract checks.
  - Added unit test guarding expected `vmware_ctx` default sections to mitigate schema drift from repeated `set_fact + combine`.

- [ ] Consider reducing `vmware_ctx` mutation complexity over time.
  - Not urgent; current mitigations (schema validation + contract tests) make this safer.
  - If discovery keeps growing, consider extracting more state assembly into pure filter/module_utils helpers.
