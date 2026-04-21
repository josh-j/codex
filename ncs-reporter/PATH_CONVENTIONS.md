# Path Conventions

This document explains the directory structures and path mapping logic used by `ncs-reporter` for consuming raw telemetry and generating HTML reports.

## Canonical Source of Truth

Pathing is defined by the user-owned `platforms.yaml` file.  
`ncs-reporter`, collector-side exports, and downstream verifiers should resolve report paths from this YAML contract, not from hardcoded path assumptions.

Collector runtime is strict for STIG telemetry:
- Every emitted `stig_target_type` must exist in `platforms.yaml` `target_types`.
- If a target type is missing, callback persistence fails fast instead of guessing a path.

Each platform entry must include a `paths` block with these required templates:

- `raw_stig_artifact`
- `report_fleet`
- `report_node_latest`
- `report_node_historical`
- `report_stig_host`
- `report_search_entry`
- `report_site`
- `report_stig_fleet`

Template placeholders are validated strictly. Required placeholders are:

- `raw_stig_artifact`: `{report_dir}`, `{hostname}`, `{target_type}`
- `report_fleet`: `{report_dir}`, `{schema_name}`
- `report_node_latest`: `{report_dir}`, `{hostname}`
- `report_node_historical`: `{report_dir}`, `{hostname}`, `{report_stamp}`
- `report_stig_host`: `{report_dir}`, `{hostname}`, `{target_type}`
- `report_search_entry`: `{report_dir}`, `{hostname}`

## 1. Input Structure (Telemetry Lake)

`ncs-reporter` expects a "Telemetry Lake" directory structure, typically populated by `ncs-collector`. 

**Pattern:** `<PLATFORM_ROOT>/{platform_category}/{sub_platform}/{hostname}/raw_{type}.yaml`

| Platform | Category | Sub-Platform | Example Path |
| :--- | :--- | :--- | :--- |
| **Linux (Ubuntu)** | `linux` | `ubuntu` | `linux/ubuntu/web-01/raw_discovery.yaml` |
| **Linux (Photon)** | `linux` | `photon` | `linux/photon/vcsa-01/raw_stig_photon.yaml` |
| **VMware (vCenter/VCSA)** | `vmware` | `vcenter/vcsa` | `vmware/vcenter/vcsa/vc-prod/raw_vcenter.yaml` |
| **VMware (ESXi)** | `vmware` | `esxi` | `vmware/esxi/esxi-01/raw_stig_esxi.yaml` |
| **Windows** | `windows` | (none) | `windows/win-srv-01/raw_audit.yaml` |

## 2. Output Structure (HTML Reports)

Reports are rendered into a flat hierarchy to ensure predictable relative linking for the "Global Search" and breadcrumb features.

### Global Reports
- `site.html`: The high-level site dashboard.
- `site.stig.html`: The cross-platform STIG compliance dashboard.
- `search_index.js`: The dynamic search database used by the UI.

### Fleet & Node Reports
Reports are grouped by their "Report Directory" (which may differ slightly from the input directory for legacy/aggregation reasons).

**Pattern:** `<REPORTS_ROOT>/platform/{report_dir}/{hostname}/health_report.html`

| Component | Path |
| :--- | :--- |
| **Fleet Dashboard** | `platform/{report_dir}/{report_dir}_fleet_report.html` |
| **Latest Node Report** | `platform/{report_dir}/{hostname}/health_report.html` |
| **Historical Node Report** | `platform/{report_dir}/{hostname}/health_report_{YYYYMMDD}.html` |

### STIG Specific Reports
STIG reports are nested according to the `target_type` of the audit.

**Pattern:** `<REPORTS_ROOT>/platform/{platform_dir}/{hostname}/{hostname}_stig_{target_type}.html`

| Target Type | Platform Directory |
| :--- | :--- |
| `ubuntu`, `linux` | `platform/linux/ubuntu` |
| `photon` | `platform/linux/photon` |
| `vcsa`, `vcenter` | `platform/vmware/vcenter/vcsa` |
| `vami`, `eam`, `lookup_svc`, `perfcharts`, `vcsa_photon_os`, `postgresql`, `rhttpproxy`, `sts`, `ui` | `platform/vmware/vcenter/vcsa` |
| `esxi` | `platform/vmware/esxi` |
| `vm` | `platform/vmware/vm` |
| `windows` | `platform/windows` |

## 3. History Navigation

When `ncs-reporter` renders a node report, it performs a local filesystem scan of the destination directory. 

1. It looks for files matching the pattern `health_report_*.html` (or `*_stig_*_*.html`).
2. It extracts the date stamp from the filename.
3. It populates the **History** dropdown in the breadcrumb bar with these links.

This allows the reports to remain completely static (serverless) while still providing a way to navigate time-series data.

## 4. Relative Path Resolution (`data-root`)

Because the reports are static and intended to be viewed via `file://` or simple web servers, they rely heavily on relative paths. 

The HTML templates include a `data-root` attribute on the search container which is calculated based on the directory depth:
- **Site Report**: `data-root="./"`
- **Fleet Report**: `data-root="../../"`
- **Node Report**: `data-root="../../../"`
- **STIG Node Report**: depth varies by target (for example, VCSA/component STIG under `platform/vmware/vcenter/vcsa/<host>/` uses `data-root="../../../../../"`).

The JavaScript logic uses this `data-root` to correctly locate `search_index.js` and resolve global search results regardless of which page the user is currently viewing.
