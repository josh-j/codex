# VMware module reference

Hardcopy reference for every external VMware module invoked from this collection's roles or playbooks. Generated from `ansible-doc --json` against the pinned vendored collection versions.

## Versions

- `community.vmware` v6.2.0
- `vmware.vmware` v2.8.0

## Connection parameters

All modules listed here read `hostname` / `username` / `password` / `validate_certs` from the role's `module_defaults` block, which sources them from `_vmware_creds` (defined in `roles/common/vars/main.yaml`). Operators set the underlying values via inventory: `vmware_username`, `vmware_password`, `vmware_validate_certs`. Per-task connection overrides are only used where a module loops over a list of ESXi hosts at different addresses.

## `community.vmware` v6.2.0

| Module | Synopsis | Used in |
|---|---|---|
| [`vcenter_extension_info`](vcenter_extension_info.md) | Gather info vCenter extensions | 1 file |
| [`vmware_about_info`](vmware_about_info.md) | Provides information about VMware server to which user is connecting to | 1 file |
| [`vmware_all_snapshots_info`](vmware_all_snapshots_info.md) | Gathers information about all snapshots across virtual machines in a specified vmware datacenter | 1 file |
| [`vmware_category_info`](vmware_category_info.md) | Gather info about VMware tag categories | 1 file |
| [`vmware_content_library_info`](vmware_content_library_info.md) | Gather information about VMWare Content Library | 1 file |
| [`vmware_datacenter_info`](vmware_datacenter_info.md) | Gather information about VMware vSphere Datacenters | 4 files |
| [`vmware_datastore_info`](vmware_datastore_info.md) | Gather info about datastores available in given vCenter | 2 files |
| [`vmware_dvs_portgroup_info`](vmware_dvs_portgroup_info.md) | Gathers info DVS portgroup configurations | 1 file |
| [`vmware_dvswitch_info`](vmware_dvswitch_info.md) | Gathers info dvswitch configurations | 1 file |
| [`vmware_guest`](vmware_guest.md) | Manages virtual machines in vCenter | 0 files |
| [`vmware_guest_snapshot`](vmware_guest_snapshot.md) | Manages virtual machines snapshots in vCenter | 1 file |
| [`vmware_host_acceptance`](vmware_host_acceptance.md) | Manage the host acceptance level of an ESXi host | 0 files |
| [`vmware_host_config_info`](vmware_host_config_info.md) | Gathers info about an ESXi host's advance configuration information | 2 files |
| [`vmware_host_config_manager`](vmware_host_config_manager.md) | Manage advanced system settings of an ESXi host | 0 files |
| [`vmware_host_facts`](vmware_host_facts.md) | Gathers facts about remote ESXi hostsystem | 1 file |
| [`vmware_host_ntp`](vmware_host_ntp.md) | Manage NTP server configuration of an ESXi host | 0 files |
| [`vmware_host_service_info`](vmware_host_service_info.md) | Gathers info about an ESXi host's services | 1 file |
| [`vmware_host_service_manager`](vmware_host_service_manager.md) | Manage services on a given ESXi host | 2 files |
| [`vmware_host_user_manager`](vmware_host_user_manager.md) | Manage users of ESXi | 1 file |
| [`vmware_host_vmnic_info`](vmware_host_vmnic_info.md) | Gathers info about vmnics available on the given ESXi host | 1 file |
| [`vmware_local_user_info`](vmware_local_user_info.md) | Gather info about users on the given ESXi host | 1 file |
| [`vmware_resource_pool_info`](vmware_resource_pool_info.md) | Gathers info about resource pool information | 1 file |
| [`vmware_tag_info`](vmware_tag_info.md) | Manage VMware tag info | 1 file |
| [`vmware_vm_info`](vmware_vm_info.md) | Return basic info pertaining to a VMware machine guest | 2 files |

## `vmware.vmware` v2.8.0

| Module | Synopsis | Used in |
|---|---|---|
| [`appliance_info`](appliance_info.md) | Gather appliance information | 0 files |
| [`cluster_info`](cluster_info.md) | Gathers information about one or more clusters | 4 files |
| [`license_info`](license_info.md) | Fetch VMware vCenter license keys | 1 file |
| [`vcsa_backup_schedule_info`](vcsa_backup_schedule_info.md) | Gather info about one or more VCSA backup schedules. | 1 file |

## Regeneration

These pages are derived from the vendored collection metadata. To refresh after a collection version bump:

```bash
cd ncs-ansible && just install-collections
# Then re-run the generator that produced this folder.
```
