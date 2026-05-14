# Multi-tenant deployment

The framework deploys on one shared Ansible server. Multiple
workcenters may use it, each with their own inventories and
credentials but the same collections, the same playbooks, and (today)
the same report share. This doc covers what's isolated and what
isn't, and where the controls live.

The operator-facing how-to with concrete commands lives in
[`../../ncs-ansible/docs/VAULT_LABELED_GROUPS.md`](../../ncs-ansible/docs/VAULT_LABELED_GROUPS.md);
this is the orientation page.

---

## What "workcenter" means here

A logical grouping of inventory + credentials + ops scope. A
workcenter might be:

- A unit / squadron / installation owning a fleet of switches.
- A team responsible for a slice of the VMware estate.
- A distinct ISE deployment within the same parent organization.

Multiple workcenters share:

- One framework checkout (`ncs-framework/`).
- One Ansible install (`ncs-ansible/.venv`).
- One installed set of `internal.*` collections.
- One `ansible.cfg`.
- One report-share path (`/srv/samba/reports/`, today).

What each workcenter owns:

- Its own `group_vars/workcenter_<name>/` directory.
- Its own vault password file (e.g. `/etc/ansible/vaults/<name>.pass`).
- Its own vaulted secrets, labeled with the workcenter's vault ID.
- Optionally, its own static inventory file or its own slice of the
  dynamic ISE-derived NAD population.

---

## Isolation status by surface

| Surface | Mechanism today | Status |
|---|---|---|
| **Credentials** (ERS, SSH, enable) | Per-workcenter `group_vars/workcenter_<name>/vault.yaml` encrypted under a workcenter-labeled vault ID; `vault_identity_list` in `ansible.cfg`; `--limit workcenter_<name>` keeps a run from touching other workcenters' encrypted vars | **Solved (Step 1)** |
| **Inventory scope** | `--limit workcenter_<name>` plus either static `workcenter_<name>` groups or `internal.ise.ise_nads` `keyed_groups: { key: ise_ops_owner, prefix: workcenter }` | **Solved (Step 1)** |
| **Vault-key access** | Filesystem permissions on `/etc/ansible/vaults/<name>.pass` (sysadmin-managed `chown`/`chmod`) | **Solved (Step 1)** — boundary is at the OS layer |
| **Report directory** | All workcenters write under `/srv/samba/reports/`; emit role + `ncs_collector` callback honor `NCS_REPORT_DIRECTORY` env var if set | **Step 2** — per-workcenter subdir via env var requires a wrapper |
| **Inventory cache** | `ise_nads` plugin's `cache_connection: /tmp/ise_nads_cache` is global | **Step 2** — concurrent workcenter runs can clobber |
| **SSH multiplexing** | `control_path_dir = /tmp/.ansible-cp` is global | **Step 2** — same-host connections shared across workcenter runs |
| **Scheduled runs** | `ncs-<schedule>.timer` systemd units share a flat namespace | **Step 2** — collision if two workcenters define the same schedule name |
| **OS user separation** | Out of scope for the framework | Sysadmin policy |

The Step-1 set is enough that a workcenter alpha operator with no
read access to `/etc/ansible/vaults/bravo.pass` cannot reach bravo's
ERS / SSH / enable passwords, even though both workcenters' files
coexist on the same disk. The Step-2 items only matter if
workcenters share output directories or run truly concurrently
against the same target hosts.

---

## The Step-1 mental model

```
                +-------------------------------+
                |   ncs-framework/  (checkout)  |
                |   ansible.cfg, collections,   |
                |   playbooks, role code        |
                +-------------------------------+
                              |
        +---------------------+---------------------+
        |                     |                     |
+---------------+   +---------------+   +---------------+
| workcenter_   |   | workcenter_   |   | workcenter_   |
|  alpha        |   |  bravo        |   |  charlie      |
| group_vars/   |   | group_vars/   |   | group_vars/   |
|   main.yaml   |   |   main.yaml   |   |   main.yaml   |
|   vault.yaml  |   |   vault.yaml  |   |   vault.yaml  |
|   (alpha key) |   |   (bravo key) |   |   (charlie    |
|               |   |               |   |    key)       |
+---------------+   +---------------+   +---------------+
```

Each operator loads only their workcenter's vault key (via
`vault_identity_list` in `ansible.cfg`, or `--vault-id` on the CLI).
Ansible's lazy decryption ensures that a `--limit workcenter_alpha`
run never tries to decrypt bravo's or charlie's files, so the
absence of those keys is invisible to the alpha operator.

---

## What to do next

- **Setting up a new workcenter today**: follow the operator guide
  at [`ncs-ansible/docs/VAULT_LABELED_GROUPS.md`](../../ncs-ansible/docs/VAULT_LABELED_GROUPS.md). The
  `just new-workcenter <name>` recipe in `ncs-ansible/Justfile`
  scaffolds the directory and key indirection for you; you encrypt
  the resulting `vault.yaml` with `ansible-vault create --vault-id
  <name>@<pass-path>`.
- **Tagging hosts with workcenter dynamically**: see the
  `keyed_groups` example in
  [`ncs-ansible-ise/docs/EXAMPLE.ise_nads.yaml`](../../ncs-ansible-ise/docs/EXAMPLE.ise_nads.yaml).
  Maps each NAD's `ise_ops_owner` NDG to a `workcenter_<owner>`
  group automatically.
- **If you hit any of the Step-2 limitations** (concurrent cache
  clobbering, report-share readback across workcenters, schedule-name
  collisions), open a follow-up plan. The fixes are small (a wrapper
  script setting `NCS_REPORT_DIRECTORY` / `ANSIBLE_INVENTORY_CACHE_CONNECTION`
  per workcenter and a workcenter-prefix variable for the systemd
  units) but require deciding on a deployment-side layout convention.

---

## Quick reference

```bash
# One-time sysadmin
sudo install -d -m 0750 -o root -g ansible /etc/ansible/vaults
openssl rand -base64 32 | sudo tee /etc/ansible/vaults/alpha.pass >/dev/null
sudo chmod 600 /etc/ansible/vaults/alpha.pass
sudo chown <alpha-op-uid>:<alpha-group> /etc/ansible/vaults/alpha.pass

# Add to ncs-ansible/ansible.cfg:
#   vault_identity_list = default@.vaultpass, alpha@/etc/ansible/vaults/alpha.pass

# Scaffold + encrypt the workcenter
cd ncs-ansible
just new-workcenter alpha
ansible-vault create --vault-id alpha@/etc/ansible/vaults/alpha.pass \
    inventory/production/group_vars/workcenter_alpha/vault.yaml

# Operator run, scoped
ansible-playbook -i inventory/production internal.ios.collect \
    --limit workcenter_alpha
```

For the full operator workflow (edit / view / rekey, migration from
the single-`.vaultpass` setup, decryption-laziness semantics),
see [`ncs-ansible/docs/VAULT_LABELED_GROUPS.md`](../../ncs-ansible/docs/VAULT_LABELED_GROUPS.md).
