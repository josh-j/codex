# `community.vmware.vmware_host_acceptance`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_host_acceptance.py`

## Synopsis

Manage the host acceptance level of an ESXi host

This module can be used to manage the host acceptance level of an ESXi host.
The host acceptance level controls the acceptance level of each VIB on a ESXi host.

## Required parameters

**`state`**  *(str, required)*
  - If set to V(partner), then accept only partner and VMware signed and certified VIBs.
  - If set to V(vmware_certified), then accept only VIBs that are signed and certified by VMware.
  - If set to V(vmware_accepted), then accept VIBs that have been accepted by VMware.
  - If set to V(community), then accept all VIBs, even those that are not signed.
  - Choices: `community`, `partner`, `vmware_accepted`, `vmware_certified`

## Other parameters

**`cluster_name`**  *(str)*
  - Name of the cluster.
  - Acceptance level of all ESXi host system in the given cluster will be managed.
  - If O(esxi_hostname) is not given, this parameter is required.

**`esxi_hostname`**  *(str)*
  - ESXi hostname.
  - Acceptance level of this ESXi host system will be managed.
  - If O(cluster_name) is not given, this parameter is required.

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
- name: Set acceptance level to community for all ESXi Host in given Cluster
  community.vmware.vmware_host_acceptance:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    cluster_name: cluster_name
    state: 'community'
  delegate_to: localhost
  register: cluster_acceptance_level

- name: Set acceptance level to vmware_accepted for the given ESXi Host
  community.vmware.vmware_host_acceptance:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    state: 'vmware_accepted'
  delegate_to: localhost
  register: host_acceptance_level
```
