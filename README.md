# NCS — Non-Core Services

**ncs-framework** — umbrella repository for the NCS fleet management platform: auditing, STIG compliance, and reporting across VMware (vCenter/ESXi/VM), Linux (Ubuntu/Photon), and Windows infrastructure.

The root directory is kept as `codex/` on disk for now; logically it is the `ncs-framework`.

## Layout

Each sub-project is either a tracked subdirectory (`ncs-ansible/`, `ncs-reporter/`, `ncs-console/`, `ncs-ansible-collection-template/`) or a git submodule for collections that publish on their own release train (`ncs-ansible-{core,vmware,linux,windows,aci}`).

| Path | Kind | What it is |
|---|---|---|
| `ncs-ansible/` | subdir | Ansible app layer — playbooks, inventory, `Justfile`, collection consumer ([README](ncs-ansible/README.md) if added) |
| `ncs-ansible-core/` | submodule | `internal.core` collection — `ncs_collector` callback, shared plugins |
| `ncs-ansible-vmware/` | submodule | `internal.vmware` — vCenter / ESXi / VM audit + STIG |
| `ncs-ansible-linux/` | submodule | `internal.linux` — Ubuntu / Photon audit + STIG |
| `ncs-ansible-windows/` | submodule | `internal.windows` — Server / AD audit + STIG |
| `ncs-ansible-aci/` | submodule | `internal.aci` — Cisco ACI audit |
| `ncs-ansible-collection-template/` | subdir | Scaffold for new collection repos |
| `ncs-reporter/` | subdir | Standalone Python reporting CLI ([README](ncs-reporter/README.md)) |
| `ncs-console/` | subdir | PowerShell/WPF operator console ([README](ncs-console/README.md)) |

## Pipeline

```
Stage 1 — Collect (ncs-ansible)
  Playbooks in ncs-ansible/ + the five internal.* collections run modules,
  emit raw_*.yaml artifacts via the ncs_collector callback plugin.

Stage 2 — Report (ncs-reporter)
  Normalizes raw data, evaluates alerts,
  renders HTML dashboards / STIG reports / CKLB artifacts.
```

The stages are decoupled — reports can be re-rendered from existing artifacts without re-auditing hosts.

## Cloning

The collection submodules use `file://` URLs (their source repos live outside this tree). Clone with:

```bash
git -c protocol.file.allow=always clone --recurse-submodules <url>
# …or after a plain clone:
git -c protocol.file.allow=always submodule update --init
```

## Quick Start

```bash
cd ncs-ansible
just setup-all    # venvs + collections + SMB share
just --list       # every Justfile recipe
just site         # full audit + report pipeline
```

See `ncs-ansible/README.md` (when present) or `ncs-ansible/Justfile` for the full command surface. Reporter-only workflows live under `ncs-reporter/` (see its README).

## Common Commands

All audit / STIG / reporting commands run from `ncs-ansible/`. See `cd ncs-ansible && just --list` for the full list; previously-top-level commands (`just site`, `just audit-vmware`, `just stig-audit-esxi`, `just report`, etc.) work unchanged once you `cd ncs-ansible`.

## Two Ansible Environments

Both live under `ncs-ansible/`:

| Env | Config | Use |
|---|---|---|
| `ncs-ansible/.venv/` | `ansible.cfg` | Everything except VCSA SSH — latest ansible-core |
| `ncs-ansible/.venv-vcsa/` | `ansible-vcsa.cfg` | VCSA appliances — pinned to ansible-core 2.15 for Python 3.7 compatibility |

## Further Reading

- [Architecture Diagram](docs/MERMAID_ARCH.md)
- [`internal.core.stig` Reference](docs/INTERNAL_CORE_STIG.md)
- [Scheduling & Alert Actions](docs/SCHEDULING_AND_ALERT_ACTIONS.md)
- [OpenSSH + Kerberos](docs/OPENSSH_KERBEROS.md)
- [Dev runbooks](docs/_dev/) — STIG migration workflow, release process, bug postmortem
