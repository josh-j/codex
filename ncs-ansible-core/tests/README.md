# internal.core — tests

Standalone test harness for the `internal.core` collection. No
orchestrator required.

## Quick start

```sh
# 1. Copy the example inventory (tracked) to the gitignored working copy
cp -r tests/inventory.example tests/inventory

# 2. Add a vault password file if you want to encrypt any test secrets
echo 'change-me' > tests/.vault_pass

# 3. Run the smoke test
ansible-playbook -i tests/inventory \
  --vault-password-file tests/.vault_pass \
  tests/smoke.yml

# or, from a checkout alongside the monorepo:
just test
```

`tests/smoke.yml` runs the `internal.core.stig` action plugin against
localhost with a trivial `_stig_validate_expr` rule. Success means the
wrapper is wired correctly and the callback plugin can emit structured
STIG events.

## What stays out of the tracked tree

`tests/inventory/` and `tests/.vault_pass` are both gitignored. The
only tracked artifacts under `tests/` are the skeleton
(`tests/inventory.example/`), the smoke playbook, and this README.

## Relationship to the orchestrator

The monorepo's `ncs-ansible/` orchestrator has its own production
inventory at `ncs-ansible/inventory/production/` and its own vault
password at `ncs-ansible/.vaultpass`. That world is completely separate
from this one — running `just test` here never reads from there, and
vice versa. See `docs/collections/COLLECTION_LAYOUT.md` in the monorepo root for
the full split.
