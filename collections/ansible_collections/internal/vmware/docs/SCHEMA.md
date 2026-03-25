# VMware Raw Payload Schema

This document defines the maintained raw payload contracts emitted by the `internal.vmware` audit roles. These contracts are consumed by `internal.core.ncs_collector` and `ncs_reporter`.

## Public Payload Families

### `vmware_raw_vcenter`

Exported by `internal.vmware.vcsa` with `ncs_action: collect`.

| Key | Type | Description |
| :--- | :--- | :--- |
| `appliance_health_info` | object | Raw result from appliance health collection. |
| `appliance_backup_info` | object | Raw result from appliance backup schedule collection. |
| `alarms_info` | object | Raw result from `vmware_triggered_alarms_info`. |
| `datacenters_info` | object | Raw result from `vmware_datacenter_info`. |
| `clusters_info` | object | Raw result from `cluster_info` (loop over datacenters). |
| `datastores_info` | object | Flattened datastore list from `vmware_datastore_info`. |
| `resource_pools_info` | object | Raw result from `vmware_resource_pool_info`. |
| `dvswitches_info` | object | Raw result from `vmware_dvswitch_info`. |
| `dvs_portgroups_info` | object | Raw result from `vmware_dvs_portgroup_info`. |
| `licenses_info` | object | Raw result from `vmware_license_info`. |
| `extensions_info` | object | Raw result from `vcenter_extension_info`. |
| `content_libraries_info` | object | Raw result from `vmware_content_library_info`. |
| `tag_categories_info` | object | Raw result from `vmware_category_info`. |
| `tags_info` | object | Raw result from `vmware_tag_info`. |
| `config` | object | Site/config context passed downstream to reporting. |
| `collection_status` | string | `SUCCESS` or `FAILED`. |
| `collection_error` | string | Failure message for preflight or collection failures. |

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

Exported by `internal.vmware.vm` with `ncs_action: collect`.

| Key | Type | Description |
| :--- | :--- | :--- |
| `datacenters_info` | object | Raw datacenter inventory payload. |
| `vms_info` | object | Raw VM inventory payload. |
| `snapshots_info` | object | Normalized VM snapshot list envelope. |
| `config` | object | Site/config context passed downstream to reporting. |
| `collection_status` | string | `SUCCESS` or `FAILED`. |
| `collection_error` | string | Failure message when collection fails. |

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
