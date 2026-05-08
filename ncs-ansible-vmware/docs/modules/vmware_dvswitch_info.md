# `community.vmware.vmware_dvswitch_info`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_dvswitch_info.py`

## Synopsis

Gathers info dvswitch configurations

This module can be used to gather information about dvswitch configurations.

## Used in this collection

- `roles/vcsa/tasks/collect.yaml:93`

## Other parameters

**`folder`**  *(str)*
  - Specify a folder location of dvswitch to gather information from.
  - Examples:
  -    folder: /datacenter1/network
  -    folder: datacenter1/network
  -    folder: /datacenter1/network/folder1
  -    folder: datacenter1/network/folder1
  -    folder: /folder1/datacenter1/network
  -    folder: folder1/datacenter1/network
  -    folder: /folder1/datacenter1/network/folder2

**`properties`**  *(list)*
  - Specify the properties to retrieve.
  - If not specified, all properties are retrieved (deeply).
  - Results are returned in a structure identical to the vsphere API.
  - Example:
  -    properties: [
  -       "summary.name",
  -       "summary.numPorts",
  -       "config.maxMtu",
  -       "overallStatus"
  -    ]
  - Only valid when O(schema=vsphere).

**`schema`**  *(str, default: `summary`)*
  - Specify the output schema desired.
  - The 'summary' output schema is the legacy output from the module
  - The 'vsphere' output schema is the vSphere API class definition
  - Choices: `summary`, `vsphere`

**`switch_name`**  *(str, aliases: `switch`, `dvswitch`)*
  - Name of a dvswitch to look for.
  - If O(switch_name) not specified gather all dvswitch information.

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
- name: Gather all registered dvswitch
  community.vmware.vmware_dvswitch_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
  delegate_to: localhost
  register: dvswitch_info

- name: Gather info about specific dvswitch
  community.vmware.vmware_dvswitch_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    switch_name: DVSwitch01
  delegate_to: localhost
  register: dvswitch_info

- name: Gather info from folder about specific dvswitch
  community.vmware.vmware_dvswitch_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    folder: /datacenter1/network/F01
    switch_name: DVSwitch02
  delegate_to: localhost
  register: dvswitch_info

- name: Gather some info from a dvswitch using the vSphere API output schema
  community.vmware.vmware_dvswitch_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    schema: vsphere
    properties:
      - summary.name
      - summary.numPorts
      - config.maxMtu
      - overallStatus
    switch_name: DVSwitch01
  register: dvswitch_info
```
