# NCS — Non-Core Services

**ncs-framework** — umbrella repository for the NCS fleet management platform: auditing, STIG compliance, and reporting across VMware (vCenter/ESXi/VM), Linux (Ubuntu/Photon), and Windows infrastructure.

This umbrella is **ncs-framework**. The checkout directory on disk may be named differently on your machine; paths below are relative to the repo root.

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
| `docs/` | subdir | Architecture and reference docs |
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
cd ncs-framework/ncs-ansible
just setup-all    # venvs + collections + SMB share
just --list       # every Justfile recipe
just site         # full audit + report pipeline
```

See `ncs-ansible/Justfile` for the full command surface. Reporter-only workflows live under `ncs-reporter/` (see its README).

## Authoring your own collection

Third-party platforms plug into NCS as their own collection. The orchestrator (`ncs-ansible/`) consumes them exactly like the built-in five — `internal.core` provides the shared callback and STIG wrapper, and your collection ships its roles, playbooks, and reporter configs.

1. **Scaffold from the template.** Copy `ncs-ansible-collection-template/` out next to the orchestrator (either inside this umbrella or as a sibling checkout):

   ```bash
   cp -r ncs-ansible-collection-template ../ncs-ansible-netbox
   cd ../ncs-ansible-netbox
   # Replace __COLLECTION_NAME__ with your platform name
   sed -i 's/__COLLECTION_NAME__/netbox/g' galaxy.yml README.md meta/*
   ```

2. **Wire the pieces.** The template already ships the right shape:
   - `galaxy.yml` — set `name:` and keep `dependencies: { internal.core: ">=1.0.0,<2.0.0" }`.
   - `roles/<platform>/` — at least one role, using the `ncs_action` / `ncs_profile` / `ncs_operation` contract so `internal.core.dispatch` can route to it. See `HELPERS.md` in the template.
   - `playbooks/<platform>_collect.yml` — emits `raw_*.yaml` via the `ncs_collector` callback (inherited from `internal.core`).
   - `plugins/` — optional filter/action/callback plugins specific to your platform.

3. **Collection-local test harness.** The template carries a `tests/` skeleton; populate it exactly like the built-ins:

   ```bash
   cp -r tests/inventory.example tests/inventory
   echo 'change-me' > tests/.vault_pass
   # edit tests/inventory/hosts.yml and any tests/inventory/group_vars/
   just test                    # --check dry-run against your lab
   ```

   See [`docs/COLLECTION_LAYOUT.md`](docs/COLLECTION_LAYOUT.md) for the full contract.

4. **Reporter configs for your collection.** Drop them under `ncs-ansible-<yours>/ncs_configs/`:

   ```
   ncs-ansible-netbox/ncs_configs/
   ├── netbox.yaml                     # schema + alerts for your bundle
   ├── scripts/<helper>.py             # optional custom normalizers
   └── cklb_skeletons/…                # optional DISA CKLB templates
   ```

   Add your collection's config dir to the orchestrator's `ncs-ansible/ncs_configs/config.yaml`:

   ```yaml
   extra_config_dirs:
     # existing built-ins…
     - ../../ncs-ansible-netbox/ncs_configs
   ```

5. **Plug into the orchestrator.** Build the collection tarball and add it to `ncs-ansible/requirements.yml`:

   ```bash
   cd ncs-ansible-netbox
   just build                                  # emits dist/internal-netbox-0.1.0.tar.gz
   cp dist/internal-netbox-0.1.0.tar.gz ../ncs-ansible/collections/vendor/
   # add to requirements.yml under the existing tarball block:
   #   - name: "./collections/vendor/internal-netbox-0.1.0.tar.gz"
   #     type: file
   cd ../ncs-ansible
   just install-collections
   ```

   Or during active development, switch `requirements.yml` to Mode B (sibling-dir references) — the comment block at the top of that file documents both.

6. **Invoke it.** Your collection's playbooks are now callable from the orchestrator by FQCN:

   ```bash
   cd ncs-ansible
   just run-fqcn internal.netbox.netbox_collect   # or ansible-playbook <fqcn> -i inventory/production
   ```

Reporter will pick up your `ncs_configs/` via the `extra_config_dirs` entry on the next `ncs-reporter all` run.

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
