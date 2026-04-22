# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in the **ncs-framework** umbrella (directory is still named `codex/` on disk).

## What This Is

NCS (Non-Core Services) — a fleet management platform for auditing, STIG compliance, and reporting across VMware, Linux, and Windows. This root repository is an umbrella over several sub-projects:

| Path | Kind | Purpose |
|---|---|---|
| `ncs-ansible/` | tracked subdir | Ansible app layer — playbooks, inventory, Justfile, venvs |
| `ncs-ansible-{core,vmware,linux,windows,aci}/` | git submodule | Internal Ansible collections, each on its own release train |
| `ncs-ansible-collection-template/` | tracked subdir | Scaffolding for new collections |
| `ncs-reporter/` | tracked subdir | Standalone Python reporting CLI |
| `ncs-console/` | tracked subdir | PowerShell/WPF operator console |

The pipeline remains two decoupled stages:
1. **Collect** (ncs-ansible + the five `internal.*` collections) — emits `raw_*.yaml` artifacts via the `ncs_collector` callback plugin.
2. **Report** (ncs-reporter) — normalizes, evaluates alerts, renders dashboards / STIG reports / CKLB artifacts.

## Working in this tree

- **All Ansible commands run from `ncs-ansible/`.** The Justfile, ansible.cfg, inventory, collections, and venvs all live there. Previously-top-level recipes like `just site`, `just audit-vmware`, `just stig-audit-esxi`, `just report` work unchanged once you `cd ncs-ansible`.
- **Reporter development runs from `ncs-reporter/`.** It is pulled in as an editable dependency of `ncs-ansible` via `[tool.uv.sources] ncs-reporter = { path = "../ncs-reporter", editable = true }`.
- **Collection development runs inside each `ncs-ansible-<name>/` submodule.** Each has its own git remote (currently a `file://` URL to the source repo) and its own `galaxy.yml` release train. Commit there first, then bump the vendored tarball under `ncs-ansible/collections/vendor/` and update `ncs-ansible/requirements.yml`.

## Common Commands

```bash
# Framework-level setup (from repo root)
git -c protocol.file.allow=always submodule update --init   # hydrate collection submodules

# Ansible layer (cd ncs-ansible)
just setup-all              # venvs + collections + SMB share
just install-collections    # install internal.* from vendored tarballs
just lint                   # ruff check .
just format                 # ruff format .
just check                  # mypy + basedpyright
just lint-configs           # ncs-reporter YAML configs
just ansible-lint           # ansible playbook linting
just --list                 # full surface

# Reporter (cd ncs-reporter)
just test                   # pytest
just lint / just check      # ruff + mypy/basedpyright on src/
just test-all               # lint + check + test
```

## Architecture

### Ansible Collections (submodules under repo root)

Each `internal.*` collection is an independent git repo pulled in as a submodule. They are resolved into `ncs-ansible/collections/ansible_collections/internal/` via `ncs-ansible/requirements.yml`:

| Submodule | Collection | Roles | Purpose |
|---|---|---|---|
| `ncs-ansible-core/` | `internal.core` | `dispatch`, `emit`, `stig_orchestrator` | `ncs_collector` callback, `stig`/`pwsh` action+module plugins, filter plugins |
| `ncs-ansible-vmware/` | `internal.vmware` | `common`, `esxi`, `vcsa`, `vm` | VMware audit, STIG audit/remediate |
| `ncs-ansible-linux/` | `internal.linux` | `ubuntu`, `photon` | Linux audit, STIG audit/remediate |
| `ncs-ansible-windows/` | `internal.windows` | `server`, `domain` | Windows audit, STIG audit/remediate, AD |
| `ncs-ansible-aci/` | `internal.aci` | — | Cisco ACI audit |

The default install mode is vendored tarballs at `ncs-ansible/collections/vendor/*.tar.gz`. Switch to Mode B (live sibling-dir references) by commenting the tarball block in `requirements.yml` and uncommenting the `../ncs-ansible-<name>` entries — those paths resolve to the submodule working trees because `ncs-ansible/` and each `ncs-ansible-<name>/` are siblings under the root.

### Playbooks

**App layer** (`ncs-ansible/playbooks/`) — site orchestrators + NCS infrastructure:
- `site.yml`, `site_*.yml` — master orchestrators (setup → audit platforms → report)
- `ncs/` — report dir init, report generation, samba share, schedule timers
- `core/send_alert_email.yml` — localhost alerting

**Collections** — each submodule ships self-contained playbooks invoked by FQCN:
- `internal.vmware.esxi_stig_audit`, `internal.linux.ubuntu_collect`, `internal.windows.server_stig_audit`, etc.

Playbook file naming inside collections is flat with a sub-platform prefix (`esxi_stig_audit.yml`, `ubuntu_collect.yml`, `server_stig_audit.yml`). Shared role interface is `ncs_action` / `ncs_profile` / `ncs_operation`.

### ncs-reporter (ncs-reporter/)

Standalone Python package (`ncs-reporter/src/ncs_reporter/`). Key modules:
- `cli.py` — Click entry point (`all`, `site`, `linux`, `vmware`, `windows`, `node`, `stig`, `cklb`, `stig-apply`)
- `normalization/` — platform-specific data normalization and alert logic (health evaluation lives here, never in templates or Ansible)
- `view_models/` — typed Pydantic view contracts consumed by templates
- `aggregation.py` — multi-host state aggregation
- `_config.py` — config schema loader supporting canonical and alias keys

### Runtime Configs

Operator-editable configs live under `ncs-ansible/ncs_configs/`:
- `ncs-ansible/ncs_configs/ncs-reporter/` — reporter YAML schemas, `cklb_skeletons/`, `scripts/` (consumed by ncs-reporter via `--config-dir`)
- `ncs-ansible/ncs_configs/schedules.yml` — systemd timer definitions consumed by `playbooks/core/manage_schedules.yml`

Each submodule also carries its own `ncs-ansible-<name>/ncs_configs/` for collection-owned configuration.

## Two Ansible Environments

Both live under `ncs-ansible/`:
- `ncs-ansible/.venv/` — ansible-core latest; everything except VCSA SSH
- `ncs-ansible/.venv-vcsa/` — ansible-core 2.15 for VCSA appliances (Python 3.7 managed nodes). Uses `ANSIBLE_CONFIG=ansible-vcsa.cfg` and `collections_vcsa/`.

## Key Conventions

- Ruff line length: 120, target Python 3.10+
- Type checking: mypy (strict) + basedpyright (standard)
- Inventory: `ncs-ansible/inventory/production/` (Ansible vault password in `ncs-ansible/.vaultpass`)
- Reports output to `/srv/samba/reports/` by default
- Telemetry lake path pattern: `<platform_root>/{category}/{sub_platform}/{hostname}/raw_{type}.yaml`
- YAML config schemas support concise aliases (e.g. `title` for `display_name`, `from` for `path`, `expr` for `compute`)

## Submodule protocol note

The five `ncs-ansible-<name>/` submodules have `file://` URLs pointing at local source repos (`/home/sio/ncs-ansible-<name>`). Clone / update requires `-c protocol.file.allow=always` because git disables the `file` transport for submodules by default. Once those sources are published to remote hosts, swap URLs in `.gitmodules` and the protocol override goes away.
