# internal.__COLLECTION_NAME__.example

Minimal example role scaffolded by the collection template. Demonstrates
the NCS conventions — dispatch via `internal.core.dispatch`, emission
via `internal.core.emit` — without depending on any real platform.

Replace or duplicate this role with your actual platform logic; the
name `example` is intentional to remind you it's scaffolding.

## Quick use

From a playbook that lives in the collection's `playbooks/` dir:

```yaml
- name: "__COLLECTION_NAME__ | Example collect"
  hosts: "{{ example_target_hosts | default('localhost') }}"
  gather_facts: false
  roles:
    - role: internal.__COLLECTION_NAME__.example
      vars:
        ncs_action: collect
```

Run it:

```bash
ansible-playbook -i inventory/production internal.__COLLECTION_NAME__.example_collect
```

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `__collection_name___skip_export` | `false` | When `true`, skips the `internal.core.emit` step (no `raw_example.yaml` is written). |

Override these from inventory group_vars or host_vars. Prefix every
custom variable you add with the collection name so cross-collection
runs don't collide.

## What this role does

1. Gathers minimal facts via `ansible.builtin.setup`.
2. Builds a small payload (hostname, OS info, uptime).
3. Emits it as `raw_example.yaml` under the telemetry lake so
   `ncs-reporter` can read it.

The STIG flow (audit/remediate/verify phases via
`internal.core.stig_orchestrator`) is not demonstrated here — see
the built-in collections' `tasks/stig.yaml` + `tasks/stig_<version>/`
directories for that pattern, or `HELPERS.md` for a summary.
