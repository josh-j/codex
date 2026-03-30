# VMware Raw Payload Schema

This document defines the maintained raw payload contracts emitted by the `internal.vmware` audit roles. These contracts are consumed by `internal.core.ncs_collector` and `ncs_reporter`.

## Public Payload Families

### `vmware_raw_vcenter`

Exported by `internal.vmware.vcsa` with `ncs_action: collect`. The assemble task flattens raw module output into a flat key structure.

| Key | Type | Description |
| :--- | :--- | :--- |
| `appliance_version` | string | vCenter Server version string. |
| `appliance_build` | string | vCenter Server build number. |
| `appliance_health_overall` | string | Overall appliance health (`green`, `yellow`, `red`, `gray`). |
| `appliance_health_cpu` | string | CPU health status. |
| `appliance_health_memory` | string | Memory health status. |
| `appliance_health_database` | string | Database health status. |
| `appliance_health_storage` | string | Storage health status. |
| `appliance_uptime_seconds` | float | Appliance uptime in seconds. |
| `ssh_enabled` | bool | Whether SSH access is enabled on the appliance. |
| `shell_enabled` | bool | Whether shell access is enabled on the appliance. |
| `ntp_mode` | string | Time synchronization mode (e.g. `NTP`). |
| `ntp_servers` | list | List of configured NTP server addresses. |
| `backup_schedules` | list | Configured backup schedule entries. |
| `backup_schedule_count` | int | Number of configured backup schedules. |
| `vcenter_count` | int | Always 1 (single vCenter per payload). |
| `datacenter_count` | int | Number of datacenters. |
| `cluster_count` | int | Number of clusters across all datacenters. |
| `esxi_host_count` | int | Total ESXi hosts across all clusters. |
| `datastore_count` | int | Number of datastores. |
| `resource_pool_count` | int | Number of resource pools. |
| `dvswitch_count` | int | Number of distributed virtual switches. |
| `dvs_portgroup_count` | int | Number of distributed port groups. |
| `license_count` | int | Number of vSphere licenses. |
| `extension_count` | int | Number of vCenter extensions. |
| `content_library_count` | int | Number of content libraries. |
| `tag_category_count` | int | Number of tag categories. |
| `tag_count` | int | Number of tags. |
| `alarm_count` | int | Number of active triggered alarms. |
| `clusters` | list | Flattened cluster list with usage metrics. |
| `datastores` | list | Flattened datastore list. |
| `resource_pools` | list | Resource pool entries. |
| `dvswitches` | list | Distributed virtual switch entries. |
| `dvs_portgroups` | list | Distributed port group entries. |
| `licenses` | list | License entries. |
| `extensions` | list | Extension entries. |
| `content_libraries` | list | Content library entries. |
| `tag_categories` | list | Tag category entries. |
| `tags` | list | Tag entries. |
| `active_alarms` | list | Currently triggered alarm entries. |
| `config` | object | Site/config context passed downstream to reporting. |

### `vmware_raw_esxi`

Exported by `internal.vmware.esxi` with `ncs_action: collect`.

| Key | Type | Description |
| :--- | :--- | :--- |
| `datacenters_info` | object | Raw datacenter inventory payload. |
| `clusters_info` | object | Raw cluster inventory payload. |
| `datastores_info` | object | Normalized datastore list envelope. |
| `hosts_info` | object | Per-ESXi-host health data (facts, NICs, services). |
| `config` | object | Site/config context passed downstream to reporting. |
| `collection_status` | string | `SUCCESS` or `FAILED`. |
| `collection_error` | string | Failure message when collection fails. |

#### `hosts_info` Structure

| Key | Type | Description |
| :--- | :--- | :--- |
| `host_facts` | list | Per-host results from `community.vmware.vmware_host_facts`. |
| `host_nics` | list | Per-host results from `community.vmware.vmware_host_vmnic_info`. |
| `host_services` | list | Per-host results from `community.vmware.vmware_host_service_info`. |

### `vmware_raw_vm`

Exported by `internal.vmware.vm` with `ncs_action: collect`. The assemble task flattens raw module output into a flat key structure.

| Key | Type | Description |
| :--- | :--- | :--- |
| `datacenters` | list | Datacenter names for the inventory scope. |
| `virtual_machines` | list | Flattened VM inventory list. |
| `vms_info_raw` | object | Raw VM info module output (pre-flattening). |
| `snapshots_raw` | list | Raw snapshot data before normalization. |
| `snapshot_count` | int | Total number of snapshots. |
| `vm_count` | int | Total number of VMs. |
| `infra_patterns` | list | Regex patterns for infrastructure VM exclusion. |
| `config` | object | Site/config context passed downstream to reporting. |

## Fixture and Simulation Rules

- Simulation fixtures may provide either a full callback-style document with a `data` envelope or just the payload body.
- Collection roles normalize both formats before mapping fixture content into `_raw_*` variables.
- The top-level payload keys listed above are the compatibility contract; internal `_raw_*` helper variables are not public.

## STIG Fact Shapes

The STIG pipelines also build internal fact structures used during rule evaluation.

### ESXi Host Facts (`esxi_ctx.stig_facts[]`)

| Key | Type | Description |
| :--- | :--- | :--- |
| `name` | string | Hostname of the ESXi host. |
| `identity` | object | Host identity: `{ version, build }`. |
| `advanced_settings_map` | dict | Dict-based advanced settings for fast lookup. |
| `config.option_value` | list | Compatibility shim for list-based advanced settings. |
| `services` | dict | Service states: `{ service_key: { running, policy, label } }`. |
| `ssh` | object | SSH configuration: `{ sshd_config, banner_content }`. |
| `discovery_meta` | object | Discovery metadata: `{ timestamp, source }`. |

### VM Facts (`vmware_ctx.stig_facts[]`)

| Key | Type | Description |
| :--- | :--- | :--- |
| `name` | string | VM name. |
| `identity` | object | VM identity: `{ guest_id, tools_status, uuid }`. |
| `advanced_settings` | dict | Dict-based VMX `extraConfig`. |
| `hardware` | object | Hardware status including removable devices and disk modes. |
| `security` | object | Security flags such as encryption and logging state. |
| `discovery_meta` | object | Discovery metadata: `{ timestamp, source }`. |
