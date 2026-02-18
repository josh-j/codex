# Improvements

1. Define a clear collection boundary contract: what data each collection must read, write, and never touch (especially `ops` namespaces).
2. Establish a single, enforced naming schema for `ops` subtrees per collection (e.g., `ops.vsphere.*`, `ops.linux.*`) with reserved keys.
3. Introduce a shared variable registry: a top-level YAML that lists every inventory variable, default, scope, and owning role.
4. Normalize variable precedence rules (inventory vs. role defaults vs. discovered facts) and enforce them in each role `init.yaml`.
5. Split role variables into `inputs` and `facts` namespaces to prevent accidental overwrite of discovered data.
6. Require every role to publish a minimal interface: `inputs`, `facts`, `alerts`, and `reports` keys under its `ops` namespace.
7. Standardize role lifecycle tasks (`init`, `discover`, `normalize`, `check`, `export`) across all collections and make `main.yaml` a thin orchestrator.
8. Add a common “role contract” task in `internal.core` that validates required keys after `init` and after `normalize`.
9. Consolidate duplicated discovery logic across collections into shared tasks or filters (e.g., time parsing, severity mapping).
10. Define a strict rule for where aggregation happens (only in `internal.core.reporting`) and ban cross-role aggregation.
11. Make collection-level defaults explicit and consistent: one `defaults/main.yaml` per role, no ad-hoc defaults in tasks.
12. Remove implicit reliance on `hostvars['localhost']` outside of the initialization play; pass `run_ctx` explicitly where needed.
13. Use a single naming convention for tags across collections (`discover`, `check`, `export`, `report`, `stig`) to reduce mental mapping.
14. Require roles to emit structured errors as alerts instead of `fail` unless the run must abort.
15. Add a single source file for shared constants (severity levels, categories, status values) to avoid drift between collections.
