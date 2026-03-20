# internal.vmware.vcsa

Role for VCSA (vCenter Server Appliance) STIG compliance audits and hardening.

For vCenter inventory/health collection, use `internal.vmware.vcenter_collect` instead.

## Usage

```yaml
- name: VCSA STIG Audit
  hosts: vcenters
  roles:
    - role: internal.vmware.vcsa
      vars:
        vcsa_stig_enable_hardening: false
```

### STIG Modes

- **Audit mode** (`vcsa_stig_enable_hardening: false`, default): evaluates STIG controls in check mode
- **Hardening mode** (`vcsa_stig_enable_hardening: true`): applies STIG remediations

Optional Photon baseline execution can be enabled with `vcsa_stig_include_photon: true`.
