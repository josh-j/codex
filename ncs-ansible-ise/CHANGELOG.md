# Changelog

## 0.4.0

- Fixed "Endpoints on NAD" and other NAD-scoped one-offs that were
  showing "0 match network devices", "0 recent endpoint auths", and a
  blank-columns active-endpoints table.
- `ise_network_devices_info`: new `name_filter` parameter feeds an ERS
  server-side `filter=name.CONTAINS.<value>` so NAD lookups hit the
  full fleet, not just page 1. New `include_settings: false` mode
  returns ERS summaries only when callers don't need the per-NAD
  detail fan-out. Row output also carries `id`/`location`/`type` now.
- `ise_session_details_info`: new module. Lists MnT
  `Session/ActiveList`, narrows by `nas_ip_address` against a
  caller-supplied NAD IP set, then fans out
  `Session/MACAddress/<mac>` per session in a `ThreadPoolExecutor`.
  Fills the port/vlan/auth_protocol/authz-profile/matched-rule columns
  that the condensed ActiveList payload doesn't carry.
- New filter `ise_sessions_on_nads(sessions, nads)` joins active
  sessions to matched NADs by IP — ActiveList rows only have
  `nas_ip_address`, so substring name queries via `ise_nad_rows` were
  dropping every match. `switch_lookup` and `nad_troubleshooting`
  reports use the new filter; `nad_endpoint_inventory` consumes the
  fan-out output directly.
- One unified `Inventory NADs` task replaces the page-1 ERS GET and
  the audit-only module call. `nad_missing_protocols` leaves
  `name_filter` empty to audit everything; the lookup ops pass
  `_ise_nad_query`.

## 0.3.1

- Replaced the `nad_missing_protocols` async + async_status fan-out with a
  new `internal.ise.ise_network_devices_info` module that does ERS list
  pagination and per-NAD detail fetches in a `ThreadPoolExecutor`. Removes
  the per-iteration Ansible loop overhead and the `delay: 2` polling that
  dominated wall-clock on large NAD fleets. The unused
  `ise_nad_protocol_status` filter and its registration are gone.

## 0.3.0

- Renamed `playbooks/ise_collect.yml` → `playbooks/collect.yml` and
  `playbooks/ise_one_offs.yml` → `playbooks/one_offs.yml`. The previous
  layout shipped both `collect.yml` (a one-line import shim used by
  `site_collect_only.yml` to dispatch `internal.ise.collect`) and
  `ise_collect.yml` (the real play), which surfaced as two separate
  entries in the ncs-console playbook tree. ISE has no sub-platform,
  so the prefix wasn't disambiguating anything; the canonical FQCN
  is now `internal.ise.collect` / `internal.ise.one_offs`.

## 0.1.0

- Initial `internal.ise` collection scaffold.
- Added read-only `collect.yml` playbook and role.
- Added ncs-console one-off profiles for endpoint lookup, endpoint risk,
  switch lookup, NAD port endpoint reporting, user auth history, failed
  auth summaries, and endpoint CoA.
- Added one-off HTML/CSV artifacts, auto-open report markers, endpoint
  timeline, policy hit explorer, and endpoint ANC apply/clear workflow.
- Added NAD troubleshooting, NAD port history, and policy object detail
  drilldown one-off reports.
- Added standalone lab test inventory.
- Added Cisco ISE Ansible/API reference documentation under `docs/`.
- Added read-only audit coverage for certificates, node health,
  backup/repository status, patch status, network access policy
  objects, TACACS/device administration objects, identity sources, and
  MnT session/authentication visibility.
- Added endpoint risk signals for default policy markers, high repeat
  counters, and locally administered/randomized MAC addresses.
