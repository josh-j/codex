# Role Composable Refactor Guide

## Purpose
Provide a lightweight guide for refactoring monolithic roles into composable capabilities while preserving current behavior and outputs.

## Goals
- Keep existing playbooks and reports working during migration.
- Make role functionality reusable and testable in isolation.
- Clarify data contracts and ownership of runtime state.

## Principles
- Single responsibility per role (capability roles).
- Explicit input/output contracts (`assert` in tasks).
- Canonical run metadata (`run_ctx`) only set once.
- Runtime state lives in scoped contexts (e.g., `vmware_ctx`).
- Backward compatibility via thin wrapper roles.

## Recommended Steps
1. **Identify capabilities**
   - Split into discovery, inventory, health, compliance, alerts, export.
2. **Create scoped context**
   - Introduce `<domain>_ctx` and initialize from `run_ctx`.
3. **Extract capability roles**
   - Move tasks into `internal.<domain>.<capability>` roles.
4. **Wire wrappers**
   - Update existing monolith role to include the new roles.
5. **Add assertions**
   - Validate required inputs and guarantee outputs.
6. **Migrate producers**
   - Populate `<domain>_ctx` from existing data sources.
7. **Remove fallbacks**
   - Once stable, stop reading legacy namespaces.

## Variable Conventions
- `run_ctx` is canonical and read-only after init play.
- `ops.check` is derived from `run_ctx` in worker play.
- `ops.alerts` / `ops.reports` are outputs only.
- `<domain>_ctx` is the primary namespace for capability roles.
- Group vars contain static config only (no runtime state).

## Compatibility Strategy
- Keep templates and report aggregation unchanged.
- Keep output directories and report names stable.
- Use thin wrappers to preserve current playbook entrypoints.
