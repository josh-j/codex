# Vault-labeled group_vars — first-step workcenter isolation

The framework deploys on one shared Ansible server. Multiple
workcenters may use it, each with their own inventories and
credentials. This document covers the simplest pattern for keeping
each workcenter's secrets opaque to the others: per-workcenter
group_vars files vault-encrypted under a workcenter-specific vault-id
label.

This is **Step 1**. It gives credential isolation without touching
the rest of the deployment shape (one inventory tree, one collections
install, one report directory). Per-workcenter report dirs, inventory
caches, and SSH multiplexing paths are tracked separately as Step 2.

---

## How it works

Ansible's `vault_identity_list` lets you load multiple vault
passwords, each with a label:

```ini
vault_identity_list = default@.vaultpass, alpha@/etc/ansible/vaults/alpha.pass, bravo@/etc/ansible/vaults/bravo.pass
```

When Ansible encounters a `!vault` block, it reads the label from the
block's header (`$ANSIBLE_VAULT;1.2;AES256;alpha`) and uses the
matching key to decrypt. If no loaded key matches the label, the
block stays opaque — Ansible doesn't error until the playbook
actually tries to *read* the value.

Combined with `ansible-playbook --limit workcenter_<name>`, this
means:

- **Workcenter operator runs scoped to their own hosts** → only their
  group_vars get touched → only their vault label needs to be loaded.
- **Other workcenters' encrypted group_vars sit on disk untouched** —
  even if the operator can SSH to the server, they can't decrypt
  another workcenter's secrets without that workcenter's `.pass` file
  (which is OS-level chowned to the right group).

---

## Directory layout

```
ncs-ansible/inventory/production/group_vars/
├── all/                              # shared across every host
│   ├── main.yaml                     # plain
│   └── vault.yaml                    # encrypted under `default` label
├── workcenter_example/               # template; copy to make new workcenters
│   ├── main.yaml
│   └── vault.yaml.example
├── workcenter_alpha/                 # one workcenter's data
│   ├── main.yaml                     # plain config
│   └── vault.yaml                    # encrypted under `alpha` label
└── workcenter_bravo/
    ├── main.yaml
    └── vault.yaml                    # encrypted under `bravo` label
```

Within each workcenter:

- **`main.yaml`** (plain, committed): connection settings, knobs,
  references to vault values via Jinja indirection.
- **`vault.yaml`** (encrypted, committed in cipher form): the actual
  secret values, keyed by `vault_<workcenter>_<purpose>`.

The indirection pattern (plain `main.yaml` referencing
`{{ vault_<workcenter>_<purpose> }}`) keeps the encrypted file's keys
grep-able and makes accidental plain-text edits jump out in review.

---

## One-time setup (sysadmin)

```bash
# 1. Generate a per-workcenter vault key
sudo install -d -m 0750 -o root -g ansible /etc/ansible/vaults
openssl rand -base64 32 | sudo tee /etc/ansible/vaults/alpha.pass >/dev/null
sudo chmod 600 /etc/ansible/vaults/alpha.pass
sudo chown <alpha-operator-uid>:<alpha-group> /etc/ansible/vaults/alpha.pass

# 2. Add the label to ansible.cfg
#    vault_identity_list = default@.vaultpass, alpha@/etc/ansible/vaults/alpha.pass

# 3. Scaffold the workcenter's group_vars dir
cp -r inventory/production/group_vars/workcenter_example \
      inventory/production/group_vars/workcenter_alpha
# Rename `vault_example_*` keys in main.yaml to `vault_alpha_*`.

# 4. Create the encrypted vault.yaml
ansible-vault create \
    --vault-id alpha@/etc/ansible/vaults/alpha.pass \
    inventory/production/group_vars/workcenter_alpha/vault.yaml
# Editor opens; paste:
#   vault_alpha_ise_password: "<real password>"
#   vault_alpha_ssh_password: "<real password>"
#   vault_alpha_enable_password: "<real enable>"
# Save + exit; the file is now encrypted on disk.

# 5. Add hosts to the workcenter_alpha group via either a static
#    inventory YAML or the dynamic ise_nads plugin's keyed_groups
#    (see "Tagging hosts" below).
```

---

## Day-to-day operator commands

