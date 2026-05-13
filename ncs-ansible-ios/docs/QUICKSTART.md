# internal.ios — Quickstart

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
