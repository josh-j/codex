# internal.vmware — tests

Standalone test harness for the `internal.vmware` collection. Runs the
`esxi_collect` / `esxi_stig_audit` playbooks against a lab vCenter and
its ESXi hosts without the `ncs-ansible/` orchestrator.

## Quick start

```sh
cp -r tests/inventory.example tests/inventory
echo 'change-me' > tests/.vault_pass

# Encrypt vCenter admin password
ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
    '<vcenter-admin-password>' --name vault_vcenter_password \
    >> tests/inventory/group_vars/vcsa.yml
#   (prune to one vault_vcenter_password line)

just test
# or:
ansible-playbook -i tests/inventory \
  --vault-password-file tests/.vault_pass \
  --check playbooks/esxi_collect.yml
```

`just test` runs `esxi_collect.yml` in `--check` mode. `just
test-apply` drops `--check` for exercising STIG remediation paths
against the lab.

## Inventory shape

- `vcsa` — the vCenter appliance(s). Each host needs
  `vmware_hostname`, `vmware_username`, `vmware_password`.
- `esxi_hosts` — ESXi hosts beneath those vCenters. The playbooks run
  with `connection: local` and reach hosts via vCenter, so no direct
  SSH credentials are needed here.

The VM-level STIG playbooks (`vm_stig_audit.yml`) populate a dynamic
`vm_targets` group at runtime — you do not need to declare it in the
static inventory.

## What stays out of the tracked tree

`tests/inventory/` and `tests/.vault_pass` are both gitignored.

## Relationship to the orchestrator

See `docs/collections/COLLECTION_LAYOUT.md` in the monorepo root.
