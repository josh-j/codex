# `community.vmware.vmware_host_config_manager`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_host_config_manager.py`

## Synopsis

Manage advanced system settings of an ESXi host

This module can be used to manage advanced system settings of an ESXi host when ESXi hostname or Cluster name is given.

## Other parameters

**`cluster_name`**  *(str)*
  - Name of the cluster.
  - Settings are applied to every ESXi host in given cluster.
  - If O(esxi_hostname) is not given, this parameter is required.

**`esxi_hostname`**  *(str)*
  - ESXi hostname.
  - Settings are applied to this ESXi host.
  - If O(cluster_name) is not given, this parameter is required.

**`options`**  *(dict, default: `{}`)*
  - A dictionary of advanced system settings.
  - Invalid options will cause module to error.
  - Note that the list of advanced options (with description and values) can be found by running `vim-cmd hostsvc/advopt/options`.

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
- name: Manage Log level setting for all ESXi hosts in given Cluster
  community.vmware.vmware_host_config_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    cluster_name: cluster_name
    options:
        'Config.HostAgent.log.level': 'info'
  delegate_to: localhost

- name: Manage Log level setting for an ESXi host
  community.vmware.vmware_host_config_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    options:
        'Config.HostAgent.log.level': 'verbose'
  delegate_to: localhost

- name: Manage multiple settings for an ESXi host
  community.vmware.vmware_host_config_manager:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    options:
        'Config.HostAgent.log.level': 'verbose'
        'Annotations.WelcomeMessage': 'Hello World'
        'Config.HostAgent.plugins.solo.enableMob': false
  delegate_to: localhost
```
