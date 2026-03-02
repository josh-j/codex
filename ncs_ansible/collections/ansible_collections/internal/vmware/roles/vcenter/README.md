# internal.vmware.vcenter

Role for interacting with vCenter instances via API to collect inventory and health data.

## Actions

Specify the action via the `vcenter_action` variable.

### `collect` (Default)
Performs deep discovery of clusters, hosts, datastores, VMs, and alarms.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats` (intercepted by `ncs_collector` plugin).
- **Idiomatic:** Uses `module_defaults` for centralized credential management.

### `stig`
Executes VCSA STIG service-role controls (v1r4 profile, vSphere 7.0) in either:
- audit mode (`vmware_stig_enable_hardening: false`, forced check mode)
- hardening mode (`vmware_stig_enable_hardening: true`)

Optional Photon baseline execution can be enabled with `vcenter_stig_include_photon: true`.


## Usage

```yaml
- name: Collect vCenter State
  hosts: vcenters
  roles:
    - role: internal.vmware.vcenter
      vars:
        vcenter_action: collect
```
