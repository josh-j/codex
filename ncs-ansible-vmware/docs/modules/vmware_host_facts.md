# `community.vmware.vmware_host_facts`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_host_facts.py`

## Synopsis

Gathers facts about remote ESXi hostsystem

This module can be used to gathers facts like CPU, memory, datastore, network and system etc. about ESXi host system.
Please specify hostname or IP address of ESXi host system as O(hostname).
If hostname or IP address of vCenter is provided as O(hostname) and O(esxi_hostname) is not specified, then the module will throw an error.
Please note that when ESXi host connection state is not C(connected), facts returned from vCenter might be stale. Users are recommended to check connection state value and take appropriate decision in the playbook.

## Used in this collection

- `roles/esxi/tasks/collect.yaml:93`

## Other parameters

**`esxi_hostname`**  *(str)*
  - ESXi hostname.
  - Host facts about the specified ESXi server will be returned.
  - By specifying this option, you can select which ESXi hostsystem is returned if connecting to a vCenter.

**`properties`**  *(list)*
  - Specify the properties to retrieve.
  - If not specified, all properties are retrieved (deeply).
  - Results are returned in a structure identical to the vsphere API.
  - Example:
  -    properties: [
  -       "hardware.memorySize",
  -       "hardware.cpuInfo.numCpuCores",
  -       "config.product.apiVersion",
  -       "overallStatus"
  -    ]
  - Only valid when O(schema=vsphere).

**`schema`**  *(str, default: `summary`)*
  - Specify the output schema desired.
  - The V(summary) output schema is the legacy output from the module
  - The V(vsphere) output schema is the vSphere API class definition
  - Choices: `summary`, `vsphere`

**`show_datacenter`**  *(bool, default: `False`)*
  - Return the related Datacenter if set to V(true).

**`show_tag`**  *(bool, default: `False`)*
  - Tags related to Host are shown if set to V(true).

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
- name: Gather vmware host facts
  community.vmware.vmware_host_facts:
    hostname: "{{ esxi_server }}"
    username: "{{ esxi_username }}"
    password: "{{ esxi_password }}"
  register: host_facts
  delegate_to: localhost

- name: Gather vmware host facts from vCenter
  community.vmware.vmware_host_facts:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    esxi_hostname: "{{ esxi_hostname }}"
  register: host_facts
  delegate_to: localhost

- name: Gather vmware host facts from vCenter with tag information
  community.vmware.vmware_host_facts:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    esxi_hostname: "{{ esxi_hostname }}"
    show_tag: true
  register: host_facts_tag
  delegate_to: localhost

- name: Get VSAN Cluster UUID from host facts
  community.vmware.vmware_host_facts:
    hostname: "{{ esxi_server }}"
    username: "{{ esxi_username }}"
    password: "{{ esxi_password }}"
  register: host_facts
- set_fact:
    cluster_uuid: "{{ host_facts['ansible_facts']['vsan_cluster_uuid'] }}"

- name: Gather some info from a host using the vSphere API output schema
  community.vmware.vmware_host_facts:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    esxi_hostname: "{{ esxi_hostname }}"
    schema: vsphere
    properties:
      - hardware.memorySize
      - hardware.cpuInfo.numCpuCores
      - config.product.apiVersion
      - overallStatus
  register: host_facts

- name: Gather information about powerstate and connection state
  community.vmware.vmware_host_facts:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    esxi_hostname: "{{ esxi_hostname }}"
    schema: vsphere
    properties:
      - runtime.connectionState
      - runtime.powerState

- name: How to retrieve Product, Version, Build, Update info for ESXi from vCenter
  block:
    - name: Gather product version info for ESXi from vCenter
      community.vmware.vmware_host_facts:
        hostname: "{{ vcenter_hostname }}"
        username: "{{ vcenter_username }}"
        password: "{{ vcenter_password }}"
        esxi_hostname: "{{ esxi_hostname }}"
        schema: vsphere
        properties:
          - config.product
          - config.option
      register: gather_host_facts_result

    - name: Extract update level info from option properties
      set_fact:
        update_level_info: "{{ item.value }}"
      loop: "{{ gather_host_facts_result.ansible_facts.config.option }}"
      when:
        - item.key == 'Misc.HostAgentUpdateLevel'

    - name: The output of Product, Version, Build, Update info for ESXi
      debug:
        msg:
          - "Product : {{ gather_host_facts_result.ansible_facts.config.product.name }}"
          - "Version : {{ gather_host_facts_result.ansible_facts.config.product.version }}"
          - "Build   : {{ gather_host_facts_result.ansible_facts.config.product.build }}"
          - "Update  : {{ update_level_info }}"
```
