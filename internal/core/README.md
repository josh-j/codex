# internal.core

Shared plugin framework and orchestration roles used by all platform-specific internal collections. Provides the unified action/profile/operation interface, STIG automation engine, PowerShell execution wrapper, and telemetry collection callback.

This is the base dependency every `internal.<platform>` collection declares.
It has no Ansible-collection dependencies of its own.

## Installation

```bash
# from a built tarball
ansible-galaxy collection install internal-core-<version>.tar.gz

# or via the app repo's requirements.yml manifest
ansible-galaxy collection install -r requirements.yml
```

## Plugins

| Plugin | Type | Purpose |
|---|---|---|
| `ncs_collector` | callback | Intercepts `ncs_collect` data from `set_stats` and persists `raw_*.yaml` / `raw_stig_*.yaml` artifacts — the bridge between Stage 1 (Ansible) and Stage 2 (ncs-reporter) |
| `stig` | action + module | Wraps any Ansible module with STIG audit/remediation semantics — handles phase routing, gating (packages, services, files, vars), and `_stig_manage` host var lookups |
| `stig_pwsh` | action + module | STIG wrapper variant for PowerShell-based checks |
| `pwsh` | action + module | PowerCLI execution wrapper — auto-connects to vCenter, pre-sets `$vmhost`/`$esxcli`/`$view`, handles credential passing and output normalization |
| `path_contract` | module_utils | Path template resolution and validation for reporting directories |

See [plugins/callback/README.md](plugins/callback/README.md) for callback-specific details.

## Roles

| Role | Purpose |
|---|---|
| `dispatch` | Universal action router — validates `ncs_action`, `ncs_profile`, `ncs_operation` and routes to the correct task file via a configurable dispatch map |
| `emit` | Standardized telemetry emitter — wraps `set_stats` with consistent `ncs_collect` schema for the `ncs_collector` callback |
| `stig_orchestrator` | Three-phase STIG runner: Phase 0 (facts + validation) → Phase 1 (audit or remediate) → Phase 2 (post-remediation verification via check_mode audit). Emits results via `emit` |

## Integration Flow

Every platform role follows this pipeline:

```
Role main.yaml
  → dispatch (validates action/profile/operation, resolves task file)
    → Mapped task (collect, stig, maintain/*, ops/*)
      → stig_orchestrator (for STIG profiles)
        → Phase 0: Facts, validations, compat aliases
        → Phase 1: Audit/remediate loop
        → Phase 2: Verification (check_mode)
        → emit (persists telemetry)
      → ncs_collector callback (writes raw_*.yaml to disk)
```

## Interface Variables

All platform roles share a common entry point contract:

| Variable | Values | Description |
|---|---|---|
| `ncs_action` | `collect`, `audit`, `remediate`, `verify` | What operation to perform |
| `ncs_profile` | `stig`, `health`, etc. | Scoped behavior profile (mutually exclusive with `ncs_operation`) |
| `ncs_operation` | role-specific (e.g. `password_rotate`) | Named maintenance operation (mutually exclusive with `ncs_profile`) |
