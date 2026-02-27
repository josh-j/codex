# ncs-reporter

Standalone Python CLI that processes raw Ansible telemetry into HTML dashboards, STIG compliance reports, and CKLB artifacts. It is Stage 2 of a fully decoupled two-stage reporting pipeline.

## Pipeline Overview

```
Stage 1 — Collect (Ansible)
  Roles run modules, emit raw_*.yaml artifacts via ncs_collector callback

Stage 2 — Report (ncs-reporter)
  Normalizes raw data, evaluates alerts, renders HTML / CKLB
```

`ncs-reporter` never touches a live host. All tests run without an inventory.

## Setup

```bash
cd tools/ncs_reporter
just setup        # creates .venv, installs ncs-reporter in editable mode
```

Or from the repo root:

```bash
just setup-tools  # installs ncs-reporter system-wide (editable)
```

## CLI Commands

### `all` — Full fleet render

Aggregates all platform directories and renders every report type in one pass.

```bash
ncs-reporter all \
  --platform-root /srv/reports/platform \
  --reports-root  /srv/reports \
  --groups        /srv/reports/platform/inventory_groups.json
```

| Option | Description |
|---|---|
| `--platform-root` | Root directory containing `ubuntu/`, `vmware/`, `windows/` subdirs |
| `--reports-root` | Output directory for generated HTML |
| `--groups` | Inventory groups JSON/YAML (used for site dashboard grouping) |
| `--report-stamp` | Override date stamp (YYYYMMDD); defaults to today |
| `--csv/--no-csv` | Enable/disable CSV exports for Windows (default: on) |

---

### `site` — Global site dashboard

```bash
ncs-reporter site \
  --input  /srv/reports/platform/all_hosts_state.yaml \
  --groups /srv/reports/platform/inventory_groups.json \
  --output-dir /srv/reports
```

---

### `linux` / `vmware` / `windows` — Platform fleet reports

```bash
ncs-reporter linux   --input linux_fleet_state.yaml   --output-dir reports/platform/ubuntu
ncs-reporter vmware  --input vmware_fleet_state.yaml  --output-dir reports/platform/vmware
ncs-reporter windows --input windows_fleet_state.yaml --output-dir reports/platform/windows
```

---

### `node` — Single host report from raw YAML

```bash
ncs-reporter node \
  --platform vmware \
  --input    raw_vmware_discovery.yaml \
  --hostname vcenter1 \
  --output-dir reports/
```

---

### `stig` — STIG compliance reports

Renders per-host STIG reports and a fleet overview from an aggregated state file.

```bash
ncs-reporter stig \
  --input    /srv/reports/platform/all_hosts_state.yaml \
  --output-dir reports/stig
```

---

### `cklb` — CKLB artifact export

Generates `.cklb` files for import into STIG Viewer.

```bash
ncs-reporter cklb \
  --input      /srv/reports/platform/all_hosts_state.yaml \
  --output-dir reports/cklb
```

---

### `collect` — Aggregate raw host YAMLs

Walks a directory of per-host raw YAML artifacts and merges them into a single fleet state file.

```bash
ncs-reporter collect \
  --report-dir /srv/reports/platform/vmware \
  --output     vmware_fleet_state.yaml
```

---

### `stig-apply` — Break-glass ESXi STIG hardening (interactive)

Reads a `raw_stig_esxi.yaml` audit artifact, extracts failing rules, and applies them **one at a time** with a confirmation prompt between each. Ansible is invoked as a subprocess per rule so output is live-streamed and side effects are visible before the next rule runs.

```
$ ncs-reporter stig-apply artifacts/vcenter1/raw_stig_esxi.yaml --limit vcenter1

Found 12 failing rule(s). Taking pre-hardening snapshot...
[ansible output...]
Snapshots done. Continue to rule application? [y/n/abort]: y

─────────────────────────────────────────────────────────────────
Rule 1/12: ESXI-70-000001  │  MEDIUM
Title:   Access to the ESXi host must be limited by enabling lockdown mode.
Finding: Lockdown mode is disabled on esxi1.prod
Fix:     From the vSphere Client, go to Hosts and Clusters…
─────────────────────────────────────────────────────────────────
Apply this rule? [y/n/abort]: y

PLAY [Phase 2c | ESXi STIG Hardening] ...
TASK [stigrule_256375_lockdown_query] ok
TASK [stigrule_256375_lockdown_remediate] changed

Ansible exited with code 0.
Continue to next rule? [y/n/abort]: y
```

**How it works:**

1. Reads the artifact and filters to rules with `status=open`
2. Generates an all-disabled vars file (`esxi_70_NNNNNN_Manage: false` for all 75 rules)
3. For each failing rule, runs:
   ```bash
   ansible-playbook playbooks/vmware_stig_remediate.yml \
     -i inventory/production/hosts.yaml \
     -l <limit> \
     --skip-tags snapshot,vm \
     -e @/tmp/ncs_stig_disabled_*.yaml \
     -e esxi_70_NNNNNN_Manage=true \
     -e vmware_stig_enable_hardening=true
   ```

**Options:**

| Option | Default | Description |
|---|---|---|
| `ARTIFACT` | *(required)* | Path to `raw_stig_esxi.yaml` artifact |
| `--limit` | *(required)* | Ansible `--limit` value (e.g. `vcenter1`) |
| `--playbook` | `playbooks/vmware_stig_remediate.yml` | Playbook path |
| `--inventory` | `inventory/production/hosts.yaml` | Inventory path |
| `--skip-snapshot` | off | Skip the pre-hardening snapshot phase |
| `-e` / `--extra-vars` | — | Extra vars passed to every ansible invocation (repeatable) |
| `--dry-run` | off | Print generated commands without executing |

**Dry run (CI / validation):**

```bash
ncs-reporter stig-apply artifacts/raw_stig_esxi.yaml \
  --limit vcenter1 \
  --skip-snapshot \
  --dry-run
```

---

## Development

```bash
just lint         # ruff check
just format       # ruff format
just check        # mypy + basedpyright
just test         # pytest
just test-all     # lint + check + test
```

## Architecture

```
src/ncs_reporter/
├── cli.py                    # Click entry point — all commands
├── _stig_apply.py            # Break-glass ESXi apply helpers
├── _report_context.py        # Jinja env, YAML loaders, timestamp helpers
├── aggregation.py            # Multi-host state aggregation
├── normalization/            # Platform-specific data normalization + alert logic
│   ├── stig.py
│   ├── vmware.py
│   ├── linux.py
│   └── windows.py
├── view_models/              # Typed Pydantic view contracts for templates
├── models/                   # Pydantic base models
├── templates/                # Jinja2 HTML templates
├── cklb_skeletons/           # CKLB JSON skeletons (ESXi V1R4, VM V1R4)
├── alerts.py                 # Health rollup logic
├── cklb_export.py            # CKLB file generation
└── date_utils.py             # Date helpers
```

**Key conventions:**

- All health evaluation and status derivation lives in `normalization/` — never in templates or Ansible
- View model builders return Pydantic models; templates only render what they are given
- `ncs_collector` callback (Stage 1) writes `raw_*.yaml`; `ncs-reporter` (Stage 2) reads them
