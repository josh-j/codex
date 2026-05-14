# internal.ios — Quickstart

## Prerequisites — install the third-party network collections

`internal.ios` calls `cisco.ios.*` modules and runs over the
`network_cli` connection plugin from `ansible.netcommon`. Neither
ships with this collection — they're third-party and the umbrella's
locally-vendored `requirements.yml` only carries the in-house
`internal.*` tarballs. Install them once per server:

```bash
cd ncs-ansible
just install-network-collections
```

That reads `ncs-ansible/requirements-network.yml` (`ansible.netcommon`
and `cisco.ios` with minimum versions pinned) and lands them in
`collections/` alongside the `internal.*` ones.

### Airgapped install

If the Ansible server has no Galaxy access, download the tarballs on
a connected machine and copy them over:

```bash
# Connected machine:
ansible-galaxy collection download ansible.netcommon cisco.ios \
    -p /tmp/galaxy

# scp /tmp/galaxy/*.tar.gz to the airgapped server, then:
ansible-galaxy collection install --collections-path collections /tmp/galaxy/*.tar.gz
```

## On the switches

```
ip ssh version 2
aaa new-model
aaa authentication login default local
aaa authorization exec default local
username svc-ansible privilege 15 secret <strong-password>
```

For privilege-level escalation via `enable` use the same `username
... privilege 15` line plus an `enable secret`; the role's
`ansible_become_method: enable` then engages cleanly.

## Inventory

Copy `tests/inventory.example/` to `tests/inventory/` (gitignored) and
edit. The required group is `ios_switches`:

```yaml
all:
  children:
    ios_switches:
      hosts:
        sw01: { ansible_host: 10.0.0.10 }
        sw02: { ansible_host: 10.0.0.11 }
```

Group vars (vaulted password values):

```bash
ansible-vault encrypt_string --vault-password-file tests/.vault_pass \
  '<svc-ansible password>' --name 'vault_ios_password' \
  >> tests/inventory/group_vars/ios_switches.yml
```

## Smoke test

```bash
just test          # --check mode against tests/inventory
just test-apply    # real run
```

## Pair with ISE-derived inventory

```yaml
# inventory/ise.ise_nads.yaml
plugin: internal.ise.ise_nads
hostname: ise-pan.example.com
username: ers.readonly
password: !vault | ...
compose:
  ansible_network_os: "'ios' if ise_device_type == 'Switch' else None"
keyed_groups:
  - { key: ise_device_type, prefix: type, separator: "_" }
```

Then:

```bash
ansible-playbook -i inventory/ise.ise_nads.yaml internal.ios.collect \
  --limit type_Switch
```
