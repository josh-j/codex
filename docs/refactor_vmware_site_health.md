# VMware Site Health Refactor (Composable Architecture)

## Purpose
Make the VMware/vSphere portion of `playbooks/site_health.yaml` composable and less brittle while preserving today’s end result: a single site health report that aggregates alerts, findings, and artifacts across sites.

## Current End Result (Behavioral Baseline)
The current flow produces:
- A **run context** with `run_ctx.id/date/timestamp/tasks` from the init play.
- Per-site execution of domain roles (vCenter, Unity, DataDomain, UCS) that populate `ops.alerts`, `ops.reports`, `ops.overall`.
- A **summary report** (HTML + Markdown) rendered on localhost that aggregates per-site alerts and report registrations.

This refactor must preserve:
- Same output report formats and templates (`site_health_report.md.j2` and `.html.j2`).
- Same aggregation behavior in `internal.core.reporting:aggregate`.
- Same run-level report directories and CSV exports.

## Goals
1. **Composable capabilities** for VMware stack (vCenter + ESXi + future) that can be assembled by playbooks.
2. **Explicit contracts** for inputs/outputs so roles are reusable and predictable.
3. **No regressions** in `playbooks/site_health.yaml` output (site health summary remains identical in structure).
4. **Backward compatibility** for existing playbooks and inventory groups during migration.

## Non-Goals
- Rewriting non-VMware roles (Unity, DataDomain, UCS).
- Changing report templates or the aggregation algorithm.
- Introducing new dependencies or external APIs.

## Proposed Architecture
### 1) Capability Roles (Composable, Narrow)
Each role does one thing and writes to `vmware_ctx` only.

- `internal.vmware.discovery`
  - Inputs: vCenter/ESXi credentials.
  - Outputs: `vmware_ctx.discovery` (raw connectivity and IDs).

- `internal.vmware.inventory`
  - Inputs: `vmware_ctx.discovery`.
  - Outputs: `vmware_ctx.inventory` (datacenters, clusters, hosts, VMs).

- `internal.vmware.health`
  - Inputs: `vmware_ctx.discovery`.
  - Outputs: `vmware_ctx.health` (appliance health, backup status, alarms).

- `internal.vmware.compliance`
  - Inputs: `vmware_ctx.inventory`.
  - Outputs: `vmware_ctx.compliance` (policy checks, violations).

- `internal.vmware.alerts`
  - Inputs: `vmware_ctx.*`.
  - Outputs: `vmware_ctx.alerts` and optionally `ops.alerts`.

- `internal.vmware.export`
  - Inputs: `vmware_ctx.*`.
  - Outputs: artifacts, registers in `ops.reports`.

### 2) Assembly Playbook (Thin)
A new `playbooks/vmware_site_health.yaml` (or the existing `site_health.yaml`) orchestrates:
1. `internal.vmware.discovery`
2. `internal.vmware.inventory`
3. `internal.vmware.health`
4. `internal.vmware.compliance`
5. `internal.vmware.alerts`
6. `internal.vmware.export`

Each step is optional via tags or `ops_config.schedule`.

### 3) Compatibility Shims
Keep existing entrypoints but make them thin wrappers:
- `internal.vsphere.vsphere_audit` becomes a wrapper role that calls the new capability roles.
- `internal.esxi.esxi_audit` (if added) follows the same pattern.

This allows existing playbooks and inventories to keep working while migration is staged.

## Data Contracts
Introduce a `vmware_ctx` contract with versioning:

- `vmware_ctx.version`: semantic version string.
- `vmware_ctx.run`: derived from `run_ctx`.
- `vmware_ctx.discovery`: connection and IDs.
- `vmware_ctx.inventory`: datacenters/clusters/hosts/vms.
- `vmware_ctx.health`: appliance health, backup, alarms.
- `vmware_ctx.compliance`: checks/violations.
- `vmware_ctx.alerts`: normalized alert list.
- `vmware_ctx.exports`: paths to generated artifacts.

Each capability role must `assert` its required inputs and guarantee its outputs.

## Variable Conventions (Before Refactor)
Clarify variable boundaries so composable roles can plug in safely.

- `run_ctx` is canonical: all time/run metadata comes from `run_ctx` and is set once in the init play.
- `ops.check` is derived: preserve existing usage, but populate it only from `run_ctx` in the worker play.
- `ops.alerts` / `ops.reports` are outputs: roles append to these, they are never defined in group_vars.
- `vmware_ctx` is VMware-scoped: all VMware/vSphere/ESXi domain outputs go here.
- Group vars are static config only: credentials, endpoints, feature toggles. No runtime state (no `run_id`, timestamps, alerts).
- Output paths are standardized: use `ops_report_output_dir` plus `run_ctx.id` for all artifacts.

This avoids runtime state leakage in group_vars and keeps run metadata consistent across all composable roles.

## Mapping Current Behavior to Composable Roles
| Current Source | New Capability |
| --- | --- |
| `vsphere_audit/tasks/infrastructure/discover.yaml` | `internal.vmware.discovery` + `internal.vmware.inventory` |
| `vsphere_audit/tasks/summary/calculate.yaml` | `internal.vmware.alerts` |
| `vsphere_audit/tasks/exports.yaml` | `internal.vmware.export` |
| `ops.alerts` population | `internal.vmware.alerts` (with shim to `ops.alerts`) |
| CSV exports | `internal.vmware.export` (uses core reporting) |

## Migration Plan
### Phase 1: Introduce `vmware_ctx`
- Add `vmware_ctx` initialization from `run_ctx` in site health worker play.
- Add assertions for required context.
- No functional change yet.

### Phase 2: Extract Discovery + Inventory
- Create `internal.vmware.discovery` and `internal.vmware.inventory` from existing `vsphere_audit` tasks.
- Update `internal.vsphere.vsphere_audit` to call new roles.
- Keep outputs in both `vcenter` and `vmware_ctx` during transition if needed.

### Phase 3: Alerts + Export
- Move alert normalization and CSV/export into `internal.vmware.alerts` and `internal.vmware.export`.
- Ensure `ops.alerts` and `ops.reports` are populated identically to current flow.

### Phase 4: Update `site_health.yaml`
- Replace direct `internal.vsphere.vsphere_audit` call with new assembly sequence, OR
- Keep `vsphere_audit` for now but allow composable roles in parallel.

## Compatibility and Risk Controls
- Keep report formats unchanged.
- Keep `ops.alerts` and `ops.reports` populated so aggregation remains stable.
- Add `assert` validations at each step to fail fast rather than partially succeed.
- Use `ops_report_output_dir` and `run_ctx.id` consistently for all artifacts.

## Success Criteria
- `playbooks/site_health.yaml` renders the same summary report without template changes.
- CSV exports and artifacts appear in the same directories.
- `ops.reports` registrations remain complete and consistent.
- VMware checks can run as:
  - vCenter-only
  - ESXi-only
  - Combined VMware stack

## Open Questions
- Do we want `vmware_ctx` to fully replace the `vcenter` fact, or maintain a transition layer?
yes fully replace
- Should ESXi direct audits be optional when vCenter is available (default off)?
yes optional
- Which modules are the preferred standard: `vmware_rest` or `vmware.vmware`?
vmware.vmware
