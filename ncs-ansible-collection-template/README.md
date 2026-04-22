# internal.__COLLECTION_NAME__

Audit, collection, and STIG automation for __COLLECTION_NAME__.

Depends on `internal.core` (`>=1.0.0,<2.0.0`) for the shared
action/profile/operation dispatch framework and the `ncs_collector`
callback plugin.

## Installation

```bash
# from a built tarball
ansible-galaxy collection install internal-__COLLECTION_NAME__-<version>.tar.gz

# or via the app repo's requirements.yml manifest
ansible-galaxy collection install -r requirements.yml
```

Playbooks ship under `playbooks/` and are invoked by FQCN:

```bash
ansible-playbook -i inventory/production internal.__COLLECTION_NAME__.<name>
```

## Layout

```
ncs-ansible-__COLLECTION_NAME__/
├── galaxy.yml                         # namespace/name/version + dependency on internal.core
├── meta/runtime.yml                   # required ansible-core version
├── roles/
│   └── example/                       # scaffolded example role — rename or replace
│       ├── tasks/{main,collect}.yaml
│       ├── defaults/main.yaml
│       ├── meta/main.yaml
│       └── README.md
├── playbooks/
│   └── example_collect.yml            # scaffolded example playbook
├── plugins/                           # optional: action/filter/callback plugins
└── CHANGELOG.md
```

The `example` role + `example_collect.yml` playbook are a working
minimum that dispatches via `internal.core.dispatch` and emits
`raw_example.yaml` via `internal.core.emit`. Treat them as a starting
point — rename, replace, or delete once your real platform code is
in place.

Playbook filename convention: flat, prefixed with the sub-platform (if
any) then the action. Examples from the existing collections:

- `esxi_collect.yml`, `esxi_stig_audit.yml`, `esxi_stig_remediate.yml`
- `ubuntu_collect.yml`, `ubuntu_update.yml`, `ubuntu_password_rotate.yml`
- `server_collect.yml`, `server_stig_audit.yml`, `domain_run.yml`

Invoked as `internal.__COLLECTION_NAME__.<filename>` (no `.yml` suffix).

## Patterns

See `HELPERS.md` for the NCS role interface — how to use
`internal.core.dispatch` for action routing, the shared
`ncs_action` / `ncs_profile` / `ncs_operation` contract, and the
`# >>> / # <<<` metadata blocks that drive ncs-console's UI.
