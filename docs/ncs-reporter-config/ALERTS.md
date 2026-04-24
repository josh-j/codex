# Alerts (`alerts:` block)

Alert rules are the reporter's health-evaluation layer. Each rule is a Jinja2 condition plus metadata; the reporter evaluates every rule against every host's field context on each run.

## Shape

```yaml
alerts:
  - id: memory_critical           # required — unique within the platform
    category: "Capacity"          # optional — groups alerts in the UI
    severity: CRITICAL            # CRITICAL | WARNING | INFO (default WARNING)
    when: memory_used_pct >= 98.0 # required — Jinja2 boolean expression
    message: "Memory saturation: {{ memory_used_pct | round(1) }}% used"
    suppress_if: <other_alert_id> # optional — skip this rule if referenced one fired
    items:                        # optional — one alert per matching row
      rows_from: disks
      when: "used_pct >= 95"
    action:                       # optional — executed on fire; see SCHEDULING_AND_ALERT_ACTIONS.md
      playbook: internal.core.send_alert_email
      extra_vars:
        subject: "mem critical on {{ hostname }}"
      timeout: 120
      cooldown: 3600              # seconds between repeat fires for the same (host, alert id)
```

`id` is the stable handle — alerts are joined to cooldown state, `suppress_if` links, and the `fire-on-alerts` action runner by id. Changing an id resets its cooldown window and breaks any `suppress_if` references.

## Severity ladder

Three levels:

| Severity | Meaning | Typical trigger |
|---|---|---|
| `CRITICAL` | Immediate attention; likely user-visible impact | ≥ 98% memory, ≥ 95% disk, failed service, missing security patch flagged critical |
| `WARNING`  | Approaching a problem; plan to act | ≥ 85% memory, ≥ 80% disk, reboot pending, pending updates |
| `INFO`     | Worth noticing, not actionable on its own | uptime > 90 days, deprecated feature detected |

The reporter rolls severities up to cluster / datacenter / site views by max-wins (any CRITICAL child marks the parent CRITICAL). Fleet tables sort on severity count.

## Writing `when:` expressions

The expression is a Jinja2 boolean, rendered with the host's full field context. Every field declared in `vars:` and every auto-imported bundle key is in scope:

```yaml
- id: services_failed
  severity: CRITICAL
  when: failed_services_count > 0
  message: "{{ failed_services_count }} systemd service(s) failed"

- id: disk_critical
  severity: CRITICAL
  when: disks | selectattr('used_pct', 'ge', 95.0) | list | length > 0
  message: "One or more filesystems critically full (>=95%)"
```

Expressions are rendered inside `{{ ... }}` — you don't wrap the outer expression in braces. If you need multi-line, quote the whole thing with YAML `|`/`>` block scalars; the reporter strips the surrounding whitespace.

## Suppression

`suppress_if: <other_alert_id>` means "don't fire me if that rule already fired for this host." Use it to model a warning that becomes moot once the critical version fires:

```yaml
- id: memory_critical
  severity: CRITICAL
  when: memory_used_pct >= 98.0
  message: "Memory saturation: {{ memory_used_pct | round(1) }}% used"

- id: memory_warning
  severity: WARNING
  suppress_if: memory_critical
  when: memory_used_pct >= 85.0
  message: "Memory pressure: {{ memory_used_pct | round(1) }}% used"
```

Evaluation order is: all `when:` expressions first, then `suppress_if:` resolution. Chains are allowed (`B.suppress_if=A`, `C.suppress_if=B`) but cycles fail loudly at config load.

## Per-row alerts (`items:`)

Most alerts are per-host. `items:` promotes one alert to per-row, fanning out over a list field:

```yaml
- id: disk_row_critical
  severity: CRITICAL
  category: "Capacity"
  items:
    rows_from: disks
    when: "used_pct >= 95"
  message: "{{ mount }} at {{ used_pct }}% ({{ total_gb | round(1) }} GB)"
```

Each matching row gets its own alert entry with the row's fields merged into the message context. The sum-count rolls up to the host-level severity.

## Actions and cooldown

`action:` attaches an executable response to an alert. It runs only when the alert fires **and** the cooldown has elapsed since the last fire for this (host, alert id) pair. Both `playbook:` (Ansible FQCN) and `command:` (shell) are supported; see [SCHEDULING_AND_ALERT_ACTIONS.md](SCHEDULING_AND_ALERT_ACTIONS.md) for how `fire-on-alerts` drives execution and stores cooldown state.

## Naming conventions

- `<subject>_<severity>` → `memory_critical`, `disk_warning`, `reboot_pending`.
- Category is free-form but stick to the existing set (`Capacity`, `Availability`, `Patching`, `Maintenance`, `Security`, `Compliance`) so cross-platform rollups group naturally.
- Keep messages first-person operational: what happened, with enough numbers to act on. Include `{{ hostname }}` only if the alert will be seen outside a host-scoped view.

## Common mistakes

- **Comparing strings to numbers.** A numeric bundle field coerced as `type: str` silently becomes a string and `>= 95` is always false. Set `type:` on the field in `vars:`.
- **Forgetting the render braces.** `when:` is a Jinja expression; conditions like `when: memory_used_pct >= 98.0` work because the reporter wraps it. But `when: "{{ memory_used_pct >= 98.0 }}"` renders to the literal string `"True"`/`"False"` and then treats a non-empty string as truthy — always fires. Don't wrap in braces.
- **`suppress_if:` pointing at an alert defined in a different schema.** Suppression only resolves within the same `alerts:` block.
