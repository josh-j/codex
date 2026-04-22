# Playbook Simplification — Complete

Root cause: **playbooks were doing work that belongs elsewhere** — credentials, key management, path resolution, host routing, and error handling were scattered across playbooks instead of living in inventory group_vars, roles, or standard Ansible variables.

## Changes

| # | Issue | Fix |
|---|-------|-----|
| 1 | VCSA/Photon SSH vars in 5 playbooks | → `inventory/production/group_vars/{vcsa,photon_servers}.yaml` |
| 2 | Ubuntu SSH key + become password | → role `pre_ssh_key.yaml` (set_fact), `inventory/production/group_vars/ubuntu_servers.yaml` |
| 3 | Fragile `playbook_dir/../../../` paths | → `ncs_repo_root` in `inventory/production/group_vars/all/main.yaml` |
| 4 | VCSA double-fallback target variable | → `vcsa_target_hosts \| default('vcsa')` |
| 5 | Parallel VM discovery duplication | → `internal.vmware.common/tasks/register_vm_targets.yaml` |
| 6 | Composite wrappers with no logic | → inlined into site playbooks, wrappers deleted |
| 7 | Missing input validation | → `assert` pre-tasks on all password_rotate playbooks |
| 8 | Inconsistent SSH error handling | → connectivity pre-check in ubuntu + photon role `main.yaml` |
| 9 | `_vcenter_hostname` + `_ncs_vcenter` custom vars | → standard `ansible_host` + `group_names` checks |
| 10 | `vmware_hostname` override support | → `init_vcenter.yaml` sets `ansible_host` from `vmware_hostname` |
| 11 | `ncs_config` in wrong group_vars | → moved to `inventory/production/group_vars/all/main.yaml` |
| 12 | Playbook file naming inconsistency | → `rotate_password.yml` → `password_rotate.yml` (noun-verb) |
| 13 | Undocumented role interfaces | → `argument_specs.yml` for all 7 platform roles + READMEs |
| 14 | Missing lint configs | → `ruff.toml`, `.ansible-lint`, `.vaultpass` placeholder |
| 15 | Vault variables as comments | → real placeholder vars in `inventory/production/group_vars/all/vault.yaml` |
