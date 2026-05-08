# internal.ise

Cisco Identity Services Engine (ISE) collection for NCS audit and
automation workflows.

This collection wraps Cisco's upstream `cisco.ise` Ansible collection
with the local NCS dispatch and emission patterns. It depends on
`internal.core` for `internal.core.dispatch` and `internal.core.emit`,
and on `cisco.ise` for the actual ISE API modules.

## Installation

```bash
# from a built tarball
ansible-galaxy collection install internal-ise-<version>.tar.gz

# or via the app repo's requirements.yml manifest
ansible-galaxy collection install -r requirements.yml
```

The upstream Cisco collection and SDK are also required:

```bash
ansible-galaxy collection install cisco.ise
python -m pip install ciscoisesdk requests
```

## Usage

Playbooks ship under `playbooks/` and are invoked by FQCN:

```bash
ansible-playbook -i inventory/production internal.ise.ise_collect
ansible-playbook -i inventory/production internal.ise.ise_one_offs -e ncs_operation=endpoint_lookup -e ise_lookup=00:11:22:33:44:55
```

Required inventory variables for each ISE node:

- `ise_hostname`
- `ise_username`
- `ise_password`
- `ise_verify`
- `ise_version`

Prefer storing `ise_password` through Ansible Vault.

## Layout

```
ncs-ansible-ise/
├── ncs_configs/          # ncs-reporter schema for raw_ise.yaml
├── docs/                 # Cisco ISE Ansible/API reference material
├── galaxy.yml            # namespace/name/version + dependencies
├── meta/runtime.yml      # required ansible-core version
├── roles/ise/            # ISE role using cisco.ise modules
├── playbooks/            # flat filename convention: ise_collect.yml
├── tests/                # standalone lab inventory skeleton
├── plugins/              # optional future plugins
└── CHANGELOG.md
```

## Documentation

Start with `docs/README.md`. It links to the upstream Cisco ISE
Ansible collection, Cisco DevNet API reference, Ansible collection
docs, SDK requirements, compatibility notes, and the curated module
catalog for common ISE automation areas.

The reporter schema in `ncs_configs/ise.yaml` exposes ISE version,
node/device inventory counts, certificate expiry alerts, backup and
patch status, policy and TACACS inventory, identity source inventory,
session/authentication visibility, endpoint default-policy markers,
high repeat counters, randomized MAC detection, TrustSec object counts,
API failure alerts, and inventory/detail tables for the raw
`ise_collect` payload.

## Console One-Offs

`ise_one_offs.yml` ships ncs-console metadata profiles for common
operator lookups:

- Endpoint lookup by MAC, IP, hostname, or username
- Endpoint risk report for default policy markers, high repeat counters,
  and randomized MACs
- Switch/NAD lookup
- Endpoint report for a specific NAD and port
- User authentication history
- Failed authentication summary
- Endpoint CoA by MAC, IP, or hostname
- Endpoint timeline report
- Policy hit explorer for matched rules/profiles and policy objects
- NAD troubleshooting bundle with device match, active sessions, recent
  auths, failures, top failing ports, and CoA/ANC candidate context
- NAD port history with endpoint churn, first/last seen, failures, and
  chronological events
- Policy object detail drilldown across authz profiles, DACLs, allowed
  protocols, filter policies, and recent hits
- Endpoint ANC apply/clear by MAC, IP, or hostname

Endpoint CoA is marked mutating so ncs-console prompts before it runs.
It also requires `ise_coa_confirm=COA`.
Endpoint ANC is also mutating and requires `ise_anc_confirm=ANC`.
One-off runs write HTML and CSV artifacts under
`/srv/samba/reports/one_offs/ise/`; ncs-console opens the latest HTML
artifact when it sees the emitted `NCS_REPORT` marker.
