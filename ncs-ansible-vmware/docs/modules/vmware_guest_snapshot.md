# `community.vmware.vmware_guest_snapshot`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_guest_snapshot.py`

## Synopsis

Manages virtual machines snapshots in vCenter

This module can be used to create, delete and update snapshot(s) of the given virtual machine.

## Used in this collection

- `roles/vm/tasks/maintain/snapshot.yaml:14`

## Required parameters

**`datacenter`**  *(str, required)*
  - Destination datacenter for the deploy operation.

## Other parameters

**`description`**  *(str)*
  - Define an arbitrary description to attach to snapshot.

**`folder`**  *(str)*
  - Destination folder, absolute or relative path to find an existing guest.
  - This is required parameter, if O(name) is supplied.
  - The folder should include the datacenter. ESX's datacenter is ha-datacenter.
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

**`memory_dump`**  *(bool, default: `False`)*
  - If set to V(true), memory dump of virtual machine is also included in snapshot.
  - Note that memory snapshots take time and resources, this will take longer time to create.
  - If virtual machine does not provide capability to take memory snapshot, then this flag is set to V(false).

**`moid`**  *(str)*
  - Managed Object ID of the instance to manage if known, this is a unique identifier only within a single vCenter instance.
  - This is required if O(name) or O(uuid) is not supplied.

**`name`**  *(str)*
  - Name of the virtual machine to work with.
  - This is required parameter, if O(uuid) or O(moid) is not supplied.

**`name_match`**  *(str, default: `first`)*
  - If multiple VMs matching the name, use the first or last found.
  - Choices: `first`, `last`

**`new_description`**  *(str)*
  - Value to change the description of an existing snapshot to.

**`new_snapshot_name`**  *(str)*
  - Value to rename the existing snapshot to.

**`quiesce`**  *(bool, default: `False`)*
  - If set to V(true) and virtual machine is powered on, it will quiesce the file system in virtual machine.
  - Note that VMware Tools are required for this flag.
  - If virtual machine is powered off or VMware Tools are not available, then this flag is set to V(false).
  - If virtual machine does not provide capability to take quiesce snapshot, then this flag is set to V(false).

**`remove_children`**  *(bool, default: `False`)*
  - If set to V(true) and O(state=absent), then entire snapshot subtree is set for removal.

**`snapshot_id`**  *(int)*
  - Sets the snapshot id to manage.
  - This param is available when O(state=absent) or O(state=revert).

**`snapshot_name`**  *(str)*
  - Sets the snapshot name to manage.
  - This param or O(snapshot_id) is required only if O(state) is not C(remove_all)

**`state`**  *(str, default: `present`)*
  - Manage snapshot(s) attached to a specific virtual machine.
  - If set to V(present) and snapshot absent, then will create a new snapshot with the given name.
  - If set to V(present) and snapshot present, then no changes are made.
  - If set to V(absent) and snapshot present, then snapshot with the given name is removed.
  - If set to V(absent) and snapshot absent, then no changes are made.
  - If set to V(revert) and snapshot present, then virtual machine state is reverted to the given snapshot.
  - If set to V(revert) and snapshot absent, then no changes are made.
  - If set to V(remove_all) and snapshot(s) present, then all snapshot(s) will be removed.
  - If set to V(remove_all) and snapshot(s) absent, then no changes are made.
  - Choices: `present`, `absent`, `revert`, `remove_all`

**`use_instance_uuid`**  *(bool, default: `False`)*
  - Whether to use the VMware instance UUID rather than the BIOS UUID.

**`uuid`**  *(str)*
  - UUID of the instance to manage if known, this is VMware's BIOS UUID by default.
  - This is required if O(name) or O(moid) parameter is not supplied.

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
- name: Create a snapshot
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: present
      snapshot_name: snap1
      description: snap1_description
    delegate_to: localhost

  - name: Remove a snapshot
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: absent
      snapshot_name: snap1
    delegate_to: localhost

  - name: Revert to a snapshot
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: revert
      snapshot_name: snap1
    delegate_to: localhost

  - name: Remove all snapshots of a VM
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: remove_all
    delegate_to: localhost

  - name: Remove all snapshots of a VM using MoID
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      moid: vm-42
      state: remove_all
    delegate_to: localhost

  - name: Take snapshot of a VM using quiesce and memory flag on
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: present
      snapshot_name: dummy_vm_snap_0001
      quiesce: true
      memory_dump: true
    delegate_to: localhost

  - name: Remove a snapshot and snapshot subtree
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: absent
      remove_children: true
      snapshot_name: snap1
    delegate_to: localhost

  - name: Remove a snapshot with a snapshot id
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      snapshot_id: 10
      state: absent
    delegate_to: localhost

  - name: Rename a snapshot
    community.vmware.vmware_guest_snapshot:
      hostname: "{{ vcenter_hostname }}"
      username: "{{ vcenter_username }}"
      password: "{{ vcenter_password }}"
      datacenter: "{{ datacenter_name }}"
      folder: "/{{ datacenter_name }}/vm/"
      name: "{{ guest_name }}"
      state: present
      snapshot_name: current_snap_name
      new_snapshot_name: im_renamed
      new_description: "{{ new_snapshot_description }}"
    delegate_to: localhost
```
