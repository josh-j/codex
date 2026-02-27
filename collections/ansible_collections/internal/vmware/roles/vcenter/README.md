# internal.vmware.vcenter

Role for interacting with vCenter instances via API to collect inventory and health data.

## Actions

Specify the action via the `vcenter_action` variable.

### `collect` (Default)
Performs deep discovery of clusters, hosts, datastores, VMs, and alarms.
- **Handoff:** Emits raw telemetry via `ansible.builtin.set_stats` (intercepted by `ncs_collector` plugin).
- **Idiomatic:** Uses `module_defaults` for centralized credential management.


## Usage

```yaml
- name: Collect vCenter State
  hosts: vcenters
  roles:
    - role: internal.vmware.vcenter
      vars:
        vcenter_action: collect
```
