# NCS Collection Patterns

A quick reference for the conventions every `internal.<col>` collection
follows. This document ships inside the template so each new collection
carries the context with it.

## Role interface contract

Every platform role takes three optional variables at the entry point:

| Variable | Values | Purpose |
|---|---|---|
| `ncs_action` | `collect`, `audit`, `remediate`, `verify` | What to do |
| `ncs_profile` | `stig`, `health`, … | Named behavior profile (mutually exclusive with `ncs_operation`) |
| `ncs_operation` | role-specific, e.g. `password_rotate` | Named maintenance operation (mutually exclusive with `ncs_profile`) |

A role's `tasks/main.yaml` calls `internal.core.dispatch` to route these
vars to the right task file:

```yaml
# roles/__ROLE_NAME__/tasks/main.yaml
---
- name: "Validate and dispatch"
  ansible.builtin.include_role:
    name: internal.core.dispatch
  vars:
    dispatch_map:
      collect:
        default: collect.yaml
      audit:
        stig: stig.yaml
        health: health.yaml
      remediate:
        stig: stig.yaml
      verify:
        stig: stig.yaml
      maintain:
        password_rotate: ops/password_rotate.yaml
        password_status: ops/password_status.yaml
```

## STIG workflow

For `ncs_profile: stig`, the role delegates to
`internal.core.stig_orchestrator`, which runs three phases:

1. **Phase 0**: facts + validation (e.g. required vars, target type
   inference).
2. **Phase 1**: audit (check_mode) or remediate (apply changes), driven
   by the same `tasks/stig.yaml` so the two modes stay symmetric.
3. **Phase 2**: post-remediation verification via a check_mode audit.

Each individual rule task uses the `internal.core.stig` action plugin:

```yaml
- name: "stigrule_<id>"
  internal.core.stig:
    _stig_gate_packages: [some-pkg]      # skip the rule if the package isn't installed
    _stig_gate_status: not_applicable    # what to record when gated out
    _stig_check: |                       # shell: rc=0 means compliant
      set -eu
      grep -qE '^\s*setting\s*=\s*value\s*$' /etc/foo/conf
    cmd: |                               # shell: applied in remediate mode
      set -eu
      sed -i 's/.*setting.*/setting = value/' /etc/foo/conf
```

See `internal/core/plugins/action/stig.py` and the existing platform
collections' `roles/<role>/tasks/stig_<profile>/` directories for
real examples.

## Telemetry emission

Collection results flow to disk via the `ncs_collector` callback plugin
(shipped by `internal.core`). Roles emit data using
`internal.core.emit`:

```yaml
- name: "Emit host facts"
  ansible.builtin.include_role:
    name: internal.core.emit
  vars:
    emit_type: "raw_<collection>"
    emit_data: "{{ _collected_data }}"
```

The callback persists the emitted data to
`<report_directory>/platform/<platform>/<hostname>/raw_<type>.yaml`.

## ncs-console UI metadata

Playbooks can opt into ncs-console's UI via `# >>> / # <<<` block
comments at the top. Options and labels feed the operator-facing form:

```yaml
# >>>
# label: Rotate Password
# options:
#   rotate_user: text = root | Username | Local account to rotate password for
#   rotate_password: text | New Password (blank = use vault) | Leave blank to use vault_rotate_password
#   rotate_force_change: bool = true | Force Password Change at Login | Require user to change password on next login
# <<<
---
- name: "aci | Rotate local account password"
  hosts: "{{ aci_target_hosts | default('aci_servers') }}"
  ...
```

Option format: `<name>: <type>[choices] = <default> | <label> | <tooltip>`.
Type is one of `text`, `bool`, `select` (with `choices` in brackets).
Multiple `# >>> / # <<<` blocks define a multi-profile playbook
(e.g. `run.yml`); ncs-console renders a profile picker.

The `is_read_only: true` flag marks a playbook as non-mutating (audit/
collect) so ncs-console doesn't surface the "⚠ This action makes changes
to remote hosts" warning.

## Adding to the app repo

Once the sibling repo is populated:

1. **Build a tarball** in `ncs-ansible`:
   ```bash
   just build-collection aci
   ```
   This needs the sibling repo at `../ncs-ansible-aci/`.

2. **Vendor it** so `git pull` carries it to every consumer:
   ```bash
   just vendor-collections
   ```

3. **Add to `requirements.yml`** (Mode A block) so
   `ansible-galaxy collection install` picks it up:
   ```yaml
   - name: "./collections/vendor/internal-aci-0.1.0.tar.gz"
     type: file
   ```

4. **Install + verify**:
   ```bash
   just install-collections
   ansible-galaxy collection list | grep aci
   ansible-playbook --syntax-check -i inventory/production internal.aci.<some_playbook>
   ```

5. **Commit the tarball + requirements.yml bump**.

From there, `just release-collection aci <version> "<message>"`
handles subsequent version bumps against the sibling repo, and
`just vendor-collections` refreshes the in-repo tarball.
