# internal.core.stig

Shared STIG compliance utilities used by all platform collections (Ubuntu, VMware, Windows).

## Tasks

### `finalize.yaml`

Normalizes `audit_full_list`, exports YAML state, generates CKLB artifacts, and renders an HTML report.

| Variable | Required | Description |
|---|---|---|
| `audit_full_list` | yes | List of dicts with at minimum `id`, `status`, `name` |
| `stig_target_type` | no | Platform identifier (e.g. `ubuntu_2404`, `esxi`, `vm`, `windows_server_2022`) |
| `ncs_export_path` | no | Absolute path for YAML state export |
| `stig_skeleton_path` | no | Path to CKLB skeleton JSON. CKLB generation is skipped if undefined |
| `stig_export_cklb` | no | Enable/disable CKLB generation (default: `true`) |
| `stig_quiet_mode` | no | Suppress debug output (default: `false`) |

### `read_callback_artifact.yaml`

Reads a single host's `stig_xml` callback JSON artifact and sets `audit_full_list`. Remaps `fixed` to `failed` when not in hardening mode.

| Variable | Required | Description |
|---|---|---|
| `_stig_artifacts_dir` | yes | Path to `.artifacts/` directory |
| `_stig_artifact_host_hint` | yes | Hostname substring to match in artifact filename |
| `_stig_is_hardening` | no | When `false`, `fixed` status becomes `failed` (default: `false`) |
| `_stig_require_artifact` | no | Fail if no artifact found (default: `true`) |

### `read_callback_artifacts_multi.yaml`

Multi-host variant. Loops over a list of target hosts, reads each host's artifact by exact filename (`xccdf-results_<host>.json`), and merges all rows into a single `audit_full_list`.

| Variable | Required | Description |
|---|---|---|
| `_stig_target_hosts` | yes | List of hostnames to read artifacts for |
| `_stig_artifacts_dir` | yes | Path to `.artifacts/` directory |
| `_stig_is_hardening` | no | When `false`, `fixed` status becomes `failed` (default: `false`) |

### `audit_orchestrator.yaml`

Generic evaluation engine. Renders an inline or file-based Jinja2 audit logic template against each item in `raw_discovery_data` and accumulates results. Used by VMware `_checks_orchestrator.yaml` and Windows `check.yaml`.

| Variable | Required | Description |
|---|---|---|
| `raw_discovery_data` | yes | List of discovery fact dicts, one per target |
| `audit_logic_template` | yes* | Absolute path to Jinja2 evaluation template |
| `audit_logic_inline` | yes* | Inline Jinja2 template string (alternative to file) |
| `stig_filter` | no | Only evaluate items matching this name |
| `stig_exclusions` | no | List of item names to skip |

*One of `audit_logic_template` or `audit_logic_inline` is required.

## Filter Plugins

These live in `internal/core/plugins/filter/` and are available as `internal.core.<name>`:

| Filter | File | Description |
|---|---|---|
| `normalize_stig_results` | `stig.py` | Canonicalizes status values, extracts violations/alerts/summary |
| `stig_eval` | `stig.py` | Evaluates a list of rule dicts (with `check` booleans) into pass/fail rows |
| `get_adv` | `stig.py` | Looks up a key in a list of vSphere advanced setting dicts |

## Callback Plugin

`internal/core/plugins/callback/stig_xml.py` — Captures results from tasks named `stigrule_NNNNNN_*` and writes per-host JSON and XCCDF XML artifacts to `.artifacts/`.

Key behaviors:
- Extracts rule numbers via regex from task names (`stigrule_`, `V-`, `SV-`, `R-` prefixes)
- In check mode, `changed` = non-compliant (`failed`); in apply mode, `changed` = `fixed`
- Supports `stig_target_host` task variable to override host attribution (for API-based platforms)
- Each JSON row includes a `name` field set to the attributed host

## Files

| File | Description |
|---|---|
| `files/create_skeleton.py` | Offline CLI tool: parses DISA STIG XCCDF XML into a CKLB skeleton JSON |
| `templates/cklb_generic.json.j2` | Jinja2 template for generating CKLB artifacts |
| `templates/stig_report.html.j2` | Jinja2 template for the per-host HTML compliance report |

## Drop-In Contract

An external STIG tasks file (e.g. Ubuntu's `ubuntu2404.yaml`) works with zero modification if:

1. Compliance tasks are named `stigrule_NNNNNN_<description>`
2. Tasks are idempotent and work in `check_mode: true`
3. No manual result collection needed — the callback handles it

For API-based platforms (tasks execute on localhost targeting remote hosts):

4. Set `stig_target_host` via `apply.vars` on the `include_tasks` call
