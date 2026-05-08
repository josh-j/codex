# internal.ise - tests

Standalone test harness for the `internal.ise` collection. Runs
`ise_collect` against a lab Cisco ISE deployment without the
`ncs-ansible/` orchestrator.

## Quick Start

```sh
cp -r tests/inventory.example tests/inventory
echo 'change-me' > tests/.vault_pass

ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
    '<ise-admin-password>' --name vault_ise_admin_password \
    >> tests/inventory/group_vars/ise_servers.yml

just test
# or:
ansible-playbook -i tests/inventory \
  --vault-password-file tests/.vault_pass \
  --check playbooks/ise_collect.yml
```

`just test` runs `ise_collect.yml` in `--check` mode. `just test-apply`
drops `--check`; the playbook remains read-only.

## Inventory Shape

- `ise_servers` - Cisco ISE API endpoints. Each host needs ISE API
  credentials and uses `ansible_connection: local`.

## What Stays Out Of The Tracked Tree

`tests/inventory/` and `tests/.vault_pass` are both gitignored.
