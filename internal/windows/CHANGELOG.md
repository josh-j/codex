# Changelog — internal.windows

## 1.1.0

- Ship platform playbooks inside the collection. The operator-facing entry
  points moved from `playbooks/windows/<sub>/<action>.yml` (in the app repo)
  into `internal/windows/playbooks/<sub>_<action>.yml` (inside the collection).
  Invoke via FQCN, e.g. `ansible-playbook internal.windows.server_stig_audit`.
- Roles and plugins are unchanged from 1.0.0.

## 1.0.0

- Initial release with server + domain audit and STIG roles.
