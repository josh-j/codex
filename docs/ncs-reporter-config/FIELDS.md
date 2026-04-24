# Fields (`vars:` block)

Fields are named values the reporter makes available to templates, alerts, and widgets. Every raw-bundle key auto-imports as a field; you only declare one in `vars:` when you need to compute, navigate, coerce, or threshold.

## The five producers

Exactly one of these keys defines how a field gets its value:

| Key | Purpose | Example |
|---|---|---|
| `path` | Pull from a JMES-style path into the raw bundle (with optional transform pipeline). Alias: `from`. | `path: ".cpu.load_avg_1m"` |
| `compute` | Render a Jinja2 expression over other fields. Alias: `expr`. | `compute: "{{ uptime_seconds / 86400 }}"` |
| `const` | Hard-coded literal. | `const: "production"` |
| `script` | Run a Python helper from the collection's `ncs_configs/scripts/` and take its return value. | `script: assemble_esxi_hosts.build` |
| (none) | Field is declared only to attach `thresholds:` or `type:` to an auto-imported key. | (see below) |

## Minimum declarations

Flat bundle keys auto-import, so the shortest useful vars entry is an empty body that just attaches metadata:

```yaml
memory_total_mb:
  type: int
  thresholds:
    warn_if_above: 14000
```

This declares nothing new — it hooks thresholds onto the already-imported `memory_total_mb` so widgets can highlight and alerts can reference the resulting `memory_total_mb_exceeds_warn` / `…_exceeds_crit` booleans.

## `path` and the transform pipeline

`path:` accepts a leading-dot JMES path plus `| transform_name` filters:

```yaml
failed_services_count:
  path: ".failed_services.stdout_lines | len_if_list"
  type: int
  thresholds:
    crit_if_above: 1

pending_updates_count:
  path: ".apt_simulate.stdout_lines | join_lines | regex_extract('(\\d+) upgraded,')"
  type: int
```

Built-in transforms available in collectors (non-exhaustive): `len_if_list`, `join_lines`, `regex_extract('<pattern>')`, `to_int`, `to_float`, `to_bool`, `strip`, `lower`. See `ncs-reporter/src/ncs_reporter/_config.py` for the full set.

`list_filter`, `list_map`, `count_where`, `any_where`, `all_where`, and `sum_field` are declarative list operations — use them when the pipeline filter syntax gets awkward:

```yaml
filesystems_near_full:
  path: ".disks"
  list_filter: "used_pct >= 80"
  sum_field: used_pct          # optional — aggregate after filtering
```

## `compute`

`compute:` is a Jinja2 expression with every other field in scope. Expressions see the already-computed values of sibling fields, so you can chain:

```yaml
uptime_days:
  compute: "{{ uptime_seconds / 86400 }}"

memory_used_pct:
  compute: "{{ (memory_total_mb - memory_free_mb) / memory_total_mb * 100 }}"
  thresholds:
    warn_if_above: 85
    crit_if_above: 98
```

Field order doesn't matter — the reporter topologically sorts compute dependencies at load time.

## Type coercion

`type:` is applied after `path`/`compute`/`const` returns. Valid values: `str`, `int`, `float`, `bool`, `list`, `dict`. Coercion is strict; a missing or non-coercible value falls through to `fallback:` (if set) or raises.

```yaml
reboot_pending:
  path: ".reboot_stat.stat.exists"
  type: bool
  fallback: false
```

Use `sentinel:` to mark "not applicable" rather than "missing": a field with `sentinel: "N/A"` renders as that literal and is excluded from threshold evaluation.

## Thresholds

`thresholds:` attaches numeric breakpoints to a field. The reporter materializes boolean companions you can reference anywhere:

```yaml
memory_used_pct:
  compute: "{{ (memory_total_mb - memory_free_mb) / memory_total_mb * 100 }}"
  thresholds:
    warn_if_above: 85
    crit_if_above: 98
```

Produces (implicitly):
- `memory_used_pct_exceeds_warn` (true when ≥ 85)
- `memory_used_pct_exceeds_crit` (true when ≥ 98)

Widgets use these to color cells; alerts can reference them instead of repeating the numeric threshold.

## `format`

`format:` is a Python f-string-style format applied after coercion, only for display. Does not affect alert evaluation.

```yaml
memory_used_pct:
  compute: "{{ (memory_total_mb - memory_free_mb) / memory_total_mb * 100 }}"
  format: "{:.1f}%"
```

## `script`

For values that can't be expressed declaratively. The helper is a plain Python module under the collection's `ncs_configs/scripts/`; the referenced symbol is called with `(bundle, context)` and must return a JSON-serializable value.

```yaml
vcsa_assembled_hosts:
  script: assemble_esxi_hosts.build
```

Helpers are discovered relative to the config dir declaring them and run inside the reporter's venv.

## Diagnosing empty fields

If a field silently renders as empty:

1. Check `path:` — run `ncs-reporter node --platform <p> --input raw_<type>.yaml --hostname <h> --debug` to dump the pre-render context and confirm the underlying key exists.
2. Check `type:` — strict coercion with no `fallback:` raises; watch the log for the field name.
3. Check `$include:` paths — missing include files fail loudly at config load, but a typo'd field inside a correctly-included file is an ordinary missing key.
