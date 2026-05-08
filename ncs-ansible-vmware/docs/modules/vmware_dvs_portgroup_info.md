# `community.vmware.vmware_dvs_portgroup_info`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_dvs_portgroup_info.py`

## Synopsis

Gathers info DVS portgroup configurations

This module can be used to gather information about DVS portgroup configurations.

## Used in this collection

- `roles/vcsa/tasks/collect.yaml:102`

## Required parameters

**`datacenter`**  *(str, required)*
  - Name of the datacenter.

## Other parameters

**`dvswitch`**  *(str)*
  - Name of a dvswitch to look for.

**`show_mac_learning`**  *(bool, default: `True`)*
  - Show or hide MAC learning information of the DVS portgroup.

**`show_network_policy`**  *(bool, default: `True`)*
  - Show or hide network policies of DVS portgroup.

**`show_port_policy`**  *(bool, default: `True`)*
  - Show or hide port policies of DVS portgroup.

**`show_teaming_policy`**  *(bool, default: `True`)*
  - Show or hide teaming policies of DVS portgroup.

**`show_uplinks`**  *(bool, default: `True`)*
  - Show or hide uplinks of DVS portgroup.

**`show_vlan_info`**  *(bool, default: `False`)*
  - Show or hide vlan information of the DVS portgroup.

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
- name: Get info about DVPG
  community.vmware.vmware_dvs_portgroup_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    datacenter: "{{ datacenter_name }}"
  register: dvpg_info

- name: Get number of ports for portgroup 'dvpg_001' in 'dvs_001'
  debug:
    msg: "{{ item.num_ports }}"
  with_items:
    - "{{ dvpg_info.dvs_portgroup_info['dvs_001'] | json_query(query) }}"
  vars:
    query: "[?portgroup_name=='dvpg_001']"
```
