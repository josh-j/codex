# internal.template

Gold-standard scaffold for creating new NCS platform collections.

## Quick Start

```bash
# 1. Copy the template
cp -r internal/template internal/<platform>

# 2. Rename the example role
mv internal/<platform>/roles/example internal/<platform>/roles/<role_name>

# 3. Search-and-replace all TEMPLATE markers
grep -rn "TEMPLATE:" internal/<platform>/

# 4. Replace placeholder names throughout:
#    - "template"  → your collection name  (galaxy.yml, meta, README)
#    - "example"   → your role name        (defaults, tasks, meta)
#    - "Example"   → your display label    (task name prefixes)
#    - "platform/example" → your platform path (emit calls)

# 5. Symlink into the collections tree
ln -s "$(pwd)/internal/<platform>" \
      collections/ansible_collections/internal/<platform>

# 6. Add a playbook under playbooks/<platform>/
```

## What's Included

### Collection Scaffolding

| File | Purpose |
|---|---|
| `galaxy.yml` | Collection metadata |
| `meta/runtime.yml` | Ansible version constraint |
| `plugins/` | Empty plugin dirs (filter, module_utils, modules) |

### Role: `example`

| Path | Purpose |
|---|---|
| `tasks/main.yaml` | Dispatcher entry point via `internal.core.dispatch` |
| `tasks/collect.yaml` | Discovery and telemetry emission via `internal.core.emit` |
| `tasks/stig.yaml` | STIG orchestrator wiring via `internal.core.stig_orchestrator` |
| `tasks/maintain/` | Operation stubs (password_rotate, password_status) |
| `tasks/stig_v1r0/` | STIG task stubs (prelude, post-stig) |
| `defaults/main.yaml` | Feature flags and thresholds |
| `handlers/main.yaml` | Service restart handler stubs |
| `meta/main.yml` | Role metadata and dependencies |

## Conventions

- All YAML files use `.yaml` extension (except role `meta/main.yml`)
- Task name prefixes: `"<Platform> | <description>"`
- Private vars: `_ncs_*` prefix
- Public defaults: `<role>_*` prefix (e.g. `example_stig_enable_audit`)
- Emit platform path: `"<category>/<role>"` (e.g. `"linux/ubuntu"`)
- Customization points are marked with `# TEMPLATE:` comments
