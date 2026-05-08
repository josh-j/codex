# Cisco ISE Module Catalog

The full upstream module index is hosted in the Ansible collection
docs:

https://docs.ansible.com/projects/ansible/11/collections/cisco/ise/index.html

Cisco also hosts generated docs for the upstream repository:

https://ciscoise.github.io/ansible-ise/main/plugins/index.html

Note: module naming can differ between Ansible-hosted docs and the
current Galaxy package. A live Galaxy install on 2026-05-07 resolved
`cisco.ise` 3.1.0; the starter role in this collection uses names
verified against that package, such as `identitygroup_info` and
`sgacl_info`.

The collection has hundreds of modules. Use this map to find the right
family quickly, then open the exact module page for parameters and
return values.

## Common Inventory And Platform

- `mnt_version_info` - MnT/API version visibility
- `telemetryinfo_info` - telemetry metadata
- `node_info`, `node_group_info`, `node_deployment_info` - node and
  deployment inventory where supported by the installed collection
- `telemetryinfo_info` - system telemetry metadata in the current
  Galaxy package

## Network Devices

- `network_device`, `network_device_info`
- `network_device_group`, `network_device_group_info`
- `network_device_bulk_request`,
  `network_device_bulk_monitor_status_info`

## Identity Stores And Users

- `identitygroup`, `identitygroup_info`
- `internal_user`, `internal_user_info`
- `active_directory`, `active_directory_info`
- `id_store_sequence`, `id_store_sequence_info`
- `rest_id_store`, `rest_id_store_info`

## Network Access Policy

- `network_access_policy_set`, `network_access_policy_set_info`
- `network_access_authentication_rules`,
  `network_access_authentication_rules_info`
- `network_access_authorization_rules`,
  `network_access_authorization_rules_info`
- `network_access_conditions`, `network_access_conditions_info`
- `authorization_profile`, `authorization_profile_info`
- `downloadable_acl`, `downloadable_acl_info`

## Device Administration

- `device_administration_policy_set`,
  `device_administration_policy_set_info`
- `device_administration_authentication_rules`,
  `device_administration_authentication_rules_info`
- `device_administration_authorization_rules`,
  `device_administration_authorization_rules_info`
- `tacacs_command_sets`, `tacacs_command_sets_info`
- `tacacs_profile`, `tacacs_profile_info`
- `tacacs_server_sequence`, `tacacs_server_sequence_info`

## Endpoints And Profiling

- `endpoint`, `endpoint_info`, `endpoints_info`
- `endpoint_group`, `endpoint_group_info`
- `endpoint_bulk_request`, `endpoint_bulk_monitor_status_info`
- `profiler_profile_info`
- `anc_policy`, `anc_policy_info`
- `anc_endpoint_apply`, `anc_endpoint_clear`, `anc_endpoint_info`

## Guest And Portals

- `guest_user`, `guest_user_info`
- `guest_type`, `guest_type_info`
- `guest_ssid`, `guest_ssid_info`
- `sponsor_group`, `sponsor_group_info`
- `sponsor_portal`, `sponsor_portal_info`
- `self_registered_portal`, `self_registered_portal_info`
- `hotspot_portal`, `hotspot_portal_info`

## TrustSec And Segmentation

- `sgt`, `sgt_info`
- `sgacl`, `sgacl_info`
- `sg_mapping`, `sg_mapping_info`
- `egress_matrix_cell`, `egress_matrix_cell_info`
- `trustsec_sg_vn_mapping`, `trustsec_sg_vn_mapping_info`
- `trustsec_vn`, `trustsec_vn_info`
- `trustsec_vn_vlan_mapping`, `trustsec_vn_vlan_mapping_info`

## pxGrid

- `px_grid_node_approve`, `px_grid_node_delete`, `px_grid_node_info`
- `px_grid_direct`, `px_grid_direct_info`
- `pxgrid_service_register`, `pxgrid_service_unregister`
- `pxgrid_sessions_info`
- `pxgrid_security_groups_info`
- `pxgrid_security_group_acls_info`
- `pxgrid_user_groups_info`

## Certificates

- `trusted_certificate`, `trusted_certificate_info`
- `trusted_certificate_import`, `trusted_certificate_export_info`
- `system_certificate`, `system_certificate_info`
- `system_certificate_create`, `system_certificate_import`
- `csr_generate`, `csr_info`, `csr_export_info`, `csr_delete`
- `bind_signed_certificate`
- `renew_certificate`
- `selfsigned_certificate_generate`

## Backup, Patch, Upgrade, And Repository

- `backup_config`, `backup_restore`, `backup_last_status_info`
- `backup_schedule_config`, `backup_schedule_config_update`
- `repository`, `repository_info`, `repository_files_info`
- `patch_info`, `patch_install`, `patch_rollback`
- `hotpatch_info`, `hotpatch_install`, `hotpatch_rollback`
- `upgrade_stage_start`, `upgrade_stage_cancel`, `upgrade_proceed`

## Monitoring And Sessions

- `mnt_account_status_info`
- `mnt_authentication_status_info`
- `mnt_failure_reasons_info`
- `mnt_session_active_count_info`
- `mnt_session_active_list_info`
- `mnt_session_by_ip_info`
- `mnt_session_by_mac_info`
- `mnt_sessions_by_session_id_info`
- `mnt_version_info`

## Newer API Areas

Check the upstream docs and Cisco API version matrix before using these
against older ISE versions:

- Duo: `duo_identity_sync`, `duo_mfa`
- Data Connect: `dataconnect_info`, `dataconnect_settings_*`
- IPsec: `ipsec_*`
- Subscriber and user equipment: `subscriber_*`, `user_equipment_*`
- OIDC and other ISE 3.5 patch additions through Cisco API changelog
