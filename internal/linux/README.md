# internal.linux

Linux audit, collection, and STIG automation for Ubuntu and Photon OS systems.

## Roles

| Role | Platform | Actions | Profiles | Operations |
|---|---|---|---|---|
| [ubuntu](roles/ubuntu/README.md) | Ubuntu 24.04 | `collect`, `audit`, `remediate`, `verify` | `stig` | `maintain`, `patch`, `password_rotate`, `password_status` |
| [photon](roles/photon/README.md) | Photon OS 5.0 | `collect`, `audit`, `remediate`, `verify` | `stig` | `password_rotate`, `password_status` |

Both roles use `internal.core.dispatch` for action routing and `internal.core.stig_orchestrator` for STIG workflows.

## STIG Coverage

- SSH hardening and crypto configuration
- Package and service management
- Audit rules and auditd controls
- PAM and account policies
- File permissions and ownership
- System and kernel configuration

## Shared Components

- `roles/common/tasks/password_status.yaml` — Reusable password aging and account status task included by both roles.
