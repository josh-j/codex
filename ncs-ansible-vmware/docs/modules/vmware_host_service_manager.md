# `community.vmware.vmware_host_service_manager`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_host_service_manager.py`

## Synopsis

Manage services on a given ESXi host

This module can be used to manage (start, stop, restart) services on a given ESXi host.
If cluster_name is provided, specified service will be managed on all ESXi host belonging to that cluster.
If specific esxi_hostname is provided, then specified service will be managed on given ESXi host only.

## Used in this collection

- `roles/esxi/tasks/stig_v7r4/30_other_modules.yaml:16`
- `roles/esxi/tasks/stig_v7r4/90_post_stig.yaml:7`

## Required parameters

**`service_name`**  *(str, required)*
  - Name of Service to be managed. This is a brief identifier for the service, for example, ntpd, vxsyslogd etc.
  - This value should be a valid ESXi service name.

## Other parameters

**`cluster_name`**  *(str)*
  - Name of the cluster.
  - Service settings are applied to every ESXi host system/s in given cluster.
  - If O(esxi_hostname) is not given, this parameter is required.

**`esxi_hostname`**  *(str)*
  - ESXi hostname.
  - Service settings are applied to this ESXi host system.
  - If O(cluster_name) is not given, this parameter is required.

**`service_policy`**  *(str)*
  - Set of valid service policy strings.
  - If set V(on), then service should be started when the host starts up.
  - If set V(automatic), then service should run if and only if it has open firewall ports.
  - If set V(off), then Service should not be started when the host starts up.
  - Choices: `automatic`, `off`, `on`

**`state`**  *(str, default: `start`)*
  - Desired state of service.
  - V(start) and V(present) has same effect.
  - V(stop) and V(absent) has same effect.
  - V(unchanged) allows defining O(service_policy) without defining or changing service state.
  - Choices: `absent`, `present`, `restart`, `start`, `stop`, `unchanged`

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
- name: Start ntpd service setting for all ESXi Host in given Cluster
  community.vmware.vmware_host_service_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    cluster_name: '{{ cluster_name }}'
    service_name: ntpd
    state: present
  delegate_to: localhost

- name: Start ntpd setting for an ESXi Host
  community.vmware.vmware_host_service_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    service_name: ntpd
    state: present
  delegate_to: localhost

- name: Start ntpd setting for an ESXi Host with Service policy
  community.vmware.vmware_host_service_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    service_name: ntpd
    service_policy: 'on'
    state: present
  delegate_to: localhost

- name: Stop ntpd setting for an ESXi Host
  community.vmware.vmware_host_service_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    service_name: ntpd
    state: absent
  delegate_to: localhost
```