```bash
# Edit secrets later
ansible-vault edit \
    --vault-id alpha@/etc/ansible/vaults/alpha.pass \
    inventory/production/group_vars/workcenter_alpha/vault.yaml

# View without editing
ansible-vault view \
    --vault-id alpha@/etc/ansible/vaults/alpha.pass \
    inventory/production/group_vars/workcenter_alpha/vault.yaml

# Re-key (e.g., after operator handoff)
ansible-vault rekey \
    --vault-id alpha@/etc/ansible/vaults/alpha.pass \
    --new-vault-id alpha@/etc/ansible/vaults/alpha-new.pass \
    inventory/production/group_vars/workcenter_alpha/vault.yaml

# Run a playbook scoped to one workcenter
ansible-playbook -i inventory/production internal.ios.collect \
    --limit workcenter_alpha
# vault_identity_list in ansible.cfg picks up the alpha key
# automatically; no explicit --vault-id needed.
```

---

## Tagging hosts with a workcenter

**Static**: add the host to a `workcenter_<name>` group in any
inventory YAML:

```yaml
all:
  children:
    workcenter_alpha:
      hosts:
        sw-aaa-01: { ansible_host: 10.1.1.10 }
        sw-aaa-02: { ansible_host: 10.1.1.11 }
```

**Dynamic (ISE-driven)**: in your `.ise_nads.yaml` plugin config, add
a `keyed_groups` entry that derives workcenter from an ISE NDG field.
Most fleets use the `Ops Owner` NDG hierarchy as the workcenter
classifier:

```yaml
keyed_groups:
  - key: ise_ops_owner
    prefix: workcenter
    separator: "_"
```

Every NAD with `ise_ops_owner: NetworkOps_Alpha` lands in
`workcenter_NetworkOps_Alpha`. That group's `group_vars/` directory
provides the matching credentials automatically.

---

## Decryption-laziness semantics (read this)

Ansible decrypts vaulted content **lazily** — only when a playbook
actually references a vaulted variable. The practical implications:

| Run pattern | What gets decrypted | Workcenter alpha's key needed? |
|---|---|---|
| `--limit workcenter_alpha` | Only `workcenter_alpha`'s group_vars | Yes |
| No `--limit`, play `hosts: all` that reads workcenter-scoped vars | Every workcenter's group_vars Ansible iterates over | All loaded labels |
| No `--limit`, play `hosts: workcenter_alpha` | Only `workcenter_alpha`'s group_vars | Yes |
| `ansible-inventory --list` | Inventory structure only, not vault content | None |

**Failure mode**: if an operator forgets `--limit` and Ansible
iterates a host whose group_vars are encrypted under a label they
don't have loaded, the run errors with `Attempting to decrypt but no
vault secrets found`. That's the expected isolation in action — they
shouldn't be running against that workcenter.

---

## Migration from a single `.vaultpass` setup

Existing `.vaultpass`-encrypted content keeps working. Ansible
treats anything encrypted without an explicit label as the `default`
label, and the new `vault_identity_list = default@.vaultpass, …`
keeps that key loaded. Nothing in `group_vars/all/vault.yaml` or any
previously-vaulted file needs re-encryption.

When you add a new workcenter, only that workcenter's vault.yaml is
encrypted under its label. Older shared secrets stay under `default`.

---

## What this approach does NOT do (Step 2 work)

- **Report directory isolation**: every workcenter still writes under
  `/srv/samba/reports/`. Cross-workcenter operators can read each
  other's report bundles.
- **Inventory-cache isolation**: the `ise_nads` plugin's
  `cache_connection: /tmp/ise_nads_cache` is shared; simultaneous
  workcenter runs against the same path will clobber each other's
  cached NAD lists.
- **SSH control-path isolation**: `control_path_dir = /tmp/.ansible-cp`
  is global; concurrent runs to the same target host from different
  workcenters share the multiplex socket.
- **Scheduled-run namespace**: `ncs-<schedule>.timer` units are
  installed system-wide. Two workcenters defining a schedule named
  `nightly` would collide.
- **OS-level user separation**: this assumes the sysadmin handles
  who can `cat /etc/ansible/vaults/alpha.pass`. The framework does
  not enforce filesystem ACLs.

If a workcenter actually needs all of the above isolated, the next
step is a per-workcenter overlay directory with its own `ansible.cfg`,
report dir, cache path, and systemd unit prefix. Tracked as a
follow-up plan.
