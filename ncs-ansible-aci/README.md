# internal.aci

Audit, collection, and STIG automation for aci.

Depends on `internal.core` (`>=1.0.0,<2.0.0`) for the shared
action/profile/operation dispatch framework and the `ncs_collector`
callback plugin.

## Installation

```bash
# from a built tarball
ansible-galaxy collection install internal-aci-<version>.tar.gz

# or via the app repo's requirements.yml manifest
ansible-galaxy collection install -r requirements.yml
```

Playbooks ship under `playbooks/` and are invoked by FQCN:

```bash
ansible-playbook -i inventory/production internal.aci.<name>
```

## Layout

```
ncs-ansible-aci/
├── galaxy.yml           # namespace/name/version + dependency on internal.core
├── meta/runtime.yml     # required ansible-core version
├── roles/               # one role per logical unit (platform, operation area)
├── playbooks/           # flat filename convention: <sub>_<action>.yml
├── plugins/             # optional: action/filter/callback plugins
└── CHANGELOG.md
```

Playbook filename convention: flat, prefixed with the sub-platform (if
any) then the action. Examples from the existing collections:

- `esxi_collect.yml`, `esxi_stig_audit.yml`, `esxi_stig_remediate.yml`
- `ubuntu_collect.yml`, `ubuntu_update.yml`, `ubuntu_password_rotate.yml`
- `server_collect.yml`, `server_stig_audit.yml`, `domain_run.yml`

Invoked as `internal.aci.<filename>` (no `.yml` suffix).

## Patterns

See `HELPERS.md` for the NCS role interface — how to use
`internal.core.dispatch` for action routing, the shared
`ncs_action` / `ncs_profile` / `ncs_operation` contract, and the
`# >>> / # <<<` metadata blocks that drive ncs-console's UI.
