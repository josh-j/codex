# `community.vmware.vmware_vm_info`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_vm_info.py`

## Synopsis

Return basic info pertaining to a VMware machine guest

Return basic information pertaining to a vSphere or ESXi virtual machine guest.

## Used in this collection

- `roles/common/tasks/discover_vms.yaml:11`
- `roles/vcsa/tasks/collect.yaml:260`

## Other parameters

**`folder`**  *(str)*
  - Specify a folder location of VMs to gather information from.
  - Examples:
  -    folder: /ha-datacenter/vm
  -    folder: ha-datacenter/vm
  -    folder: /datacenter1/vm
  -    folder: datacenter1/vm
  -    folder: /datacenter1/vm/folder1
  -    folder: datacenter1/vm/folder1
  -    folder: /folder1/datacenter1/vm
  -    folder: folder1/datacenter1/vm
  -    folder: /folder1/datacenter1/vm/folder2

**`show_allocated`**  *(bool, default: `False`)*
  - Allocated storage in byte and memory in MB are shown if it set to True.

**`show_attribute`**  *(bool, default: `False`)*
  - Attributes related to VM guest shown in information only when this is set V(true).

**`show_cluster`**  *(bool, default: `True`)*
  - Tags virtual machine's cluster is shown if set to V(true).

**`show_datacenter`**  *(bool, default: `True`)*
  - Tags virtual machine's datacenter is shown if set to V(true).

**`show_datastore`**  *(bool, default: `True`)*
  - Tags virtual machine's datastore is shown if set to V(true).

**`show_esxi_hostname`**  *(bool, default: `True`)*
  - Tags virtual machine's ESXi host is shown if set to V(true).

**`show_folder`**  *(bool, default: `True`)*
  - Show folders

**`show_mac_address`**  *(bool, default: `True`)*
  - Tags virtual machine's mac address is shown if set to V(true).

**`show_net`**  *(bool, default: `True`)*
  - Tags virtual machine's network is shown if set to V(true).

**`show_resource_pool`**  *(bool, default: `True`)*
  - Tags virtual machine's resource pool is shown if set to V(true).

**`show_tag`**  *(bool, default: `False`)*
  - Tags related to virtual machine are shown if set to V(true).

**`vm_name`**  *(str)*
  - Name of the virtual machine to get related configurations information from.

**`vm_type`**  *(str, default: `all`)*
  - If set to V(vm), then information are gathered for virtual machines only.
  - If set to V(template), then information are gathered for virtual machine templates only.
  - If set to V(all), then information are gathered for all virtual machines and virtual machine templates.
  - Choices: `all`, `vm`, `template`

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
- name: Gather all registered virtual machines
  community.vmware.vmware_vm_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
  delegate_to: localhost
  register: vm_info

- debug:
    var: vm_info.virtual_machines

- name: Gather one specific VM
  community.vmware.vmware_vm_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    vm_name: 'vm_name_as_per_vcenter'
  delegate_to: localhost
  register: vm_info

- debug:
    var: vm_info.virtual_machines

- name: Gather only registered virtual machine templates
  community.vmware.vmware_vm_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    vm_type: template
  delegate_to: localhost
  register: template_info

- debug:
    var: template_info.virtual_machines

- name: Gather only registered virtual machines
  community.vmware.vmware_vm_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    vm_type: vm
  delegate_to: localhost
  register: vm_info

- debug:
    var: vm_info.virtual_machines

- name: Get UUID from given VM Name
  block:
    - name: Get virtual machine info
      community.vmware.vmware_vm_info:
        hostname: '{{ vcenter_hostname }}'
        username: '{{ vcenter_username }}'
        password: '{{ vcenter_password }}'
        folder: "/datacenter/vm/folder"
      delegate_to: localhost
      register: vm_info

    - debug:
        msg: "{{ item.uuid }}"
      with_items:
        - "{{ vm_info.virtual_machines | community.general.json_query(query) }}"
      vars:
        query: "[?guest_name=='DC0_H0_VM0']"

- name: Get Tags from given VM Name
  block:
    - name: Get virtual machine info
      community.vmware.vmware_vm_info:
        hostname: '{{ vcenter_hostname }}'
        username: '{{ vcenter_username }}'
        password: '{{ vcenter_password }}'
        folder: "/datacenter/vm/folder"
      delegate_to: localhost
      register: vm_info

    - debug:
        msg: "{{ item.tags }}"
      with_items:
        - "{{ vm_info.virtual_machines | community.general.json_query(query) }}"
      vars:
        query: "[?guest_name=='DC0_H0_VM0']"

- name: Gather all VMs from a specific folder
  community.vmware.vmware_vm_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    folder: "/Asia-Datacenter1/vm/prod"
  delegate_to: localhost
  register: vm_info

- name: Get datastore_url from given VM name
  block:
    - name: Get virtual machine info
      community.vmware.vmware_vm_info:
        hostname: '{{ vcenter_hostname }}'
        username: '{{ vcenter_username }}'
        password: '{{ vcenter_password }}'
      delegate_to: localhost
      register: vm_info

    - debug:
        msg: "{{ item.datastore_url }}"
      with_items:
        - "{{ vm_info.virtual_machines | community.general.json_query(query) }}"
      vars:
        query: "[?guest_name=='DC0_H0_VM0']"
```
