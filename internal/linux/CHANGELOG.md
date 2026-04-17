# Changelog — internal.linux

## 1.1.0

- Ship platform playbooks inside the collection. The operator-facing entry
  points moved from `playbooks/linux/<sub>/<action>.yml` (in the app repo)
  into `internal/linux/playbooks/<sub>_<action>.yml` (inside the collection).
  Invoke via FQCN, e.g. `ansible-playbook internal.linux.ubuntu_collect`.
- `stig_report.py` now ships with the ubuntu role at
  `roles/ubuntu/files/stig_report.py` (previously at the app-repo
  `scripts/stig_report.py` path). `ubuntu_stig_verify` resolves it via the
  playbook directory.
- Roles and plugins are unchanged from 1.0.0.

## 1.0.0

- Initial release with ubuntu + photon audit and STIG roles.
