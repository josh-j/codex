# `vmware.vmware.cluster_info`

**Collection:** `vmware.vmware` v2.8.0  
**Source:** `vmware/vmware/plugins/modules/cluster_info.py`

## Synopsis

Gathers information about one or more clusters

Gathers information about one or more clusters. You can search for clusters based on the cluster name, datacenter name, or a combination of the two.

## Used in this collection

- `playbooks/esxi_refresh_inventory.yml:33`
- `roles/common/tasks/discover_esxi.yaml:24`
- `roles/esxi/tasks/collect.yaml:37`
- `roles/vcsa/tasks/collect.yaml:55`

## Other parameters

**`cluster`**  *(str, aliases: `cluster_name`, `name`)*
  - The name of the cluster on which to gather info.
  - At least one of O(datacenter) or O(cluster) is required.

**`datacenter`**  *(str, aliases: `datacenter_name`)*
  - The name of the datacenter.
  - At least one of O(datacenter) or O(cluster) is required.

**`gather_tags`**  *(bool, default: `False`)*
  - If true, gather any tags attached to the cluster(s)
  - This has no affect if the O(schema) is set to V(vsphere). In that case, add 'tag' to O(properties) or leave O(properties) unset.

**`properties`**  *(list)*
  - If the schema is 'vsphere', gather these specific properties only

**`proxy_protocol`**  *(str, default: `https`, aliases: `protocol`)*
  - The proxy connection protocol to use.
  - This option is used if the correct proxy protocol cannot be automatically determined.
  - Choices: `http`, `https`

**`schema`**  *(str, default: `summary`)*
  - Specify the output schema desired.
  - The V(summary) output schema is the legacy output from the module.
  - The V(vsphere) output schema is the vSphere API class definition.
  - Choices: `summary`, `vsphere`

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
- name: Gather Cluster Information
  vmware.vmware.cluster_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: datacenter
    cluster_name: my_cluster
  register: _out

- name: Gather Information About All Clusters In a Datacenter
  vmware.vmware.cluster_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    datacenter_name: datacenter
  register: _out

- name: Gather Specific Properties About a Cluster
  vmware.vmware.cluster_info:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    cluster_name: my_cluster
    schema: vsphere
    properties:
      - name
      - configuration.dasConfig.enabled
      - summary.totalCpu
  register: _out
```
