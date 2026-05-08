# `vmware.vmware.vcsa_backup_schedule_info`

**Collection:** `vmware.vmware` v2.8.0  
**Source:** `vmware/vmware/plugins/modules/vcsa_backup_schedule_info.py`

## Synopsis

Gather info about one or more VCSA backup schedules.

Gather info about vCenter server appliance backup schedules.
If a name is provided, only the schedule with that name will be included in the output.

## Used in this collection

- `roles/vcsa/tasks/collect.yaml:246`

## Other parameters

**`name`**  *(str)*
  - The name of the backup schedule for which to gather info.
  - If no name is provided, all backup schedules are returned.

**`proxy_protocol`**  *(str, default: `https`, aliases: `protocol`)*
  - The proxy connection protocol to use.
  - This option is used if the correct proxy protocol cannot be automatically determined.
  - Choices: `http`, `https`

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
- name: Gather All Backup Schedules Info
  vmware.vmware.vcsa_backup_schedule_info: {}

- name: Gather The Default Schedule Info
  vmware.vmware.vcsa_backup_schedule_info:
    name: default
```
