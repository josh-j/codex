# Changelog

## 0.1.0

- Initial `internal.ise` collection scaffold.
- Added read-only `ise_collect` playbook and role.
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
