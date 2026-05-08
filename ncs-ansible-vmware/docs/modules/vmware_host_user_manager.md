# `community.vmware.vmware_host_user_manager`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_host_user_manager.py`

## Synopsis

Manage users of ESXi

This module can add, update or delete local users on ESXi host.

## Used in this collection

- `roles/esxi/tasks/maintain/password_rotate.yaml:20`

## Required parameters

**`esxi_hostname`**  *(str, required)*
  - Name of the ESXi host that is managing the local user.

**`user_name`**  *(str, required, aliases: `local_user_name`)*
  - Name of the local user.

## Other parameters

**`override_user_password`**  *(bool, default: `False`)*
  - If the local user exists and updates the password, change this parameter value is true.

**`state`**  *(str, default: `present`)*
  - If set to V(present), add a new local user or update information.
  - If set to V(absent), delete the local user.
  - Choices: `present`, `absent`

**`user_description`**  *(str, aliases: `local_user_description`)*
  - The local user description.

**`user_password`**  *(str, aliases: `local_user_password`)*
  - The local user password.
  - If you'd like to update the password, requires O(override_user_password=true).

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
- name: Add new local user to ESXi host
  community.vmware.vmware_host_user_manager:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    validate_certs: false
    esxi_hostname: "{{ esxi1 }}"
    user_name: example
    user_description: "example user"
    user_password: "{{ local_user_password }}"
    state: present

- name: Update the local user password in ESXi host
  community.vmware.vmware_host_user_manager:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    validate_certs: false
    esxi_hostname: "{{ esxi1 }}"
    user_name: example
    user_description: "example user"
    user_password: "{{ local_user_password }}"
    override_user_password: true
    state: present

- name: Delete the local user in ESXi host
  community.vmware.vmware_host_user_manager:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    validate_certs: false
    esxi_hostname: "{{ esxi1 }}"
    user_name: example
    state: absent
```
