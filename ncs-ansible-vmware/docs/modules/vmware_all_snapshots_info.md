# `community.vmware.vmware_all_snapshots_info`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_all_snapshots_info.py`

## Synopsis

Gathers information about all snapshots across virtual machines in a specified vmware datacenter

This module collects detailed information of all the snapshots of the datacenter, can be used with filter options

## Used in this collection

- `roles/vcsa/tasks/collect.yaml:308`

## Required parameters

**`datacenter`**  *(str, required)*
  - The name of the datacenter to gather snapshot information from. You can get it in the vmware UI.

## Other parameters

**`filters`**  *(dict, default: `{}`)*
  - Optional filters to apply to the snapshot data being gathered, you can apply one or more.
  - Filters are applied based on the variable match_type specified. If match_type exact, filters require exact matches.
  - On the other hand when match_type includes it gets the values that contain that value.
  - Available filter options creation_time, description, folder, id, name, quiesced, state, vm_name.
  - Multiple filters can be applied the snapshot must meet all filter criteria to be included in the results.

**`match_type`**  *(str, default: `exact`)*
  - Indicates whether the filter match should be exact or includes.
  - For example when you want to get all the snapshots that contain in their name the word test you place the filter name test and the match_type includes.
  - For example when you want to get all snapshots that are in state poweredOn you skip the match_type default is exact  or you write match_type exact.
  - Choices: `exact`, `includes`

## Connection parameters

These come from the role's `module_defaults` block (sourced from `_vmware_creds`); operators do not set them per-task.

**`hostname`**  *(str)*
  - The hostname or IP address of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_HOST) will be used instead.

**`password`**  *(str, aliases: `pass`, `pwd`)*
  - The password of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PASSWORD) will be used instead.

**`port`**  *(int, default: `443`)*
  - The port number of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PORT) will be used instead.

**`proxy_host`**  *(str)*
  - The address of a proxy that will receive all HTTPS requests and relay them.
  - The format is a hostname or a IP.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PROXY_HOST) will be used instead.

**`proxy_port`**  *(int)*
  - The port of the HTTP proxy that will receive all HTTPS requests and relay them.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PROXY_PORT) will be used instead.

**`username`**  *(str, aliases: `admin`, `user`)*
  - The username of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_USER) will be used instead.

**`validate_certs`**  *(bool, default: `True`)*
  - Allows connection when SSL certificates are not valid. Set to V(false) when certificates are not trusted.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_VALIDATE_CERTS) will be used instead.

## Notes

- All modules require API write access and hence are not supported on a free ESXi license.
- All variables and VMware object names are case sensitive.
- Modules may rely on the 'requests' python library, which does not use the system certificate store by default. You can specify the certificate store by setting the REQUESTS_CA_BUNDLE environment variable. Note having this variable set may cause a 'false' value for the 'validate_certs' option to be ignored in some cases. Example: 'export REQUESTS_CA_BUNDLE=/path/to/your/ca_bundle.pem'

## Examples

```yaml
- name: Gather information about all snapshots in VMware vCenter
    vmware_all_snapshots_info:
      hostname: '{{ vcenter_hostname }}'
      username: '{{ vcenter_username }}'
      password: '{{ vcenter_password }}'
      validate_certs: no
      datacenter: '{{ datacenter_name }}'
    delegate_to: localhost
  - name: Gather information of a snapshot with filters applied and match_type in exacts.
    vmware_all_snapshots_info:
      hostname: '{{ vcenter_hostname }}'
      username: '{{ vcenter_username }}'
      password: '{{ vcenter_password }}'
      validate_certs: yes
      datacenter: '{{ datacenter_name }}'
      filters:
        state: "poweredOn"
        vm_name: "you_marchine_name"
    delegate_to: localhost
  - name: Gather information of snapshots that in their name contain the "test" in their name.
    vmware_all_snapshots_info:
      hostname: '{{ vcenter_hostname }}'
      username: '{{ vcenter_username }}'
      password: '{{ vcenter_password }}'
      validate_certs: yes
      datacenter: '{{ datacenter_name }}'
      match_type: "includes"
      filters:
        name: "test"
    delegate_to: localhost
```
