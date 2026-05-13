# internal.ios

Cisco IOS / IOS-XE collect + small operator-driven config operations.

Depends on `internal.core` (`>=1.0.0,<2.0.0`) for the shared
action/profile/operation dispatch framework and the `ncs_collector`
callback plugin.

## What it does

- **Collect**: gather baseline state from each switch (version, model,
  serial, interfaces, VLANs, AAA / RADIUS / TACACS config, syslog
  destinations) and emit `raw_ios.yaml` for the reporter.
- **Switchport Config**: set access VLAN, voice VLAN, description,
  shutdown/no-shutdown on one interface.
- **Apply Interface Template**: bind a pre-existing IOS-XE port-template
  to an interface (`interface <if>` / `source template <name>`).
- **Change Syslog Server**: replace one `logging host <ip>` with a new
  IP, optionally per VRF.

Each op is one console button via the `# >>>` annotation block in
`playbooks/ios_ops.yml`; all three are `mutating: true` so ncs-console
prompts before applying.

## Installation

```bash
# from the vendored tarball
ansible-galaxy collection install internal-ios-<version>.tar.gz

# or via the umbrella's requirements.yml
ansible-galaxy collection install -r requirements.yml
```

## Usage

Playbooks ship under `playbooks/` and are invoked by FQCN:

```bash
# Baseline collect over SSH (network_cli)
ansible-playbook -i inventory/production internal.ios.collect

# Switchport change on one interface
ansible-playbook -i inventory/production internal.ios.ios_ops \
  -e ncs_operation=switchport_config \
  -e ios_interface=GigabitEthernet1/0/10 \
  -e ios_access_vlan=20 \
  -e ios_voice_vlan=30 \
  -e ios_description="user printer"

# Bind a port-template that already exists on the switch
ansible-playbook -i inventory/production internal.ios.ios_ops \
  -e ncs_operation=apply_template \
  -e ios_interface=GigabitEthernet1/0/10 \
  -e ios_template_name=CORP_ACCESS

# Replace a syslog destination
ansible-playbook -i inventory/production internal.ios.ios_ops \
  -e ncs_operation=change_syslog \
  -e ios_syslog_old=10.0.0.5 \
  -e ios_syslog_new=10.0.0.6
```

Required inventory shape (see `tests/inventory.example/`):

```yaml
ansible_connection: network_cli
ansible_network_os: ios
ansible_user: svc-ansible
ansible_password: "{{ vault_ios_password }}"
ansible_become: true
ansible_become_method: enable
ansible_become_password: "{{ vault_ios_enable_password }}"
```

## Pairing with ISE

The `internal.ise.ise_nads` inventory plugin (from `internal.ise`)
already sets `ansible_network_os: ios` on hosts whose ISE NDG
`device_type` is `Switch`. Drop that plugin's config in your
inventory tree and `internal.ios.collect` will run against every
switch ISE knows about.

## Layout

```
ncs-ansible-ios/
├── galaxy.yml
├── meta/runtime.yml
├── roles/ios/
│   ├── defaults/main.yaml
│   ├── meta/{main,argument_specs}.yaml
│   └── tasks/
│       ├── main.yaml
│       ├── collect.yaml
│       └── ops/{switchport_config,apply_template,change_syslog}.yaml
├── playbooks/
│   ├── collect.yml         # FQCN: internal.ios.collect
│   └── ios_ops.yml         # console-driven config ops (internal.ios.ios_ops)
├── ncs_configs/ios.yaml    # ncs-reporter schema
├── tests/inventory.example/
├── docs/
└── CHANGELOG.md
```

## Out of scope (v0.1.0)

- STIG audit / remediate.
- IOS-XE RESTCONF (`httpapi` connection) — operator can override per-host.
- Bulk switchport changes across many interfaces in one run.
- Template *definition* management (we apply templates; we don't author them).
- Cross-collection AAA verification against ISE PSN state.
