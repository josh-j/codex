# internal.ios.ios

The single role for the `internal.ios` collection. Covers both classic
IOS and IOS-XE; per-host divergence is handled at fact-gather time via
`cisco.ios.ios_facts`.

## Actions

- `ncs_action: collect` → `tasks/collect.yaml`
  Gathers `ios_facts` + a small set of `show` commands and emits a
  payload under `ios/<hostname>/raw.yaml` for ncs-reporter.
- `ncs_action: operate` + `ncs_operation: <op>` → `tasks/ops/<op>.yaml`
  - `switchport_config`
  - `apply_template`
  - `change_syslog`

See `tasks/main.yaml` for the dispatch map.

## Variables

Defaults live in `defaults/main.yaml`; every variable is prefixed `ios_*`.
The console annotation block in `playbooks/ios_ops.yml` is the
operator-facing source of truth for which vars each op consumes.
