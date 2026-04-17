# Scheduling & Alert Actions

NCS has two independent execution triggers. They operate on different axes
(clock vs. state) and compose into a feedback loop — the scheduler keeps
collected data fresh, the alert trigger reacts to what the fresh data reveals.

---

## Table of Contents

1. [Time-based scheduler (systemd timers)](#time-based-scheduler-systemd-timers)
2. [Alert-driven actions (`fire-on-alerts`)](#alert-driven-actions-fire-on-alerts)
3. [How they compose](#how-they-compose)
4. [When to use which](#when-to-use-which)

---

## Time-based scheduler (systemd timers)

Schedules full playbook runs against the wall clock.

### Config

All schedules live in one file at the repo root: `schedules.yml`.

```yaml
schedules:
  - name: nightly-fleet-audit
    description: "Full fleet audit and report pipeline"
    playbook: playbooks/site.yml
    calendar: "*-*-* 02:00:00"       # systemd OnCalendar syntax
    enabled: true
    notify_on_failure: true
    timeout_minutes: 180
```

**Supported fields**: `name`, `playbook`, `calendar`, `description`, `limit`,
`tags`, `extra_args`, `check_mode`, `enabled`, `notify_on_failure`,
`timeout_minutes`. See the inline docstring in
[`schedules.yml`](../schedules.yml) for defaults.

### Deployment

```bash
just apply-schedules
# or
ansible-playbook -i inventory/production playbooks/ncs/manage_schedules.yml
```

This reads `schedules.yml`, validates each entry, and deploys paired units to
`/etc/systemd/system/`:

- `ncs-<name>.service` — one-shot unit that executes the wrapper script
- `ncs-<name>.timer` — `OnCalendar=` trigger pointing at the service

Wrapper scripts land in `.cache/ncs-schedules/<name>.sh`. They handle working
directory, logging to `/var/log/ncs-schedules/<name>.log`, and failure
notification via `playbooks/core/send_alert_email.yml` when
`notify_on_failure: true`.

### Inspection

```bash
systemctl list-timers 'ncs-*'
systemctl status ncs-nightly-fleet-audit.timer
journalctl -u ncs-nightly-fleet-audit.service -n 100
tail -f /var/log/ncs-schedules/nightly-fleet-audit.log
```

### Runs

Any `ansible-playbook` target. Common patterns:

- `playbooks/site.yml` — full audit + report
- `playbooks/site_stig_audit.yml` — STIG compliance sweep
- `playbooks/ncs/generate_reports.yml` — rebuild dashboards from existing raw data
- `internal.linux.ubuntu_collect` (FQCN) — single-platform refresh

### State

systemd journal + the wrapper's per-unit log file. Nothing in-repo.

---

## Alert-driven actions (`fire-on-alerts`)

Reacts to alert conditions detected in a just-collected raw data bundle. Not a
scheduler — it's a condition-gated trigger invoked against a known snapshot of
fleet state.

### Config

Each `AlertRule` in a platform config (`configs/<platform>.yaml`) may carry an
`action:` stanza. Example from a vcsa config:

```yaml
alerts:
  - id: appliance_health_red
    category: "Appliance Health"
    severity: CRITICAL
    when: appliance_health_overall == 'red'
    msg: "VCSA component failure: overall health is RED"
    cooldown: 24h                    # per-alert, default 7d
    action:
      playbook: playbooks/core/send_alert_email.yml
      extra_vars:
        subject: "VCSA RED: {{ inventory_hostname }}"
      timeout: 60                    # seconds
```

`ActionSpec` ([`models/report_schema.py:198`](../ncs-reporter/src/ncs_reporter/models/report_schema.py#L198))
supports two mutually-exclusive forms:

- `playbook:` + `extra_vars:` — runs `ansible-playbook <playbook> -e <vars>`.
  Merged vars always include `alert_id`, `alert_severity`, `alert_host`, `alert_msg`.
- `command:` — runs a raw shell command. Rendered as a Jinja2 template with
  the full `fields:` context (e.g. `systemctl restart {{ service_name }}`).

### Invocation

```bash
ncs-reporter fire-on-alerts \
  -i /srv/samba/reports/platform/vmware/vcsa/vcenter-prod/raw_vcenter.yaml \
  --hostname vcenter-prod \
  --state-file /var/lib/ncs/alert_state.yaml \
  --project-dir /opt/codex
```

- `-i` — path to the raw bundle (what the collector wrote).
- `--hostname` — optional; auto-detected from bundle metadata when omitted.
- `--state-file` — tracks `last_fired` timestamps; default `.alert_state.yaml`
  in CWD. Pin to a stable location on any production host.
- `--project-dir` — directory to `cd` into before running the action playbook
  (so relative paths resolve).
- `--dry-run` — prints the action command without executing.

### Cooldown + state

Each alert carries a `cooldown:` (default `7d`, parsed as `\d+[dhms]`). When
an alert fires successfully, the state file records
`{<alert_id>: {<host>: {last_fired: <iso8601>}}}`. On the next invocation
within the cooldown window, the action is skipped and the CLI emits
`COOLDOWN: Nh remaining`.

When an alert stops firing (`current_fired` no longer includes it), its entry
is cleared from state. Next time it fires it's treated as a new event — the
cooldown clock resets.

### Runs

Whatever the `action:` stanza points to:

- a remediation playbook (e.g. restart a service)
- a notification playbook (`playbooks/core/send_alert_email.yml`)
- a raw shell command (slack webhook `curl`, PagerDuty event, etc.)

### Return codes

Exits non-zero if any action command returns non-zero. Schedulers gating on
this exit code can notify on failure.

---

## How they compose

The two triggers aren't parallel; they stack:

```
┌──────────────────────────┐
│  systemd timer (clock)   │   every N minutes / hours / days
└──────────────┬───────────┘
               ↓
┌──────────────────────────┐
│  ansible-playbook        │   e.g. playbooks/site.yml
│  site.yml / site_*.yml   │   collects raw_*.yaml
└──────────────┬───────────┘
               ↓
┌──────────────────────────┐
│  ncs_collector callback  │   persists raw bundles to
│  (internal.core)         │   /srv/samba/reports/platform/...
└──────────────┬───────────┘
               ↓
┌──────────────────────────┐
│  ncs-reporter render     │   HTML dashboards (optional)
│  playbooks/ncs/          │
│  generate_reports.yml    │
└──────────────┬───────────┘
               ↓
┌──────────────────────────┐
│  ncs-reporter            │   cooldown-gated,
│  fire-on-alerts          │   per-alert action execution
└──────────────────────────┘
```

### Example wiring

To turn alerts into a true event pipeline, add a scheduler entry that invokes
`fire-on-alerts` after a fresh collect. Either bundle it into a site
orchestrator, or schedule a thin wrapper:

```yaml
# schedules.yml
schedules:
  - name: hourly-alert-sweep
    description: "Collect + evaluate alerts + fire gated actions"
    playbook: playbooks/site_collect_and_alert.yml
    calendar: "hourly"
    enabled: true
    notify_on_failure: true
    timeout_minutes: 45
```

```yaml
# playbooks/site_collect_and_alert.yml (sketch — not yet in repo)
- import_playbook: site_collect_only.yml

- name: Fire alert actions across the fleet
  hosts: localhost
  connection: local
  tasks:
    - name: Evaluate alerts per host + fire gated actions
      ansible.builtin.command:
        cmd: >-
          ncs-reporter fire-on-alerts
          -i {{ item }}
          --state-file /var/lib/ncs/alert_state.yaml
          --project-dir {{ playbook_dir }}/..
      loop: "{{ query('fileglob', '/srv/samba/reports/platform/**/raw_*.yaml') }}"
      changed_when: false
```

This glue playbook is not yet shipped — it's the natural bridge if you want
alerts to drive continuous action without manual CLI invocation.

---

## When to use which

| You want to... | Use |
|---|---|
| Run the full audit every night | **Scheduler**: add an entry to `schedules.yml` |
| Regenerate dashboards every hour off already-collected data | **Scheduler** pointing at `ncs/generate_reports.yml` |
| Page oncall when a VCSA goes RED | **Alert action**: `action.command:` → webhook, or `action.playbook:` → mail playbook |
| Automatically restart a failed service when detected | **Alert action**: `action.playbook:` → remediation playbook |
| Send a notification only once per day per host for the same issue | **Alert action** with `cooldown: 24h` |
| Run something on a fixed cadence regardless of state | **Scheduler** |
| Run something only when a threshold is crossed | **Alert action** |
| Both — detect *and* act on a recurring cadence | **Both**: scheduler runs collect + `fire-on-alerts` wrapper |

### State vs. schedule — mental model

- **Scheduler** asks: *what time is it?*
- **Alert action** asks: *what does the data say right now, and has it been
  long enough since we last reacted to this?*

Neither triggers the other directly. They share only the raw data written by
`ncs_collector`. This separation is deliberate: collection and reaction are
independently restartable, testable, and observable.
