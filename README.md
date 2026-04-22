# NCS — Non-Core Services

**ncs-framework** — umbrella repository for the NCS fleet management platform: auditing, STIG compliance, and reporting across VMware (vCenter/ESXi/VM), Linux (Ubuntu/Photon), and Windows infrastructure.

The root directory is kept as `codex/` on disk for now; logically it is the `ncs-framework`.

## Layout

Every sub-project is a tracked subdirectory of this repo. The five built-in `internal.*` collections live alongside the orchestrator; a plain `git clone` pulls everything.

| Path | Kind | What it is |
|---|---|---|
| `ncs-ansible/` | subdir | Ansible app layer — playbooks, inventory, `Justfile`, collection consumer |
| `ncs-ansible-core/` | subdir | `internal.core` collection — `ncs_collector` callback, `stig`/`pwsh` plugins |
| `ncs-ansible-vmware/` | subdir | `internal.vmware` — vCenter / ESXi / VM audit + STIG |
| `ncs-ansible-linux/` | subdir | `internal.linux` — Ubuntu / Photon audit + STIG |
| `ncs-ansible-windows/` | subdir | `internal.windows` — Server / AD audit + STIG |
| `ncs-ansible-aci/` | subdir | `internal.aci` — Cisco ACI audit |
| `ncs-ansible-collection-template/` | subdir | Scaffold for new collections |
| `ncs-reporter/` | subdir | Standalone Python reporting CLI ([README](ncs-reporter/README.md)) |
| `ncs-console/` | subdir | PowerShell/WPF operator console ([README](ncs-console/README.md)) |
| `docs/` | subdir | Architecture, references, dev runbooks under `_dev/` |
| `prompts/` | subdir | Reusable agent prompts for repetitive authoring tasks |

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

## Quick Start

```bash
git clone <url>
cd codex/ncs-ansible
just setup-all    # venvs + collections + SMB share
just --list       # every Justfile recipe
just site         # full audit + report pipeline
```

See `ncs-ansible/Justfile` for the full command surface. Reporter-only workflows live under `ncs-reporter/` (see its README).

## Testing a collection standalone

Each `internal.*` collection ships a `tests/` harness that works without the orchestrator:

```bash
cd ncs-ansible-linux
cp -r tests/inventory.example tests/inventory
echo 'change-me' > tests/.vault_pass
# populate tests/inventory/hosts.yml with a lab host; see tests/README.md
just test         # dry-run ubuntu_collect against the lab
```

Full contract: [`docs/COLLECTION_LAYOUT.md`](docs/COLLECTION_LAYOUT.md).

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
- [Collection Layout (inventory + vault)](docs/COLLECTION_LAYOUT.md)
- [Scheduling & Alert Actions](docs/SCHEDULING_AND_ALERT_ACTIONS.md)
- [OpenSSH + Kerberos](docs/OPENSSH_KERBEROS.md)
- [Dev runbooks](docs/_dev/) — STIG migration workflow, release process, bug postmortem
