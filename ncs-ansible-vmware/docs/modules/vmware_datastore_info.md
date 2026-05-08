# `community.vmware.vmware_datastore_info`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_datastore_info.py`

## Synopsis

Gather info about datastores available in given vCenter

This module can be used to gather information about datastores in VMWare infrastructure.

## Used in this collection

- `roles/esxi/tasks/collect.yaml:50`
- `roles/vcsa/tasks/collect.yaml:68`

## Other parameters

**`cluster`**  *(str)*
  - Cluster to search for datastores.
  - If set, information of datastores belonging this clusters will be returned.
  - This parameter is required, if O(datacenter) is not supplied.

**`datacenter`**  *(str, aliases: `datacenter_name`)*
  - Datacenter to search for datastores.
  - This parameter is required, if O(cluster) is not supplied.

**`gather_nfs_mount_info`**  *(bool, default: `False`)*
  - Gather mount information of NFS datastores.
  - Disabled per default because this slows down the execution if you have a lot of datastores.
  - Only valid when O(schema=summary).

**`gather_vmfs_mount_info`**  *(bool, default: `False`)*
  - Gather mount information of VMFS datastores.
  - Disabled per default because this slows down the execution if you have a lot of datastores.
  - Only valid when O(schema=summary).

**`name`**  *(str)*
  - Name of the datastore to match.
  - If set, information of specific datastores are returned.

**`properties`**  *(list)*
  - Specify the properties to retrieve.
  - If not specified, all properties are retrieved (deeply).
  - Results are returned in a structure identical to the vsphere API.
  - Example:
  -    properties: [
  -       "name",
  -       "info.vmfs.ssd",
  -       "capability.vsanSparseSupported",
  -       "overallStatus"
  -    ]
  - Only valid when O(schema=vsphere).

**`schema`**  *(str, default: `summary`)*
  - Specify the output schema desired.
  - The 'summary' output schema is the legacy output from the module
  - The 'vsphere' output schema is the vSphere API class definition
  - Choices: `summary`, `vsphere`

**`show_tag`**  *(bool, default: `False`)*
  - Tags related to Datastore are shown if set to V(true).

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
- name: Gather info from standalone ESXi server having datacenter as 'ha-datacenter'
  community.vmware.vmware_datastore_info:
    hostname: '{{ esxi_hostname }}'
    username: '{{ esxi_username }}'
    password: '{{ esxi_password }}'
    datacenter_name: "ha-datacenter"
  delegate_to: localhost
  register: info

- name: Gather info from datacenter about specific datastore
  community.vmware.vmware_datastore_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: '{{ datacenter_name }}'
    name: datastore1
  delegate_to: localhost
  register: info

- name: Gather some info from a datastore using the vSphere API output schema
  community.vmware.vmware_datastore_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: '{{ datacenter_name }}'
    schema: vsphere
    properties:
      - name
      - info.vmfs.ssd
      - capability.vsanSparseSupported
      - overallStatus
  delegate_to: localhost
  register: info
```
