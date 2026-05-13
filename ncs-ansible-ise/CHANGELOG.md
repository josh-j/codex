# Changelog

## 0.6.1

- `ise_auth_rows` now explodes the `other_attr_string` blob that MnT
  Session/MACAddress responses carry — a `:!:Key=Val:!:Key=Val:!:`
  string holding `ISEPolicySetName`,
  `AuthorizationPolicyMatchedRule`, `IdentityPolicyMatchedRule`, and
  `IdentitySelectionMatchedRule` among other fields. 0.6.0 removed
  the rule-name sections on the assumption MnT didn't expose them
  per-session on 3.3; the data was reachable all along, just nested
  inside that one field.
- `_first` fallback chains for `authentication_rule` /
  `authorization_rule` / `policy_set` / `matched_rule` extended to
  recognize the exploded key names.
- New filters `ise_parse_other_attr_string` (raw access),
  `ise_authentication_rule_summary`,
  `ise_authorization_rule_summary`, `ise_policy_set_summary` —
  same `_group_count` shape as the existing breakdowns.
- `nad_policy_hits` report restores `authentication_rules`,
  `authorization_rules`, and `policy_sets` sections, all driven
  from the now-populated row fields.

## 0.6.0

- **Pivot `nad_policy_hits` and the rest of the role off MnT
  AuthStatus/MACAddress.** Operator notes from a live ISE 3.3
  deployment confirmed everything outside `Session/ActiveList` and
  `Session/MACAddress/<mac>` is either confirmed-404 or 500-on-call,
  including the AuthStatus path the previous nad_policy_hits + every
  op's `recent_authentications` view was reading from. The role no
  longer polls that endpoint; `_ise_one_off_auth_rows` is permanently
  `[]` in the Shape task and reports that still reference it render
  empty until rewritten to a Session/MACAddress source.
- `nad_policy_hits` now consumes the per-MAC `Session/MACAddress`
  detail already fanned out by `ise_session_details_info` (extended
  to fire for this op). Report sections rewritten to match what MnT
  XML actually carries on 3.3 — `authorization_profiles` (with
  comma-split for chained-rule profiles), `authentication_methods`,
  `identity_groups`, `endpoint_policies`, `cts_security_groups`,
  `status_breakdown`, `failure_breakdown`, `recent_events`. The
  removed `authentication_rules` / `authorization_rules` /
  `policy_sets` sections were always going to be empty — MnT doesn't
  expose rule names per-session on 3.3.
- `ise_failure_summary` extracts the leading 5-digit code from
  `failure_reason` (e.g. `"11512 EAP-NAK received..."` → `code=11512`,
  `reason="EAP-NAK received..."`) so the same failure mode bucketed
  consistently across slightly-different description strings.
- New `_is_auth_record` guard in the breakdown helpers skips
  accounting-Stop records (no `passed`/`failed` field, no policy
  signal) so they don't sink into an empty-key bucket.
- New `ise_normalize_location` filter strips `All Locations#` prefix
  from session-side location strings to match the NAD-inventory
  output format; applied inside `ise_auth_rows`.
- New "MnT host sanity check" task fires when `ise_mnt_hostname`
  resolves to the same value as `ise_pan_hostname`. Single-node
  deployments will see it and ignore; split-persona deployments that
  forgot to set `ise_mnt_hostname` will see it and fix the wrong-node
  problem before chasing phantom-empty reports.
- Removed the 0.5.2 diagnostic task; the breakdown rewrite makes it
  obsolete.

## 0.5.2

- Temporary diagnostic step on `nad_policy_hits` to surface the
  upstream MnT request state, raw XML head, parsed row count, and
  filter survival count. nad_policy_hits is still showing empty
  breakdowns after the 0.5.1 parser fix; this dumps enough state to
  tell whether the breakage is the HTTP call, the parser, or the NAD
  filter. Will be removed once we've localized the issue.

## 0.5.1

- Fix `_parse_mnt_xml_rows` to walk 3-level MnT XML
  (`<authStatusOutputList><authStatusList><authStatusElements>...`).
  The old parser stopped at the per-MAC `<authStatusList>` wrapper and
  produced rows like `{"authStatusElements": <whitespace>}`, which
  blanked every field downstream — including all five `nad_policy_hits`
  breakdown tables and every `recent_authentications`/`recent_endpoint_auths`
  table on the other NAD-scoped one-offs. Parser now BFS-walks until it
  finds nodes whose direct children are all leaves and emits each as a
  row, so flat-row, 2-level, and 3-level shapes all work.

## 0.5.0

- New `nad_policy_hits` one-off: for a given NAD, breaks down recent
  authentication events by authentication rule, authorization rule,
  authorization profile, policy set, and authentication
  method/protocol. Sources are the existing AuthStatus payload narrowed
  to the NAD via `network_device_name` substring match — no extra MnT
  calls. Defaults to 24h lookback / 2000 records (raise for busy NADs).
- `ise_auth_rows` now exposes `authentication_rule`, `authorization_rule`,
  and `policy_set` as separate fields (previously conflated under
  `matched_rule`, which is preserved for back-compat).
- Five new aggregation filters: `ise_authc_rule_summary`,
  `ise_authz_rule_summary`, `ise_authz_profile_summary`,
  `ise_policy_set_summary`, `ise_authc_method_summary`. Each groups by
  the named field, counts hits, tracks last_seen, and carries a few
  sample fields the report uses for context.

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
