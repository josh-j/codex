# NCS — Network Control System

Ansible-based fleet management platform for auditing, STIG compliance, and reporting across VMware (vCenter/ESXi/VM), Linux (Ubuntu/Photon), and Windows infrastructure.

## Architecture

NCS uses a two-stage pipeline:

```
Stage 1 — Collect (Ansible)
  Roles run modules, emit raw_*.yaml artifacts via ncs_collector callback

Stage 2 — Report (ncs-reporter)
  Normalizes raw data, evaluates alerts, renders HTML dashboards / STIG reports / CKLB artifacts
```

The stages are fully decoupled — you can re-render reports from existing artifacts without re-auditing hosts.

## Directory Structure

| Directory | Purpose |
|---|---|
| `playbooks/` | Ansible playbooks organized by platform ([README](playbooks/README.md)) |
| `internal/` | Custom Ansible collections: [core](internal/core/README.md), [linux](internal/linux/README.md), [vmware](internal/vmware/README.md), [windows](internal/windows/README.md) |
| `ncs-reporter/` | Standalone Python reporting CLI ([README](ncs-reporter/README.md)) |
| `ncs-console/` | PowerShell/WPF operator console ([README](ncs-console/README.md)) |
| `inventory/` | Ansible inventory (`production/`, `lab/`) |
| `files/` | Deployed configuration files (ncs-reporter configs, templates) |
| `docs/` | Operational documentation (STIG workflows, architecture, lab access) |
| `scripts/` | Utility scripts (config sync, report verification) |

## Quick Start

```bash
just setup-all    # Bootstrap both venvs + install all collections
just verify-env   # Verify environments are configured correctly
just --list       # Show all available commands
```

## Common Commands

### Fleet Audits

```bash
just site                         # Full pipeline: audit all platforms + generate reports
just site-collect                 # Collection only (no reporting)
just site-reports                 # Reporting only from existing artifacts
just audit-vmware                 # VMware health audit
just audit-ubuntu                 # Ubuntu audit
just audit-windows                # Windows audit
just health-windows               # Windows health checks
```

### STIG Compliance (Read-Only)

```bash
just stig-audit-esxi <target>     # ESXi STIG compliance check
just stig-audit-vcsa              # VCSA STIG audit
just stig-audit-photon            # Photon OS STIG audit
just stig-audit-vm <vcenter> <vm> # Single VM STIG audit
```

### STIG Remediation (Mutating)

```bash
just stig-harden-esxi <target>    # ESXi STIG hardening
just stig-remediate-vcsa          # VCSA STIG hardening
just stig-remediate-photon        # Photon OS STIG hardening
just stig-apply-esxi <artifact> <vcenter> <host>  # Interactive rule-by-rule apply
```

### Reporting

```bash
just report                       # Generate all platform + site reports
just report-stig <input>          # STIG compliance reports only
just report-cklb <input>          # CKLB artifacts for STIG Viewer
```

### Lifecycle Management

```bash
just update-ubuntu                # Ubuntu apt update + dist-upgrade
just update-windows               # Windows update apply
just rotate-password-ubuntu       # Rotate local user password
just rotate-password-esxi <vc> <hosts>  # Rotate ESXi local password via vCenter
```

### Development

```bash
just lint                         # Ruff check
just format                       # Ruff format
just check                        # mypy + basedpyright
just test                         # Unit tests (pytest)
just integration                  # Integration tests
just lint-configs                 # Lint ncs-reporter YAML configs
just ansible-lint                 # Ansible playbook linting
```

## Two Ansible Environments

| Environment | Config | Use Case |
|---|---|---|
| `.venv/` (main) | `ansible.cfg` | Everything except VCSA SSH — uses latest ansible-core |
| `.venv-vcsa/` | `ansible-vcsa.cfg` | VCSA appliances — pinned to ansible-core 2.15 for Python 3.7 compatibility |

## Further Reading

- [STIG Migration Workflow](docs/STIG_MIGRATION_WORKFLOW.md) — End-to-end guide for migrating platform STIG roles
- [Architecture Diagram](docs/MERMAID_ARCH.md) — Mermaid diagrams of the NCS system
- [OpenSSH + Kerberos](docs/OPENSSH_KERBEROS.md) — Hybrid Windows connection strategy
- [STIG Bugs Encountered](docs/STIG_BUGS_ENCOUNTERED.md) — Known issues and framework-level mitigations
- [Lab Access](docs/LAB_ACCESS.md) — Lab environment credentials and endpoints
