# `community.vmware.vmware_host_ntp`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_host_ntp.py`

## Synopsis

Manage NTP server configuration of an ESXi host

This module can be used to configure, add or remove NTP servers from an ESXi host.
If O(state) is not given, the NTP servers will be configured in the exact sequence.
User can specify an ESXi hostname or Cluster name. In case of cluster name, all ESXi hosts are updated.

## Required parameters

**`ntp_servers`**  *(list, required)*
  - IP or FQDN of NTP server(s).
  - This accepts a list of NTP servers. For multiple servers, please look at the examples.

## Other parameters

**`cluster_name`**  *(str)*
  - Name of the cluster from which all host systems will be used.
  - This parameter is required if O(esxi_hostname) is not specified.

**`esxi_hostname`**  *(str)*
  - Name of the host system to work with.
  - This parameter is required if O(cluster_name) is not specified.

**`state`**  *(str)*
  - V(present): Add NTP server(s), if specified server(s) are absent else do nothing.
  - V(absent): Remove NTP server(s), if specified server(s) are present else do nothing.
  - Specified NTP server(s) will be configured if O(state) isn't specified.
  - Choices: `present`, `absent`

**`verbose`**  *(bool, default: `False`)*
  - Verbose output of the configuration change.
  - Explains if an NTP server was added, removed, or if the NTP server sequence was changed.

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
- name: Configure NTP servers for an ESXi Host
  community.vmware.vmware_host_ntp:
    hostname: vcenter01.example.local
    username: administrator@vsphere.local
    password: SuperSecretPassword
    esxi_hostname: esx01.example.local
    ntp_servers:
        - 0.pool.ntp.org
        - 1.pool.ntp.org
  delegate_to: localhost

- name: Set NTP servers for all ESXi Host in given Cluster
  community.vmware.vmware_host_ntp:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    cluster_name: '{{ cluster_name }}'
    state: present
    ntp_servers:
        - 0.pool.ntp.org
        - 1.pool.ntp.org
  delegate_to: localhost

- name: Set NTP servers for an ESXi Host
  community.vmware.vmware_host_ntp:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    state: present
    ntp_servers:
        - 0.pool.ntp.org
        - 1.pool.ntp.org
  delegate_to: localhost

- name: Remove NTP servers for an ESXi Host
  community.vmware.vmware_host_ntp:
    hostname: '{{ vcenter_hostname }}'
    username: '{{ vcenter_username }}'
    password: '{{ vcenter_password }}'
    esxi_hostname: '{{ esxi_hostname }}'
    state: absent
    ntp_servers:
        - bad.server.ntp.org
  delegate_to: localhost
```
