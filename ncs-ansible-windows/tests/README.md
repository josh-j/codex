# internal.windows — tests

Standalone test harness for the `internal.windows` collection. Runs
the `server_collect` / `server_stig_audit` playbooks against a lab
Windows Server fleet without the `ncs-ansible/` orchestrator.

## Quick start

```sh
cp -r tests/inventory.example tests/inventory
echo 'change-me' > tests/.vault_pass

# If using password auth, encrypt the lab service account password:
ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
    '<svc-account-password>' --name vault_windows_server_password \
    >> tests/inventory/group_vars/windows_servers.yml

just test
# or:
ansible-playbook -i tests/inventory \
  --vault-password-file tests/.vault_pass \
  --check playbooks/server_collect.yml
```

`just test` runs `server_collect.yml` in `--check` mode. `just
test-apply` drops `--check` when you're ready to exercise state
changes against the lab.

## Inventory shape

- `windows_servers` — the managed Windows Server fleet. The default
  connection template is SSH + Kerberos/GSSAPI; see the monorepo's
  [OpenSSH + Kerberos doc](../../docs/OPENSSH_KERBEROS.md) for the
  server-side prerequisites.

The `domain` role's playbooks (`domain_collect.yml`, etc.) target
whichever host-subset you delegate them to at runtime; no separate
static group is required for lab smoke tests.

## What stays out of the tracked tree

`tests/inventory/` and `tests/.vault_pass` are both gitignored.

## Relationship to the orchestrator

See `docs/COLLECTION_LAYOUT.md` in the monorepo root.
