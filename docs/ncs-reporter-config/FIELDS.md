# Fields (`vars:` block)

Fields are named values the reporter makes available to templates, alerts, and widgets. Every raw-bundle key auto-imports as a field; you only declare one in `vars:` when you need to compute, navigate, coerce, or threshold.

## The field producers

Exactly one of these keys defines how a field gets its value:

| Key | Purpose | Example |
|---|---|---|
| `path` | Pull from a JMES-style path into the raw bundle (with optional transform pipeline). Alias: `from`. | `path: ".cpu.load_avg_1m"` |
| `compute` | Render a Jinja2 expression over other fields. Alias: `expr`. | `compute: "{{ uptime_seconds / 86400 }}"` |
| `normalize` | Shape raw lists, objects, and scalar values with the generic normalization DSL. Prefer this for config-owned normalization. | `normalize: {count: disks}` |
| `template` | Render a full Jinja2 template over current fields and keep the native return value. Use only when `normalize` is too limited. | `template: "{% set out = [] %}...{{ out }}"` |
| `const` | Hard-coded literal. | `const: "production"` |
| `script` | Escape hatch for logic that cannot reasonably live in YAML. | `script: normalize_thing.py` |
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

For list shaping (filter, map, aggregate) use [`normalize:`](#normalize) — the legacy `list_filter` / `list_map` / `count_where` / `any_where` / `all_where` / `sum_field` field-spec keys have been retired in favor of the unified DSL.

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

## `normalize`

`normalize:` is the preferred way to keep product-specific shaping in config without writing Python helpers or large Jinja templates. It is intentionally generic: the reporter provides list/object/path primitives, while each collection owns its own config.

Common operations:

```yaml
datastore_count:
  type: int
  normalize: {count: datastores}

normalized_disks:
  type: list
  normalize:
    list:
      source:
        first_of:
          - disks
          - {flatten: "disk_results[].disks[]"}
      include_source: false
      map:
        name: {first_of: [name, device, {const: ""}]}
        used_pct: {first_of: [used_pct, {const: 0}]}

hosts_by_cluster:
  type: list
  normalize:
    list:
      for_each: cluster_results
      expand: clusters
      include_source: false
      map:
        cluster: item.key
        datacenter: parent.item
        host_names: {pluck: {source: item.value.hosts, path: name}}
```

### DSL operator reference

The `normalize:` body is one of the operator dicts below. Operators compose recursively — any `source:` / `key:` / `value:` slot accepts another operator dict, a string path, or a literal scalar.

#### Path access

| Op | Purpose | Example |
|---|---|---|
| `const` | Literal value (any type). | `{const: 1}` |
| `path` / `from` | Dotted-path lookup into the bundle, current `item`, or `parent`. | `{path: appliance.summary.uptime}` |
| `flatten` | Walk a path with `[]` to expand list segments. | `{flatten: "results[].datastores[]"}` |
| `defined` | True iff the operand is present (not `None`). | `{defined: vcenters}` |

#### Composition

| Op | Purpose | Example |
|---|---|---|
| `first_of` | Return the first non-empty candidate. Treats `None`/`""`/`[]`/`{}` as absent; `0` and `False` are present. Optional `default:`. | `{first_of: [a, b, {const: 0}]}` |
| `if` | Conditional. `if:` is a predicate; returns `then:` if true, else `else:` (or `None`). | `{if: {defined: x}, then: {count: x}, else: {const: 0}}` |
| `object` | Build a dict by evaluating each value spec. | `{object: {hostname: hostname, uptime_d: {expr: "..."}}}` |
| `merge` | Combine dicts in precedence order (earlier wins). | `{merge: [overrides, defaults]}` |

#### Lists

| Op | Purpose | Example |
|---|---|---|
| `list` | Build a list from `source:` or `for_each:`/`expand:`. Filter via `include_where:` / `exclude_where:` / `exclude_match_any:`; reshape with `map:`; suppress passthrough with `include_source: false`. | (see below) |
| `count` | Length of the operand (list, dict, or string); 0 otherwise. | `{count: items}` |
| `pluck` | Project a path off each element of a list (or dict, treated as a list of `{key, value}` rows). | `{pluck: {source: faults, path: faultInst.attributes}}` |
| `slice` | Python-style slice with `start:` / `stop:` / `step:`. | `{slice: {source: events, stop: 500}}` |
| `sort` | Stable sort by an optional `by:` path; `reverse: true` for descending. | `{sort: {source: hits, by: utilMax, reverse: true}}` |
| `unique` | Deduplicate keeping first occurrence; optional `by:` path. | `{unique: {source: rows, by: interface_label}}` |

#### Indexing / lookup

| Op | Purpose | Example |
|---|---|---|
| `find` | Return the first list item matching a predicate dict. | `{find: {source: tags, where: {category: Owner}}}` |
| `get` | `dict.get(key, default)` for an arbitrary source dict. | `{get: {source: shadow_map, key: name, default: 0}}` |
| `index` | Build a `{key: value}` dict from a list (or dict) source. | `{index: {source: results, key: item.name, value: json}}` |

#### Scalars

| Op | Purpose | Example |
|---|---|---|
| `truthy` | Coerce to bool with sensible string handling (`"0"`, `"false"`, `"no"`, `"off"` → false). | `{truthy: ssh_enabled}` |
| `lookup` | Map an operand value through a dict of replacements. | `{lookup: {value: severity, map: {high: critical, low: info}, default: warn}}` |
| `regex_search` | First regex match of `pattern` against `value`; capture group 1 if present, else group 0. | `{regex_search: {value: dn, pattern: '^.*\]'}}` |
| `regex_replace` | Substitute `pattern` with `replacement` (supports backrefs `\1`, `\2`, …) in `value`. Optional `count:` (max replacements; 0 = all) and `ignorecase: true`. | `{regex_replace: {value: dn, pattern: '^.*/(node-\d+)/.*?\[(.*?)\]/.*$', replacement: 'leaf \1 \2'}}` |
| `age_days` | Days between `value` (ISO-8601) and `reference` (default: now). Optional `round:`. | `{age_days: {value: created, reference: collected_at, round: 1}}` |
| `expr` / `compute` | Evaluate a Jinja2 expression; returns native types. | `{expr: "{{ size_total | float / 1073741824 }}"}` |
| `template` | Render a multi-statement Jinja template. | `{template: "{% set out = [] %}...{{ out }}"}` |

Use `list.source` for a single list, or `list.for_each` plus `expand` for parent/child raw structures. `for_each` accepts either a list or a dict — when given a dict, each iteration's `item` is `{key: ..., value: ...}`. `pluck.source`, `index.source`, and `merge:` sources all accept dicts the same way. Inside `map`, `item` is the current row and `parent` is the containing row. Earlier mapped values are also available to later mapped fields.

### Filtering with `include_where` / `exclude_where`

`list:` accepts predicate clauses to keep or drop rows before `map:` runs:

```yaml
powered_on_vms:
  type: list
  normalize:
    list:
      source: virtual_machines
      include_where: {power_state: poweredOn}

big_powered_on_vms:
  type: list
  normalize:
    list:
      source: virtual_machines
      # Multiple clauses combined with AND.
      include_where:
        - {power_state: poweredOn}
        - {field: memory_gb, op: gt, value: 8}

real_vms:
  type: list
  normalize:
    list:
      source: virtual_machines
      # `any:` flips a clause group to OR semantics. Useful for
      # exclude_where when several disjoint conditions should drop a row.
      exclude_where:
        any:
          - {field: name, op: matches, value: '^infra-'}
          - {power_state: suspended}
```

Predicate operators: `eq` (default for `{field: value}` shorthand), `ne`, `gt`, `ge`, `lt`, `le`, `in`, `not_in`, `contains`, `matches` (case-insensitive regex). Predicates compose via `any:`, `all:` (default), and `not:`.

Predicate `value:` is treated literally when it's a scalar (so `value: '^infra-'` is a regex literal, not a field path). To resolve a path or expression for the `value`, wrap it explicitly: `value: {path: snapshot_age_days}` or `value: {expr: "{{ ... }}"}`.

### Slicing

`slice:` returns a Python-style slice of a list:

```yaml
top_5_alarms:
  type: list
  normalize:
    slice:
      source: alarms_sorted
      start: 0
      stop: 5
```

### Sort, unique, top-N

`sort:` and `unique:` chain naturally with `slice:`:

```yaml
top_busy_interfaces:
  type: list
  normalize:
    slice:
      source:
        unique:
          source:
            sort:
              source: interface_rows
              by: utilMax
              reverse: true
          by: interface_label
      stop: 10
```

`sort.by:` resolves a dotted path against each row; missing values sort last. `unique:` keeps the first occurrence — sort first if you want a particular winner.

### Conditionals: `if`/`defined`

`first_of:` only skips empty values (`None` / `""` / `[]` / `{}`); a literal `0` or `False` is "present" and stops the chain. Use `if:` with a `defined:` predicate when you want to distinguish "field is missing" from "field is zero":

```yaml
vcenter_count:
  type: int
  normalize:
    first_of:
      # Tree mode injects `vcenters`; standalone mode does not.
      - {if: {defined: vcenters}, then: {count: vcenters}}
      - {const: 1}
```

`defined:` works both as a top-level op (returning a bool field) and as a predicate inside `include_where:` / `exclude_where:`:

```yaml
vms_with_owner:
  type: list
  normalize:
    list:
      source: virtual_machines
      include_where: {defined: owner_email}
```

### Building dicts: `object`/`merge`/`index`

`object:` constructs a dict by evaluating each value spec; `merge:` combines dicts with precedence; `index:` re-keys a list:

```yaml
appliance_rest:
  type: dict
  normalize:
    first_of:
      - appliance_rest                                                      # legacy pre-shaped
      - {index: {source: appliance_rest_results, key: item.item, value: item.json}}
      - {const: {}}

effective_config:
  type: dict
  normalize:
    merge:
      - host_overrides       # wins
      - cluster_defaults
      - {const: {timeout: 30, retries: 3}}
```

### Joining via lookup

Combine `index:` to build a lookup table once, then `get:` (or an `expr:` inside `map:`) to enrich each row:

```yaml
shadow_map:
  type: dict
  normalize:
    index:
      source:
        list:
          source: shadow_lines
          include_source: false
          map:
            name:        {expr: "{{ ((item | string).split(':') + ['', ''])[0] }}"}
            last_change: {expr: "{{ ((item | string).split(':') + ['', '', '0'])[2] | int(0) }}"}
      key: name
      value: last_change

users:
  type: list
  normalize:
    list:
      for_each: getent_passwd
      include_source: false
      map:
        name: item.key
        uid:  item.value.1
        password_age_days:
          expr: "(epoch_days - (shadow_map.get(item.key, 0) | int(0))) if (shadow_map.get(item.key, 0) | int(0)) > 0 else -1"
```

## `template`

`template:` is a lower-level fallback for config-owned normalization that needs loops, temporary lists, or dictionaries that the generic `normalize` DSL cannot express. It uses the same native Jinja environment as alerts and widgets, so a final `{{ out }}` can return a real list or dict:

```yaml
normalized_disks:
  type: list
  template: >-
    {%- set out = [] -%}
    {%- for disk in raw_disks | default([]) -%}
      {%- set _ = out.append({"name": disk.name, "used_pct": disk.used_pct | default(0)}) -%}
    {%- endfor -%}
    {{ out }}
```

Template fields run after path/compute/normalize fields and before script fields. A final compute pass runs afterward, so computed fields may reference template outputs.

Useful helpers include `coalesce(...)`, `truthy(value)`, `lookup(value, mapping, default)`, `regex_search`, and `age_days`.

## Type coercion

`type:` is applied after `path`/`compute`/`normalize`/`template`/`script`/`const` returns. Valid values: `str`, `int`, `float`, `bool`, `list`, `dict`. Coercion is strict; a missing or non-coercible value falls through to `fallback:` (if set) or raises.

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

For values that can't be expressed declaratively. The helper is a plain script under the collection's `ncs_configs/scripts/`; the reporter sends `{"fields": {...}, "args": {...}}` on stdin and reads a JSON-serializable value from stdout.

```yaml
vms:
  script:
    run: "get_vms_list.py"
```

Helpers are discovered relative to the config dir declaring them and run inside the reporter's venv.

Use `script_bundles` when one helper returns a mapping of many derived fields.
The reporter executes the helper once for each unique script plus args pair,
then unpacks the requested keys:

```yaml
script_bundles:
  - script:
      run: normalize_platform_bundle.py
    unpack:
      health: {type: str}
      item_count:
        type: int
        thresholds:
          warn_if_above: 1
```

## Diagnosing empty fields

If a field silently renders as empty:

1. Check `path:` — run `ncs-reporter node --platform <p> --input raw_<type>.yaml --hostname <h> --debug` to dump the pre-render context and confirm the underlying key exists.
2. Check `type:` — strict coercion with no `fallback:` raises; watch the log for the field name.
3. Check `$include:` paths — missing include files fail loudly at config load, but a typo'd field inside a correctly-included file is an ordinary missing key.
