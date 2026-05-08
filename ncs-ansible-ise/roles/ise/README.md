# internal.ise.ise

Read-only Cisco ISE collection role.

The role delegates Cisco ISE API access to the upstream `cisco.ise`
modules, then emits a `raw_ise.yaml` bundle through `internal.core.emit`.
It is intentionally conservative around large datasets: endpoints,
guest users, and active session lists are off by default because those
datasets can be large or sensitive.

## Required Variables

- `ise_hostname`
- `ise_username`
- `ise_password`
- `ise_verify`
- `ise_version`

## Optional Collection Toggles

- `ise_collect_network_devices`: defaults to `true`
- `ise_collect_endpoints`: defaults to `false`
- `ise_collect_guests`: defaults to `false`
- `ise_collect_trustsec`: defaults to `true`
- `ise_collect_certificates`: defaults to `true`
- `ise_collect_node_health`: defaults to `true`
- `ise_collect_backup_repository`: defaults to `true`
- `ise_collect_patches`: defaults to `true`
- `ise_collect_policy`: defaults to `true`
- `ise_collect_device_admin`: defaults to `true`
- `ise_collect_identity_sources`: defaults to `true`
- `ise_collect_sessions`: defaults to `true`
- `ise_collect_active_session_list`: defaults to `false`
- `ise_skip_export`: defaults to `false`

Optional targeted checks:

- `ise_replication_nodes`: list of node names for replication status
  checks.
- `ise_repository_file_names`: list of repository names for file
  listing checks.
- `ise_authentication_status_seconds`: MnT authentication lookback
  window, defaults to `3600`.
- `ise_authentication_status_records`: MnT authentication record limit,
  defaults to `25`.

## Collected Areas

- Product/MnT version and telemetry metadata.
- Node inventory and optional node replication checks.
- Network devices and network device groups.
- System and trusted certificate inventories with expiry reporting.
- Backup last status, repositories, and optional repository file lists.
- Patch and hotpatch status.
- Network access policy objects available in the upstream collection:
  allowed protocols, authorization profiles, downloadable ACLs, and
  filter policies.
- Device administration/TACACS objects: command sets, profiles, server
  sequences, and external servers.
- Identity sources: Active Directory, ID store sequences, internal
  users, and LDAP sources.
- MnT visibility: active session count, failure reasons, recent
  authentication status, and optionally active session lists.
- Endpoint risk signals: default policy markers, high repeat counters,
  locally administered/randomized MAC addresses, endpoint device-type
  summary, and ISE RCM detection status.

## API Prerequisites

The upstream Cisco collection assumes that ISE API Gateway, ERS APIs,
and OpenAPIs are enabled on the target ISE deployment.
