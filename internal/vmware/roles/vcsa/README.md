# internal.vmware.vcsa

Role for vCenter appliance health collection and VCSA STIG compliance audits/hardening.

## Usage

### Collection

```yaml
- name: vCenter health audit
  hosts: vcenters
  roles:
    - role: internal.vmware.vcsa
      vars:
        ncs_action: collect
```

### STIG Modes

```yaml
- name: VCSA STIG Audit
  hosts: vcenters
  roles:
    - role: internal.vmware.vcsa
      vars:
        vcsa_stig_enable_hardening: false
```

- **Audit mode** (`vcsa_stig_enable_hardening: false`, default): evaluates STIG controls in check mode
- **Hardening mode** (`vcsa_stig_enable_hardening: true`): applies STIG remediations

Optional Photon baseline execution can be enabled with `vcsa_stig_include_photon: true`.
