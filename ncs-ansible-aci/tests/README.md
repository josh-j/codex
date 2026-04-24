# internal.aci — tests

Standalone test harness for the `internal.aci` collection. Runs
`apic_collect` against a lab APIC without the `ncs-ansible/`
orchestrator.

## Quick start

```sh
cp -r tests/inventory.example tests/inventory
echo 'change-me' > tests/.vault_pass

ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
    '<apic-admin-password>' --name vault_aci_admin_password \
    >> tests/inventory/group_vars/aci_apics.yml

just test
# or:
ansible-playbook -i tests/inventory \
  --vault-password-file tests/.vault_pass \
  --check playbooks/apic_collect.yml
```

`just test` runs `apic_collect.yml` in `--check` mode. `just
test-apply` drops `--check` (note: `apic_collect` is read-only, so
`test-apply` mainly exercises the non-check branches).

## Inventory shape

- `aci_apics` — APIC controllers. Each host needs `aci_username` and
  `aci_password`; connection is always `local` because the role
  talks to the APIC REST API over HTTPS.

## What stays out of the tracked tree

`tests/inventory/` and `tests/.vault_pass` are both gitignored.

## Relationship to the orchestrator

See `docs/collections/COLLECTION_LAYOUT.md` in the monorepo root.
