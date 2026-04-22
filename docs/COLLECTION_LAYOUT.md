# Collection layout — inventory + vault

The ncs-framework splits inventory and vault responsibilities into two
independent worlds that never read from each other:

| World | Lives at | Owns | Uses |
|---|---|---|---|
| **Orchestrator** (`ncs-ansible/`) | `ncs-ansible/inventory/production/` + `ncs-ansible/.vaultpass` | The real production fleet, prod secrets | Run the full site orchestration: `just site`, scheduled collects, reporting |
| **Collection** (`ncs-ansible-<name>/`) | `tests/inventory/` + `tests/.vault_pass` | A lab fixture just big enough to exercise that one collection | Run that collection's playbooks standalone: `cd ncs-ansible-linux && just test` |

This is the Galaxy-canonical layout for published Ansible collections
— `tests/` is where collection-level fixtures go, and production
inventory belongs in the consuming deployment (here, `ncs-ansible/`).

## What each collection ships

```
ncs-ansible-<name>/
├── tests/
│   ├── inventory.example/        # tracked: skeleton hosts + group_vars with placeholder values
│   ├── inventory/                # gitignored: operator fills in for their lab
│   ├── .vault_pass               # gitignored: per-collection test vault password
│   └── README.md                 # quick-start instructions
├── .gitignore                    # excludes tests/inventory/ and tests/.vault_pass
└── Justfile                      # `just test` → --check dry-run; `just test-apply` → real run
```

The tracked `tests/inventory.example/` mirrors the group shape and
`vault_*` variable names used by `ncs-ansible/inventory/production/`
so copying vars between the two worlds is mechanical. Each collection
has its own vault password file so a leak of one lab's test key never
exposes another's.

## Bootstrapping a collection's test lab

```sh
cd ncs-ansible-linux

# 1. Copy the skeleton to the gitignored working copy
cp -r tests/inventory.example tests/inventory

# 2. Create a per-collection vault password (any value; this file is
#    gitignored and local to your checkout)
echo 'change-me' > tests/.vault_pass

# 3. Populate tests/inventory/ with real lab hosts
vi tests/inventory/hosts.yml

# 4. Encrypt real secrets into the inventory's group_vars
ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
    '<your-password>' --name vault_ubuntu_server_password \
    >> tests/inventory/group_vars/ubuntu_servers.yml

# 5. Dry-run the representative playbook
just test

# 6. When ready, drop --check to exercise real remediation
just test-apply
```

Every collection's `tests/README.md` has the same flow with its own
variable names and target playbook.

## Vault password scope — test vs. production

| File | What it encrypts | Machines that see it |
|---|---|---|
| `ncs-ansible-linux/tests/.vault_pass` | Test hosts for linux collection | Developers running `just test` locally |
| `ncs-ansible-vmware/tests/.vault_pass` | Test vCenters for vmware collection | Developers running `just test` locally |
| `ncs-ansible-<other>/tests/.vault_pass` | (same pattern per collection) | Developers only |
| `ncs-ansible/.vaultpass` | **Production** inventory under `ncs-ansible/inventory/production/` | CI runner + on-call operator |

Test vault passwords are disposable and per-collection. Production's
vault password is shared secret with its own rotation cadence; it is
never referenced by collection `tests/` directories and collection
test directories are never referenced by orchestrator playbooks.

## How the orchestrator picks inventory

`ncs-ansible/ansible.cfg` sets `inventory = inventory/production/` and
`vault_password_file = .vaultpass`. When an orchestrator playbook
calls a collection playbook by FQCN (e.g.
`ansible-playbook internal.linux.ubuntu_collect`), Ansible resolves
the playbook inside the collection but evaluates it against the
orchestrator's inventory and vault — the collection's `tests/`
directory is invisible to that run.

## `ncs_configs/` — where reporter configs live

Each built-in collection owns the reporter schemas, CKLB skeletons, and helper scripts that describe its platform. The orchestrator keeps only cross-cutting configs:

| Path | What's there |
|---|---|
| `ncs-ansible/ncs_configs/schedules.yml` | Systemd timer definitions (orchestrator feature) |
| `ncs-ansible/ncs_configs/ncs-reporter/config.yaml` | Primary index — lists each collection's config dir via `extra_config_dirs:` |
| `ncs-ansible/ncs_configs/ncs-reporter/inventory_root.yaml` | Cross-platform inventory-root schema |
| `ncs-ansible-core/ncs_configs/` | (empty — core has no reporter configs) |
| `ncs-ansible-linux/ncs_configs/ncs-reporter/*.yaml` | `linux_base_*`, `ubuntu`, `photon` schemas |
| `ncs-ansible-linux/ncs_configs/ncs-reporter/scripts/user_inventory.py` | Linux helper script referenced by `linux_base_fields.yaml` |
| `ncs-ansible-linux/ncs_configs/ncs-reporter/cklb_skeletons/…` | Ubuntu CKLB skeleton |
| `ncs-ansible-vmware/ncs_configs/ncs-reporter/*.yaml` | `vm`, `esxi`, `vcsa`, `vsphere`, `cluster`, `datacenter` schemas |
| `ncs-ansible-vmware/ncs_configs/ncs-reporter/scripts/*.py` | VMware helper scripts (`get_vms_list`, `count_vm_compliance`, `normalize_snapshots`, `assemble_esxi_hosts`) |
| `ncs-ansible-vmware/ncs_configs/ncs-reporter/cklb_skeletons/…` | vSphere 7 CKLB skeletons (includes `vca_photon_os` — also referenced by `linux/photon.yaml`) |
| `ncs-ansible-windows/ncs_configs/ncs-reporter/windows.yaml` | Windows schema |
| `ncs-ansible-aci/ncs_configs/ncs-reporter/aci.yaml` | ACI schema |

The reporter resolves schemas, scripts, and CKLB skeletons relative to each config file's own directory, so `cklb_skeletons/foo.json` inside `vcsa.yaml` finds the file next to it in the vmware collection. `$include: "linux_base_fields.yaml"` inside `ubuntu.yaml` resolves to the sibling in the linux collection. Invoke the reporter with `--config-dir ncs-ansible/ncs_configs/ncs-reporter` and the orchestrator's `config.yaml` fans out to every collection's dir.

## Don't do these

- Commit `tests/inventory/` or `tests/.vault_pass`. Both are in
  `.gitignore`; if either appears in `git status`, double-check the
  ignore rule hasn't been clobbered.
- Reference `ncs-ansible/inventory/production/` from a collection's
  `tests/` playbook, or vice versa. The worlds are meant to be
  independent — that's why collections can be extracted and reused.
- Reuse the same vault password for a collection's `tests/.vault_pass`
  and `ncs-ansible/.vaultpass`. If the test password leaks it must
  not decrypt production secrets.

## Adding a new collection

Follow the existing five:

1. `mkdir -p ncs-ansible-<name>/tests/inventory.example/group_vars`
2. Populate `tests/inventory.example/hosts.yml` with fake hosts in
   the groups the collection's playbooks target.
3. Populate `tests/inventory.example/group_vars/*.yml` with the
   shape of real group_vars (placeholder values, real
   `vault_*` variable names).
4. Add `tests/README.md` describing quick-start for that collection.
5. Add `.gitignore` entries: `tests/inventory/`,
   `tests/.vault_pass`, plus the normal Python/build-output patterns.
6. Add `test` and `test-apply` recipes to the collection's
   `Justfile`. Use the `_test_inv`, `_test_vault`, `_ap` helpers
   from `shared.just` so the invocation matches the other
   collections.
