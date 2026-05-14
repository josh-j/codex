# Changelog — internal.ios

## 0.2.2

- `galaxy.yml` `dependencies:` now declares `ansible.netcommon
  (>=6.0.0)` and `cisco.ios (>=5.0.0)`. They're not vendored in the
  umbrella — the framework's `requirements.yml` only carries the
  in-house `internal.*` tarballs — but the declaration means
  `ansible-galaxy collection install internal.ios` from Galaxy
  resolves them automatically.
- New `ncs-ansible/requirements-network.yml` is the operator entry
  point for the same two deps; `just install-network-collections`
  runs `ansible-galaxy collection install -r requirements-network.yml`.
  Separate from the umbrella's primary `requirements.yml` so the
  "locally-resolved only" promise of the main file stays intact.
- `docs/QUICKSTART.md` covers both the connected install path
  (`just install-network-collections`) and the airgapped path
  (pre-download via `ansible-galaxy collection download` on a
  connected machine, scp, install from local tarballs).

## 0.2.1

- Drop `internal.core.dispatch` and `internal.core.emit` from
  `roles/ios/meta/main.yaml` `dependencies:`. They're already invoked
  explicitly via `include_role:` from `tasks/main.yaml` (and from
  each op task) with the per-call `vars:` block carrying
  `_ncs_role_label`, `_dispatch_map`, etc. Listing them as meta deps
  caused Ansible to auto-load `internal.core.dispatch` at role-include
  time *before* the IOS role's tasks ran — so every dispatch task
  name templating `{{ _ncs_role_label }}` rendered as
  `<< error: _ncs_role_label is undefined >>`. The play continued
  past the warnings (the dep invocation didn't actually run anything),
  but the noise was a smell.

## 0.2.0

- New `switchport_config_bulk` operation: same effect as
  `switchport_config` but takes a list of interface changes in one
  console run. Operator pastes a YAML / JSON array via the
  `ios_switchports` field, e.g.
  `[{interface: Gi1/0/10, access_vlan: 20}, {interface: Gi1/0/11, voice_vlan: 30, description: 'printer'}]`.
  The role hands the whole list to `cisco.ios.ios_l2_interfaces` and
  `cisco.ios.ios_interfaces` in one task each — both modules
  natively accept a config list, so the wire push is one minimal
  diff per resource rather than N independent merges.
- ncs-console annotation block updated; `Switchport Config (Bulk)`
  surfaces alongside the existing three operations.

## 0.1.0

- Initial collection. Cisco IOS / IOS-XE over `network_cli` (SSH).
- `internal.ios.collect` — baseline collect via `cisco.ios.ios_facts` +
  a small set of show-commands. Emits `raw_ios.yaml` for ncs-reporter
  under tree path `ios/<hostname>/`.
- `internal.ios.ios_ops` — three operator-driven config operations,
  each surfaced as its own ncs-console button via `# >>>` annotation:
  - `switchport_config` — set access vlan / voice vlan / description /
    shutdown state on one interface (uses
    `cisco.ios.ios_l2_interfaces` and `cisco.ios.ios_interfaces`).
  - `apply_template` — bind an IOS-XE port-template to an interface
    (`source template <name>`, via `cisco.ios.ios_config`).
  - `change_syslog` — replace one `logging host <ip>` with a new IP,
    optional VRF.
- Reporter schema at `ncs_configs/ios.yaml` (`platform: network/ios`):
  stat-cards for version / model / serial / interfaces, AAA + syslog
  detail tables, alerts for missing AAA / missing syslog.
- One unified `roles/ios/` covers both classic IOS and IOS-XE; per-host
  divergence handled via `ansible_facts.net_iostype` / `net_version`.
