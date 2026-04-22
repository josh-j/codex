# internal.linux — tests

Standalone test harness for the `internal.linux` collection. Runs the
`ubuntu_collect` / `photon_stig_audit` playbooks against lab hosts
without needing the `ncs-ansible/` orchestrator.

## Quick start

```sh
# 1. Copy the skeleton inventory to the gitignored working copy
cp -r tests/inventory.example tests/inventory

# 2. Set a test vault password (this file is gitignored)
echo 'change-me' > tests/.vault_pass

# 3. Encrypt the real password for your lab hosts
ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
    '<your-lab-password>' --name vault_ubuntu_server_password \
    >> tests/inventory/group_vars/ubuntu_servers.yml
#   (edit the file to keep only one vault_ubuntu_server_password entry)

# 4. Dry-run the collect playbook
just test
# or:
ansible-playbook -i tests/inventory \
  --vault-password-file tests/.vault_pass \
  --check playbooks/ubuntu_collect.yml
```

`just test` runs `ubuntu_collect.yml` in `--check` mode — safe, no
mutations. `just test-apply` drops `--check` when you're ready to
exercise remediation paths against the lab.

## Inventory shape

Two groups:

- `ubuntu_servers` — Ubuntu 22.04 / 24.04 hosts for the `ubuntu`
  role's collect + STIG plays.
- `photon_servers` — Photon OS 3 hosts (vCenter appliances) for the
  `photon` role.

`tests/inventory.example/group_vars/*.yml` mirrors the shape of
`ncs-ansible/inventory/production/group_vars/` so real secret names
match up if you ever copy vars between them.

## What stays out of the tracked tree

`tests/inventory/` and `tests/.vault_pass` are both gitignored. Only
`tests/inventory.example/`, the README, and (once added) any
self-contained smoke playbooks are tracked.

## Relationship to the orchestrator

The monorepo's `ncs-ansible/` orchestrator has its own production
inventory and vault; neither reads from the other. See
`docs/COLLECTION_LAYOUT.md` in the monorepo root for the split.
